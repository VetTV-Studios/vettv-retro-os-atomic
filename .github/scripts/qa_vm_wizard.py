#!/usr/bin/env python3
"""QA wizard gate (Faye/Naomi 11-25). Boots a qcow2 overlay of the raw under
QEMU/KVM, offline, OVMF, 1280x800, usb-tablet. A root diag unit is passed only
as SMBIOS systemd credentials (test VM only) and prints @@markers@@/sections to
ttyS0. Phases:
  boot1: wait for the plasma-setup wizard (after the first-boot auto-reboot),
         screenshot it, then drive it with QMP key/pointer events (tesseract OCR
         finds the buttons) and create test user 'qatest' with a random
         per-job password that is generated here, never printed or written.
  boot2: wizard must not start; greeter must offer 'qatest'.
Writes <tag>-serial.log, shots/<tag>-*.png, diag/<section>.txt, <tag>-result.json."""
import argparse, base64, json, os, re, secrets, shutil, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--disk", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--tag", required=True); ap.add_argument("--phase", choices=["boot1", "boot2"], required=True)
ap.add_argument("--script", required=True); ap.add_argument("--vars", required=True, help="OVMF vars file (kept across boots of one disk)")
ap.add_argument("--strategy", choices=["keys", "clicks"], default="keys")
a = ap.parse_args()
TMP = os.environ.get("RUNNER_TEMP", "/tmp")
SHOTS = os.path.join(a.out, "shots"); DIAG = os.path.join(a.out, "diag")
for d in (SHOTS, DIAG): os.makedirs(d, exist_ok=True)
USER = "qatest"
PW = secrets.token_hex(16) if a.phase == "boot1" else None   # never printed, never written
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {a.tag}: {m}", flush=True)

code = next(p for p in ["/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd"] if os.path.exists(p))
if not os.path.exists(a.vars): shutil.copy(code.replace("CODE", "VARS"), a.vars)

def creds():
    b64 = lambda s: base64.b64encode(s if isinstance(s, bytes) else s.encode()).decode()
    unit = ("[Unit]\nDescription=QA wizard gate probe (credential-only, test VM)\n"
            "ConditionPathExists=!/etc/initrd-release\nAfter=systemd-user-sessions.service\n"
            "[Service]\nType=simple\nImportCredential=qawiz.script\n"
            "ExecStart=/bin/bash -c 'exec bash \"$CREDENTIALS_DIRECTORY/qawiz.script\"'\n")
    cs = [("qawiz.script", open(a.script, "rb").read()),
          ("systemd.extra-unit.qawiz.service", unit),
          ("systemd.unit-dropin.multi-user.target~qawiz", "[Unit]\nWants=qawiz.service\n")]
    args = []
    for i, (n, v) in enumerate(cs):
        p = os.path.join(TMP, f"wcred-{a.tag}-{i}")
        with open(p, "w") as f: f.write(f"io.systemd.credential.binary:{n}={b64(v)}")
        args += ["-smbios", f"type=11,path={p}"]
    return args

serial = os.path.join(a.out, f"{a.tag}-serial.log")
qmp_path = os.path.join(TMP, f"{a.tag}.qmp")
cmd = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-smp", "4", "-m", "6144",
       "-nic", "none",
       "-drive", f"if=pflash,format=raw,readonly=on,file={code}", "-drive", f"if=pflash,format=raw,file={a.vars}",
       "-drive", f"file={a.disk},format=qcow2,if=virtio",
       "-vga", "none", "-device", "virtio-vga,xres=1280,yres=800", "-display", "none",
       "-device", "qemu-xhci", "-device", "usb-tablet",
       "-serial", f"file:{serial}", "-qmp", f"unix:{qmp_path},server=on,wait=off"] + creds()
log(" ".join(cmd))
P = subprocess.Popen(cmd)
import socket
S = None
for _ in range(100):
    try:
        S = socket.socket(socket.AF_UNIX); S.connect(qmp_path); break
    except OSError:
        S = None; time.sleep(0.2)
        if P.poll() is not None: break
if S is None: log("QEMU/QMP did not start"); P.kill(); sys.exit(4)
F = S.makefile("rw")
def q(c, **kw):
    F.write(json.dumps({"execute": c, "arguments": kw} if kw else {"execute": c}) + "\n"); F.flush()
    while True:
        line = F.readline()
        if not line: raise RuntimeError(f"QMP closed during {c}")
        r = json.loads(line)
        if "error" in r: log(f"QMP {c} error: {r['error'].get('desc')}")
        if "return" in r or "error" in r: return r
F.readline(); q("qmp_capabilities")
T0 = time.time()
def el(): return int(time.time() - T0)
def text():
    try: return open(serial, errors="replace").read()
    except FileNotFoundError: return ""
def wait(rx, timeout, after=0):
    r = re.compile(rx); end = time.time() + timeout
    while time.time() < end and P.poll() is None:
        m = r.search(text(), after)
        if m: return m
        time.sleep(1)
    return None

