#!/usr/bin/env bash
# Label-only fix after ostree-rechunk (Faye 11-24): build-chunked-oci drops every
# image label, so bootc writes "version": null into /sysroot/.bootc-aleph.json and
# bootupd 0.3.2 fails (coreos/bootupd#1166). Restore the full label set:
#   base labels (pinned FROM) < our build labels (pre-rechunk) < rechunk labels
#   (containers.bootc, ostree.commit, ostree.final-diffid: must describe the
#   chunked image, so they win) < our org.opencontainers.image.version
# via a FROM-only podman build with --label (config change only). Fails if the
# layers change, any base label is missing, or the version is empty/null.
set -euo pipefail
IMG=$1          # localhost/vettv-retro-os:latest
PRE=$2          # JSON labels of the pre-rechunk image
REV=${VETTV_REV:?VETTV_REV unset}
BASE=$(awk '$1=="FROM" && $2!="scratch" {print $2; exit}' Containerfile)
echo "base: $BASE"
skopeo inspect --no-tags "docker://$BASE" > /tmp/base-inspect.json
podman image inspect "$IMG" --format '{{json .Labels}}' > /tmp/post-labels.json
podman image inspect "$IMG" --format '{{json .RootFS.Layers}}' > /tmp/layers-before.json
python3 - "$PRE" "$REV" <<'PY' > /tmp/label-args
import json, sys
base = json.load(open("/tmp/base-inspect.json")).get("Labels") or {}
pre = json.load(open(sys.argv[1])) or {}
post = json.load(open("/tmp/post-labels.json")) or {}
rev = sys.argv[2]
bv = base.get("org.opencontainers.image.version") or ""
if not bv.strip() or bv.strip() == "null":
    sys.exit("base has no org.opencontainers.image.version")
want = dict(base)
want.update({k: v for k, v in pre.items() if k not in ("ostree.commit", "ostree.final-diffid")})
want.update(post)
want["org.opencontainers.image.version"] = f"{bv}-vettv.{rev}"
json.dump(want, open("/tmp/want-labels.json", "w"), indent=1, sort_keys=True)
for k, v in sorted(want.items()):
    if post.get(k) != v:
        sys.stdout.write(f"{k}={v}\0")
PY
mapfile -d '' KV < /tmp/label-args
ARGS=(); for kv in "${KV[@]}"; do ARGS+=(--label "$kv"); done
echo "setting ${#KV[@]} labels"
mkdir -p /tmp/label-ctx && printf 'FROM %s\n' "$IMG" > /tmp/label-ctx/Containerfile
podman build --pull=never --layers=false "${ARGS[@]}" -t "$IMG" -f /tmp/label-ctx/Containerfile /tmp/label-ctx
podman image inspect "$IMG" --format '{{json .RootFS.Layers}}' > /tmp/layers-after.json
podman image inspect "$IMG" --format '{{json .Labels}}' > /tmp/final-labels.json
python3 - <<'PY'
import json, sys
b = json.load(open("/tmp/layers-before.json")); a = json.load(open("/tmp/layers-after.json"))
want = json.load(open("/tmp/want-labels.json")); got = json.load(open("/tmp/final-labels.json"))
base = json.load(open("/tmp/base-inspect.json")).get("Labels") or {}
err = []
if a != b: err.append(f"layers changed: {len(b)} -> {len(a)}")
for k, v in want.items():
    if got.get(k) != v: err.append(f"label {k}: want {v!r} got {got.get(k)!r}")
for k in base:
    if k not in got: err.append(f"base label missing: {k}")
v = got.get("org.opencontainers.image.version")
if not v or v.strip() in ("", "null"): err.append("version empty/null")
for k, val in sorted(got.items()): print(f"  {k} = {val[:120]}")
print(f"layers: {len(a)} (unchanged: {a == b})")
if err: print("\n".join(err)); sys.exit(1)
print("labels restored OK; version =", v)
PY
