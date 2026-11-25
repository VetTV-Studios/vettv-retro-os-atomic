#!/usr/bin/env python3
"""PASS/FAIL for the online DOSBox-X job. Branches on the on-image DOSBOX_X_GATE
(pending: install skipped; passed: pinned app+runtime installed and masked)."""
import glob, json, os, re, sys
O = sys.argv[1]
APP = "a63863de89d3839f64ca039d5425f319d6fd925e8b9e55d09c20f76a4e3495ff"
RT = "df26daaf9d07610b4a72cc4585566194051275ac68396597b06474396f66427c"
# Key lines from vettv.3 (358fa4a). Comment-only drift is OK; any other key change is FAIL.
V3_KEYS = {
    "DOSBOX_X_APP": "com.dosbox_x.DOSBox-X",
    "DOSBOX_X_VER": "2026.08.31",
    "DOSBOX_X_COMMIT": APP,
    "DOSBOX_X_RUNTIME": "org.freedesktop.Platform/x86_64/26.08",
    "DOSBOX_X_RUNTIME_COMMIT": RT,
    "PROTONPLUS_APP": "com.vysp3r.ProtonPlus",
    "PROTONPLUS_VER": "0.6.8",
    "PROTONPLUS_COMMIT": "eee0c85dcc5987f2a9ab2f027eb614ad30f38c56ccc6a81a55ac0040320afcda",
    "HEROIC_APP": "com.heroicgameslauncher.hgl",
    "HEROIC_VER": "v2.22.4",
    "HEROIC_COMMIT": "8f930918e5b8a0901969e036a2b274d2b2bcd5f820c80b2f79819aba51043267",
    "DOSBOX_X_GATE": "pending",
}
V3_COMMENTS = [
    "# DOSBOX_X_* lines GENERATED from ../dosbox-x/16bit-pins.toml by shared/sync-pins.py; do not hand-edit.",
    "# Flathub app pins (x86_64/stable). Read live from dl.flathub.org/repo/refs/heads on 2026-11-02 12:10 CT.",
    "# Each commit is the current stable ref at the listed Flathub version. Re-check with `flatpak remote-info --log` in the first F44 VM.",
    "# Wolf3D gate (Faye 11-17): DOSBox-X pin is NOT taken until Linux QA's Wolf Floor 1 60 s check holds on this exact commit.",
    '# Set to "passed" only when QA logs the pass for DOSBOX_X_COMMIT.',
]
r = json.load(open(os.path.join(O, "N1-result.json"))) if os.path.exists(os.path.join(O, "N1-result.json")) else {}
b = r.get("boot")
def d(s, boot=None):
    bb = b if boot is None else boot
    fs = sorted(glob.glob(os.path.join(O, "diag", f"N1-o{bb}-{s}.txt"))) if bb else []
    return open(fs[-1]).read() if fs else ""
def all_d(s):
    return [open(p).read() for p in sorted(glob.glob(os.path.join(O, "diag", f"N1-o*-{s}.txt")))]
def first_hash(t):
    for line in t.splitlines():
        if line.startswith("#####") or not line.strip():
            continue
        return line.strip()
    return ""
def parse_env(t):
    keys, comments = {}, []
    for line in t.splitlines():
        if line.startswith("#####"):
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            comments.append(s)
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            keys[k.strip()] = v.strip()
    return keys, comments
L = []; bad = 0
def chk(n, ok, ev):
    global bad; bad += 0 if ok else 1; L.append(f"{'PASS' if ok else 'FAIL'}  {n}: {ev}")