def shot(name):
    ppm = os.path.join(SHOTS, f"{a.tag}-{name}.ppm"); png = ppm[:-4] + ".png"
    q("screendump", filename=ppm); time.sleep(0.5)
    with open(png, "wb") as o: subprocess.run(["pnmtopng", ppm], stdout=o, stderr=subprocess.DEVNULL)
    os.remove(ppm); return png

def ocr(png):
    big = png[:-4] + ".x2.png"
    subprocess.run(f"pngtopnm '{png}' | ppmtopgm | pamscale 2 | pnmtopng > '{big}'", shell=True, stderr=subprocess.DEVNULL)
    out = subprocess.run(["tesseract", big, "-", "--psm", "11", "tsv"], capture_output=True, text=True).stdout
    os.remove(big)
    words = []
    for line in out.splitlines()[1:]:
        c = line.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) > 30:
            x, y, w, h = (int(v) / 2 for v in c[6:10])
            words.append({"t": c[11].strip(), "x": x, "y": y, "w": w, "h": h})
    return words

def leaks(flat):
    """True if any 6-char piece of the test password shows up in OCR text."""
    if not PW: return False
    t = re.sub(r"[^0-9a-f]", "", flat.lower())
    return any(PW[i:i + 6] in t for i in range(len(PW) - 5))

def size(png):
    r = subprocess.run(["pngtopnm", png], capture_output=True).stdout.split(b"\n", 2)
    w, h = map(int, r[1].split()); return w, h

W, H = 1280, 800
def click(x, y):
    ax, ay = int(x * 32767 / (W - 1)), int(y * 32767 / (H - 1))
    q("input-send-event", events=[{"type": "abs", "data": {"axis": "x", "value": ax}},
                                  {"type": "abs", "data": {"axis": "y", "value": ay}}])
    time.sleep(0.3)
    q("input-send-event", events=[{"type": "btn", "data": {"down": True, "button": "left"}}]); time.sleep(0.1)
    q("input-send-event", events=[{"type": "btn", "data": {"down": False, "button": "left"}}])

def key(*names):
    q("send-key", keys=[{"type": "qcode", "data": n} for n in names]); time.sleep(0.12)
def typ(s):   # [a-z0-9] only; the password is hex
    for ch in s:
        assert re.fullmatch(r"[a-z0-9]", ch)
        key(ch)

def find(words, *phrase, region=None):
    """center of the first run of consecutive words matching phrase (case-insensitive)."""
    n = len(phrase)
    for i in range(len(words) - n + 1):
        if all(words[i + k]["t"].strip(".,:").lower() == phrase[k].lower() for k in range(n)):
            ws = words[i:i + n]
            x0, y0 = ws[0]["x"], min(w["y"] for w in ws)
            x1 = ws[-1]["x"] + ws[-1]["w"]; y1 = max(w["y"] + w["h"] for w in ws)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if region and not region(cx, cy): continue
            return cx, cy, x1
    return None

RESULT = {"tag": a.tag, "phase": a.phase, "strategy": a.strategy}
def finish(rc):
    try: _finish(rc)
    finally:
        if P.poll() is None: P.kill()
def _finish(rc):
    left = re.compile(r"@@BEGIN (\S+)@@\n(.*?)\n@@END \1 rc=(\d+)@@", re.S)
    txt = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text()).replace("\r", "")
    for m in left.finditer(txt):
        open(os.path.join(DIAG, f"{a.tag}-{m.group(1)}.txt"), "w").write(f"##### {m.group(1)} (exit {m.group(3)})\n{m.group(2)}\n")
    RESULT["markers"] = re.findall(r"@@((?:QA|WIZARD|GREETER|USER|SESSIONS|SETTLED)[^@]*)@@", txt)
    if P.poll() is None:
        try:
            q("system_powerdown"); P.wait(timeout=180)
        except Exception as e:
            log(f"no clean power-off ({type(e).__name__}); killing QEMU"); P.kill(); P.wait(timeout=30)
    RESULT["qemu_exit"] = P.returncode
    for fn in os.listdir(TMP):
        if fn.startswith(f"wcred-{a.tag}-"): os.remove(os.path.join(TMP, fn))
    json.dump(RESULT, open(os.path.join(a.out, f"{a.tag}-result.json"), "w"), indent=1)
    log(json.dumps({k: v for k, v in RESULT.items() if k != "markers"}))
    sys.exit(rc)

def wizard_up(timeout):
    """WIZARD-UP on the boot after the auto-reboot (no newer 'QA boot=' after it for 30 s)."""
    end = time.time() + timeout; pos = 0
    while time.time() < end:
        m = wait(r"@@WIZARD-UP boot=(\d+)@@", end - time.time(), pos)
        if not m: return None
        time.sleep(90)
        boots = re.findall(r"@@QA boot=(\d+)", text())
        if re.search(r"@@QA boot=\d+", text()[m.end():]) or (boots and boots[-1] != m.group(1)):
            pos = m.end(); log("reboot after wizard start; waiting again"); continue
        return m
    return None

