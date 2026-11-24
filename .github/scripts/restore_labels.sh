#!/usr/bin/env bash
# Label fix for ostree-rechunk (Faye 11-24): build-chunked-oci drops every image
# label, so bootc writes "version": null into /sysroot/.bootc-aleph.json and
# bootupd 0.3.2 fails (coreos/bootupd#1166). We hand the full label set to the
# rechunker itself (rpm-ostree build-chunked-oci --label), so labels are set at
# creation and no extra layer or rebuild step is involved:
#   base labels (pinned FROM) < our build labels (pre-rechunk) < our version;
#   containers.bootc / ostree.commit / ostree.final-diffid come from the rechunker.
#   prepare IMG  -> /tmp/rechunk-labels (NUL-separated KEY=VALUE), /tmp/want-labels.json
#   verify  IMG  -> fail if a label is missing/different, a base label is absent,
#                   the version is empty/null, or final-diffid != last layer
set -euo pipefail
MODE=$1; IMG=$2
if [ "$MODE" = prepare ]; then
  REV=${VETTV_REV:?VETTV_REV unset}
  BASE=$(awk '$1=="FROM" && $2!="scratch" {print $2; exit}' Containerfile)
  echo "base: $BASE"
  skopeo inspect --no-tags "docker://$BASE" > /tmp/base-inspect.json
  podman image inspect "$IMG" --format '{{json .Labels}}' > /tmp/pre-labels.json
  python3 - "$REV" <<'PY'
import json, sys
base = json.load(open("/tmp/base-inspect.json")).get("Labels") or {}
pre = json.load(open("/tmp/pre-labels.json")) or {}
bv = (base.get("org.opencontainers.image.version") or "").strip()
if not bv or bv == "null":
    sys.exit("base has no org.opencontainers.image.version")
skip = ("containers.bootc", "ostree.commit", "ostree.final-diffid")  # rechunker sets these
want = {k: v for k, v in base.items() if k not in skip}
want.update({k: v for k, v in pre.items() if k not in skip})
want["org.opencontainers.image.version"] = f"{bv}-vettv.{sys.argv[1]}"
json.dump(want, open("/tmp/want-labels.json", "w"), indent=1, sort_keys=True)
with open("/tmp/rechunk-labels", "w") as o:
    for k, v in sorted(want.items()):
        if "\0" in k + v: sys.exit(f"NUL in label {k}")
        o.write(f"{k}={v}\0")
print(f"{len(want)} labels for the rechunker; version = {want['org.opencontainers.image.version']}")
PY
elif [ "$MODE" = verify ]; then
  podman image inspect "$IMG" --format '{{json .Labels}}' > /tmp/final-labels.json
  podman image inspect "$IMG" --format '{{json .RootFS.Layers}}' > /tmp/final-layers.json
  python3 - <<'PY'
import json, sys
want = json.load(open("/tmp/want-labels.json")); got = json.load(open("/tmp/final-labels.json")) or {}
base = json.load(open("/tmp/base-inspect.json")).get("Labels") or {}
layers = json.load(open("/tmp/final-layers.json"))
err = []
for k, v in want.items():
    if got.get(k) != v: err.append(f"label {k}: want {v!r} got {got.get(k)!r}")
for k in base:
    if k not in got: err.append(f"base label missing: {k}")
for k in ("containers.bootc", "ostree.commit", "ostree.final-diffid"):
    if k not in got: err.append(f"rechunker label missing: {k}")
v = (got.get("org.opencontainers.image.version") or "").strip()
if not v or v == "null": err.append("version empty/null")
if layers and got.get("ostree.final-diffid") != layers[-1]: err.append("ostree.final-diffid is not the last layer")
for k, val in sorted(got.items()): print(f"  {k} = {val[:120]}")
print(f"layers: {len(layers)}; last = {layers[-1] if layers else None}")
if err: print("\n".join(err)); sys.exit(1)
print("labels OK; version =", v)
PY
else
  echo "usage: $0 prepare|verify IMG"; exit 2
fi