net = d("01-net"); chk("network up in online job", "flathub HTTP 200" in net or "flathub HTTP 3" in net, (re.search(r"flathub HTTP \S+", net) or ["no http line"])[0])
env = d("07-pins-env")
gm = re.search(r"^DOSBOX_X_GATE=(\S+)", env, re.M)
gate = gm.group(1) if gm else ""
sv = d("02-service"); jn = d("03-journal")
ap = d("04-flatpak-apps"); inf = d("05-flatpak-info"); al = d("06-flatpak-all")
if gate == "pending":
    chk("service exit 0", "Result=success" in sv and "ExecMainStatus=0" in sv, " ".join(re.findall(r"(?:Result|ExecMainStatus|ExecMainCode)=\S+", sv)))
    chk("service logs 'skipping install'", "skipping install" in jn, (re.search(r".*skipping install.*", jn) or ["not found"])[0].strip())
    chk("DOSBox-X not installed", bool(ap) and bool(inf) and "com.dosbox_x.DOSBox-X" not in ap and "(exit 0)" not in inf.splitlines()[0], (inf.splitlines()[1:2] or ["no flatpak info section"])[0])
    chk("4964216d absent", "4964216d hits: 0" in al and "4964216d" not in ap, (re.search(r"4964216d hits: \d+", al) or ["?"])[0])
    chk("on-image env pins a63863de + df26daaf, gate pending", f"DOSBOX_X_COMMIT={APP}" in env and f"DOSBOX_X_RUNTIME_COMMIT={RT}" in env and "DOSBOX_X_GATE=pending" in env and "4964216d" not in env,
        " | ".join(l for l in env.splitlines() if l.startswith(("DOSBOX_X_COMMIT", "DOSBOX_X_RUNTIME", "DOSBOX_X_GATE"))))
elif gate == "passed":
    this_ok = "Result=success" in sv and "ExecMainStatus=0" in sv
    prior_ok = any("Result=success" in x and "ExecMainStatus=0" in x for x in all_d("02-service"))
    done = "dosbox-x-flatpak.done" in al
    ev_sv = " ".join(re.findall(r"(?:Result|ExecMainStatus|ExecMainCode|ConditionResult)=\S+", sv)) or "no service dump"
    if not this_ok and prior_ok and done:
        ev_sv += "; done-file present, earlier boot ran the unit"
    chk("service Result=success and exit 0", this_ok or (prior_ok and done), ev_sv)
    chk("DOSBox-X installed", "com.dosbox_x.DOSBox-X" in ap and bool(inf) and "(exit 0)" in inf.splitlines()[0],
        (inf.splitlines()[1] if inf and len(inf.splitlines()) > 1 else (ap[:200] or "not installed")))
    ac = first_hash(d("09-flatpak-app-commit"))
    chk("app commit a63863de", ac == APP, ac or "no --show-commit output")
    rc = first_hash(d("10-flatpak-runtime-commit"))
    chk("runtime commit df26daaf (org.freedesktop.Platform//26.08)", rc == RT, rc or "no --show-commit output")
    msk = d("11-flatpak-mask")
    chk("app masked", "com.dosbox_x.DOSBox-X" in msk, msk.strip() or "no mask output")
    chk("runtime masked", "org.freedesktop.Platform" in msk and "26.08" in msk, msk.strip() or "no mask output")
    chk("4964216d hits: 0", "4964216d hits: 0" in al, (re.search(r"4964216d hits: \d+", al) or ["?"])[0])
    chk("on-image env pins a63863de + df26daaf, gate passed", f"DOSBOX_X_COMMIT={APP}" in env and f"DOSBOX_X_RUNTIME_COMMIT={RT}" in env and "DOSBOX_X_GATE=passed" in env and "4964216d" not in env,
        " | ".join(l for l in env.splitlines() if l.startswith(("DOSBOX_X_COMMIT", "DOSBOX_X_RUNTIME", "DOSBOX_X_GATE"))))
    keys, comments = parse_env(env)
    expect = dict(V3_KEYS); expect["DOSBOX_X_GATE"] = "passed"
    diffs = []
    for k in sorted(set(keys) | set(expect)):
        if keys.get(k) != expect.get(k):
            diffs.append(f"{k}: {keys.get(k, '<missing>')} (vettv.3 {V3_KEYS.get(k, '<absent>')})")
    added = [c for c in comments if c not in V3_COMMENTS]
    removed = [c for c in V3_COMMENTS if c not in comments]
    comm = []
    if added: comm.append("comment added: " + " | ".join(added))
    if removed: comm.append("comment removed: " + " | ".join(removed))
    if not comm: comm.append("comments unchanged")
    chk("env diff vs vettv.3 (358fa4a) is only GATE pending->passed", not diffs, ("; ".join(diffs) if diffs else "only DOSBOX_X_GATE pending->passed") + "; " + "; ".join(comm))
else:
    chk("DOSBOX_X_GATE is pending or passed", False, gate or "missing from on-image env")
out = "\n".join(L) + f"\n{'ALL PASS' if not bad else str(bad) + ' FAIL'}\n"
open(os.path.join(O, "CHECKS-online.txt"), "w").write(out); print(out); sys.exit(1 if bad else 0)