def drive():
    words_log = open(os.path.join(a.out, f"{a.tag}-ocr.txt"), "w")
    acct_tries = []; last = None; stall = 0
    for step in range(1, 26):
        png = shot(f"w{step:02d}"); ws = ocr(png); flat = " ".join(w["t"] for w in ws)
        if leaks(flat):   # password visible on screen (wrong focus): drop the frame, never log it
            os.remove(png); flat = "[frame dropped: password text visible]"; ws = []
            log(f"step {step}: password visible on screen; frame dropped, stopping attempt"); words_log.write(f"--- step {step}: {flat}\n"); return False
        words_log.write(f"--- step {step} ({el()} s) {os.path.basename(png)}\n{flat}\n")
        foot = lambda x, y: y > H * 0.4
        if wait(r"@@USER-PRESENT " + USER, 1):
            log(f"user present after step {step}"); return True
        if flat == last: stall += 1
        else: stall = 0
        last = flat
        if stall >= 4: log("no screen change for 4 steps"); return False
        b = find(ws, "Begin", "Setup")
        if b:
            log(f"step {step}: Begin Setup at {b[:2]}"); click(*b[:2]); time.sleep(3); continue
        is_acct = find(ws, "Username") and find(ws, "Password")
        if is_acct and len(acct_tries) < 2:
            strat = a.strategy if not acct_tries else ("clicks" if a.strategy == "keys" else "keys")
            acct_tries.append(strat)
            log(f"step {step}: account page ({strat})"); RESULT["account_tries"] = acct_tries
            if strat == "keys":
                typ(USER); key("tab"); key("tab"); typ(PW); key("tab"); key("tab"); typ(PW); key("ret")
            else:
                for lbl, val in ((("Full", "Name"), USER), (("Password",), PW), (("Confirm", "Password"), PW)):
                    hit = None
                    if lbl == ("Password",):
                        cands = [w for w in ws if w["t"].strip(":").lower() == "password"]
                        conf = find(ws, "Confirm", "Password")
                        cands = [w for w in cands if not conf or abs((w["y"] + w["h"] / 2) - conf[1]) > 5]
                        if cands: w0 = cands[0]; hit = (w0["x"] + w0["w"] / 2, w0["y"] + w0["h"] / 2, w0["x"] + w0["w"])
                    else:
                        hit = find(ws, *lbl)
                    if not hit: log(f"label {lbl} not found"); return False
                    click(hit[2] + 140, hit[1]); time.sleep(0.5); key("ctrl", "a"); key("delete"); typ(val); time.sleep(0.3)
                key("ret")
            time.sleep(3); continue
        f = find(ws, "Finish", region=foot)
        if f:
            log(f"step {step}: Finish at {f[:2]}"); click(*f[:2])
            return bool(wait(r"@@USER-PRESENT " + USER, 120))
        n = find(ws, "Next", region=foot)
        if n:
            log(f"step {step}: Next at {n[:2]}"); click(*n[:2]); time.sleep(3); continue
        log(f"step {step}: no known button; waiting"); time.sleep(5)
    return False

def main():
    global W, H
    if a.phase == "boot1":
        m = wizard_up(720)
        RESULT["wizard_up_s"] = el() if m else None
        if not m:
            shot("no-wizard"); log("wizard never came up"); RESULT["wizard"] = "not seen"; wait(r"@@SETTLED boot=", 300); finish(2)
        p0 = shot("wizard-first-screen")
        W, H = size(p0); RESULT["screen"] = [W, H]
        fs = " ".join(w["t"] for w in ocr(p0)); RESULT["first_screen_ocr"] = fs
        RESULT["first_screen_wizard_text"] = bool(re.search(r"Begin|Setup|Welcome|Plasma|language", fs, re.I))
        ok = drive()
        RESULT["driven"] = ok
        if ok:
            time.sleep(30); shot("after-finish")
            RESULT["user_session"] = bool(wait(r"@@SESSIONS \[[^\]]*" + USER, 120))
            time.sleep(20); shot("user-session")
        wait(r"@@SETTLED boot=", 400)
        finish(0 if ok else 3)
    else:
        m = wait(r"@@GREETER-UP boot=", 600)
        RESULT["greeter_up_s"] = el() if m else None
        time.sleep(30)
        p0 = shot("greeter"); W, H = size(p0)
        q("input-send-event", events=[{"type": "abs", "data": {"axis": "x", "value": 16000}}, {"type": "abs", "data": {"axis": "y", "value": 16000}}])
        key("shift"); time.sleep(4)
        p1 = shot("greeter-woken"); ws = ocr(p1)
        flat = " ".join(w["t"] for w in ws)
        open(os.path.join(a.out, f"{a.tag}-ocr.txt"), "w").write(flat + "\n")
        RESULT["greeter_shows_user"] = USER in flat.lower()
        wait(r"@@SETTLED boot=", 400)
        RESULT["wizard_started"] = bool(re.search(r"@@WIZARD-UP", text()))
        finish(0)

try:
    main()
except Exception as e:
    log(f"harness error: {type(e).__name__}: {e}"); RESULT["error"] = f"{type(e).__name__}: {e}"; finish(5)
