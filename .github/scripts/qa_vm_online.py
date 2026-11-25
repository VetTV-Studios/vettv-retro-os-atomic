#!/usr/bin/env python3
"""Online first-boot job: boot a fresh overlay WITH user-mode networking
(this job only) and the qa_online_guest.sh probe as SMBIOS credentials; wait for
@@ONLINE-DONE@@ on the boot after the first-boot auto-reboot; split sections."""
import argparse, base64, json, os, re, shutil, socket, subprocess, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("--disk", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--script", required=True); ap.add_argument("--tag", default="N1")
a = ap.parse_args()
TMP = os.environ.get("RUNNER_TEMP", "/tmp"); DIAG = os.path.join(a.out, "diag"); SHOTS = os.path.join(a.out, "shots")
for d in (DIAG, SHOTS): os.makedirs(d, exist_ok=True)
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {a.tag}: {m}", flush=True)
code = next(p for p in ["/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd"] if os.path.exists(p))
vars_ = os.path.join(TMP, f"{a.tag}-vars.fd"); shutil.copy(code.replace("CODE", "VARS"), vars_)
b64 = lambda s: base64.b64encode(s if isinstance(s, bytes) else s.encode()).decode()
unit = ("[Unit]\nDescription=QA online probe (credential-only, test VM)\nConditionPathExists=!/etc/initrd-release\n"
        "After=network-online.target\n[Service]\nType=simple\nImportCredential=qaonl.script\n"
        "ExecStart=/bin/bash -c 'exec bash \"$CREDENTIALS_DIRECTORY/qaonl.script\"'\n")
args = []
for i, (n, v) in enumerate([("qaonl.script", open(a.script, "rb").read()), ("systemd.extra-unit.qaonl.service", unit),
                            ("systemd.unit-dropin.multi-user.target~qaonl", "[Unit]\nWants=qaonl.service\n")]):
    p = os.path.join(TMP, f"ocred-{i}"); open(p, "w").write(f"io.systemd.credential.binary:{n}={b64(v)}")
    args += ["-smbios", f"type=11,path={p}"]
serial = os.path.join(a.out, f"{a.tag}-serial.log"); qmp = os.path.join(TMP, f"{a.tag}.qmp")
cmd = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-smp", "4", "-m", "6144",
       "-nic", "user,model=virtio-net-pci",
       "-drive", f"if=pflash,format=raw,readonly=on,file={code}", "-drive", f"if=pflash,format=raw,file={vars_}",
       "-drive", f"file={a.disk},format=qcow2,if=virtio", "-vga", "virtio", "-display", "none",
       "-serial", f"file:{serial}", "-qmp", f"unix:{qmp},server=on,wait=off"] + args
log(" ".join(cmd)); P = subprocess.Popen(cmd)
S = None
for _ in range(100):
    try: S = socket.socket(socket.AF_UNIX); S.connect(qmp); break
    except OSError: S = None; time.sleep(0.2)
F = S.makefile("rw"); F.readline()
def q(c, **kw):
    F.write(json.dumps({"execute": c, "arguments": kw} if kw else {"execute": c}) + "\n"); F.flush()
    while True:
        l = F.readline()
        if not l: return {}
        r = json.loads(l)
        if "return" in r or "error" in r: return r
q("qmp_capabilities"); t0 = time.time(); res = {"done": False}
def text():
    try: return open(serial, errors="replace").read()
    except FileNotFoundError: return ""
try:
    while time.time() - t0 < 1200 and P.poll() is None:
        m = list(re.finditer(r"@@ONLINE-DONE boot=(\d+)@@", text()))
        boots = re.findall(r"@@QA boot=(\d+)@@", text())
        if m and boots and m[-1].group(1) == boots[-1]:
            time.sleep(60)   # no reboot after it?
            if re.findall(r"@@QA boot=(\d+)@@", text())[-1] == m[-1].group(1):
                res = {"done": True, "boot": int(m[-1].group(1)), "t": int(time.time() - t0)}; break
        time.sleep(5)
    q("screendump", filename=os.path.join(SHOTS, f"{a.tag}-end.ppm"))
    txt = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text()).replace("\r", "")
    last = res.get("boot")
    for mm in re.finditer(r"@@BEGIN (\S+)@@\n(.*?)\n@@END \1 rc=(\d+)@@", txt, re.S):
        open(os.path.join(DIAG, f"{a.tag}-{mm.group(1)}.txt"), "w").write(f"##### {mm.group(1)} (exit {mm.group(3)})\n{mm.group(2)}\n")
finally:
    if P.poll() is None:
        q("system_powerdown")
        try: P.wait(timeout=180)
        except subprocess.TimeoutExpired: P.kill(); P.wait()
    for i in range(3):
        try: os.remove(os.path.join(TMP, f"ocred-{i}"))
        except FileNotFoundError: pass
    if shutil.which("pnmtopng"):
        for fn in os.listdir(SHOTS):
            if fn.endswith(".ppm"):
                src = os.path.join(SHOTS, fn)
                with open(src[:-4] + ".png", "wb") as o: subprocess.run(["pnmtopng", src], stdout=o)
                os.remove(src)
    json.dump(res, open(os.path.join(a.out, f"{a.tag}-result.json"), "w")); log(json.dumps(res))
sys.exit(0 if res.get("done") else 2)
