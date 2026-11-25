#!/usr/bin/env python3
"""PASS/FAIL for the online DOSBox-X job (pending Wolf gate expected: install skipped)."""
import glob, json, os, re, sys
O = sys.argv[1]; APP = "a63863de89d3839f64ca039d5425f319d6fd925e8b9e55d09c20f76a4e3495ff"; RT = "df26daaf9d07610b4a72cc4585566194051275ac68396597b06474396f66427c"
r = json.load(open(os.path.join(O, "N1-result.json"))) if os.path.exists(os.path.join(O, "N1-result.json")) else {}
b = r.get("boot")
def d(s):
    fs = sorted(glob.glob(os.path.join(O, "diag", f"N1-o{b}-{s}.txt"))) if b else []
    return open(fs[-1]).read() if fs else ""
L = []; bad = 0
def chk(n, ok, ev):
    global bad; bad += 0 if ok else 1; L.append(f"{'PASS' if ok else 'FAIL'}  {n}: {ev}")
net = d("01-net"); chk("network up in online job", "flathub HTTP 200" in net or "flathub HTTP 3" in net, (re.search(r"flathub HTTP \S+", net) or ["no http line"])[0])
sv = d("02-service"); jn = d("03-journal")
chk("service exit 0", "Result=success" in sv and "ExecMainStatus=0" in sv, " ".join(re.findall(r"(?:Result|ExecMainStatus|ExecMainCode)=\S+", sv)))
chk("service logs 'skipping install'", "skipping install" in jn, (re.search(r".*skipping install.*", jn) or ["not found"])[0].strip())
ap = d("04-flatpak-apps"); inf = d("05-flatpak-info"); al = d("06-flatpak-all")
chk("DOSBox-X not installed", bool(ap) and bool(inf) and "com.dosbox_x.DOSBox-X" not in ap and "(exit 0)" not in inf.splitlines()[0], (inf.splitlines()[1:2] or ["no flatpak info section"])[0])
chk("4964216d absent", "4964216d hits: 0" in al and "4964216d" not in ap, (re.search(r"4964216d hits: \d+", al) or ["?"])[0])
env = d("07-pins-env")
chk("on-image env pins a63863de + df26daaf, gate pending", f"DOSBOX_X_COMMIT={APP}" in env and f"DOSBOX_X_RUNTIME_COMMIT={RT}" in env and "DOSBOX_X_GATE=pending" in env and "4964216d" not in env,
    " | ".join(l for l in env.splitlines() if l.startswith(("DOSBOX_X_COMMIT", "DOSBOX_X_RUNTIME", "DOSBOX_X_GATE"))))
out = "\n".join(L) + f"\n{'ALL PASS' if not bad else str(bad) + ' FAIL'}\n"
open(os.path.join(O, "CHECKS-online.txt"), "w").write(out); print(out); sys.exit(1 if bad else 0)
