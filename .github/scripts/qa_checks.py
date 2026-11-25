#!/usr/bin/env python3
"""PASS/FAIL lines for the combined wizard gate from qa-out/. Exit 1 on any FAIL."""
import glob, json, os, re, sys
O = sys.argv[1]; EXP = sys.argv[2] if len(sys.argv) > 2 else ""
WIZ_ONLY = len(sys.argv) > 3 and sys.argv[3] == "wizard-only"
def rd(p):
    try: return open(os.path.join(O, p), errors="replace").read()
    except FileNotFoundError: return ""
def diag(tag, suffix):
    fs = sorted(glob.glob(os.path.join(O, "diag", f"{tag}-b*-{suffix}.txt")))
    return open(fs[-1], errors="replace").read() if fs else ""
def jr(tag):
    try: return json.load(open(os.path.join(O, f"{tag}-result.json")))
    except Exception: return {}
B1 = rd("BOOT1_TAG").strip() or "W1"
lines = []; bad = 0
def chk(name, ok, ev):
    global bad
    bad += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}  {name}: {ev}")
if not WIZ_ONLY:
    size = lambda t: (re.search(r"root partition: \S+ size (\d+)", t) or [None, "0"])[1]
    stamp = lambda t: (re.search(r"== stamp\n(.*)", t) or [None, ""])[1]
    i0, i1, i2 = rd("W0-inspect.txt"), rd(f"{B1}-inspect.txt"), rd("W2-inspect.txt")
    chk("root growth boot1", int(size(i1)) > 60_000_000_000 and stamp(i1).startswith("-") and "grow-root.done" in stamp(i1), f"{size(i0)} -> {size(i1)}; {stamp(i1)}")
    chk("boot2 unchanged", size(i2) == size(i1) and stamp(i2).startswith("-") and stamp(i2) == stamp(i1), f"{size(i2)}; {stamp(i2)}")
    bu = re.search(r"-- bootloader-update journal \(all boots\)\n(.*?)\n-- bootupctl", i2, re.S); bu = bu.group(1) if bu else ""
    chk("bootloader-update", bu.count("Finished bootloader-update") >= 2 and "Failed" not in bu,
        f"Finished x{bu.count('Finished bootloader-update')}, failed x{bu.count('Failed')}")
    for tag in (B1, "W2"):
        al = diag(tag, "01-aleph"); v = re.search(r'"version"\s*:\s*("[^"]*"|null)', al)
        chk(f"aleph version ({tag})", bool(v) and v.group(1) not in ('null', '""') and "-vettv.5" in v.group(1), v.group(0) if v else "no aleph section")
        st = diag(tag, "21-bootupctl-status")
        chk(f"bootupctl status ({tag})", "(exit 0)" in st and "Aleph version" in st, " | ".join(l.strip() for l in st.splitlines()[1:6]))
        fl = diag(tag, "22-failed"); units = re.findall(r"^\W*(\S+\.(?:service|path|socket|timer|mount|automount|device|scope|slice|target|swap))\s", fl, re.M)
        # Offline wizard job has no NIC, so the first-boot Flatpak install cannot
        # finish (Monday: run the override offline / stop the fail loop). Allow
        # only that unit beyond the NVIDIA CDI pair; the online job still requires it to succeed.
        other = [u for u in units if not u.startswith("nvidia-cdi-refresh") and u != "vettv-dosbox-x-flatpak.service"]
        chk(f"failed units ({tag})", bool(fl) and not other, ", ".join(units) or "0 units")
        ro = diag(tag, "23-rpm-ostree")
        chk(f"rpm-ostree digest ({tag})", bool(EXP) and EXP in ro, (re.search(r"Digest: \S+", ro) or [""])[0])
    esp = lambda t: re.findall(r"^(\w{64})  (/dev/nbd0p\d+) files\n(\d+)", t, re.M)
    e0, e1, e2 = esp(i0), esp(i1), esp(i2)
    vfat = lambda t: [x for x in re.findall(r"(/dev/nbd0p\d+) \(vfat", t)]
    chk("ESP + /boot trees", len(e0) == 2 and len(e1) == 2 and e1 == e2 and e0[0] == e1[0],
        "; ".join(f"{p}: {h[:8]}({n})" for h, p, n in e0) + " -> " + "; ".join(f"{p}: {h[:8]}({n})" for h, p, n in e1) + " -> " + "; ".join(f"{p}: {h[:8]}({n})" for h, p, n in e2))
r1, r2 = jr(B1), jr("W2")
chk("(a) wizard on boot 1 (screenshot)", bool(r1.get("wizard_up_s")) and bool(r1.get("first_screen_wizard_text")) and os.path.exists(os.path.join(O, "shots", f"{B1}-wizard-first-screen.png")),
    f"WIZARD-UP at {r1.get('wizard_up_s')} s; OCR: {r1.get('first_screen_ocr','')[:120]}; shots/{B1}-wizard-first-screen.png")
u = diag(B1, "11-user") or diag("W2", "11-user")
chk("(b) user created through the wizard", bool(r1.get("driven")) and "uid=" in u and "qatest" in u, (re.search(r"uid=.*", u) or ["no user"])[0])
chk("(b) user is admin (wheel)", bool(re.search(r"groups=.*\(wheel\)", u)) and bool(re.search(r"^wheel:.*qatest", u, re.M)),
    " | ".join(l for l in u.splitlines() if l.startswith(("uid=", "wheel:"))))
chk("(b) password set (passwd -S, value never logged)", bool(re.search(r"^qatest PS? ", u, re.M)), (re.search(r"^qatest \S+", u, re.M) or ["?"])[0])
wz = diag("W2", "25-wizard-unit-settled")
done = bool(re.search(r"^-\S+ .*/etc/plasma-setup-done$", wz, re.M)); skip = "no-regular-user rc=1" in wz
chk("(c) wizard not run on boot 2", bool(r2) and r2.get("wizard_started") is False and (done or skip) and "ActiveState=active" not in wz,
    " ".join(re.findall(r"(?:ConditionResult|ActiveState|Result)=\S+", wz)) + f" | done-flag={done} | " + " ".join(l for l in wz.splitlines() if "regular user" in l))
chk("(c) greeter offers qatest", bool(r2.get("greeter_shows_user")), f"OCR of shots/W2-greeter-woken.png: {rd('W2-ocr.txt').strip()[:160]}")
u2 = diag("W2", "11-user")
if u and "uid=" in u and not re.search(r"groups=.*\(wheel\)", u):
    lines.append("IMAGE ISSUE: plasma-setup created a standard (non-wheel) user - stop, image fix needed")
out = "\n".join(lines) + f"\n{'ALL PASS' if not bad else str(bad) + ' FAIL'}\n"
open(os.path.join(O, "CHECKS.txt"), "w").write(out); print(out)
sys.exit(1 if bad else 0)
