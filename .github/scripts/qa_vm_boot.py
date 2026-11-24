#!/usr/bin/env python3
"""Boot a disk under QEMU/KVM with no network, save serial log and periodic
screenshots (QMP screendump), then ACPI power off. Exits nonzero only if
QEMU fails to start or KVM is unavailable."""
import argparse, json, os, socket, subprocess, sys, time, shutil

ap = argparse.ArgumentParser()
ap.add_argument("--disk"); ap.add_argument("--out"); ap.add_argument("--tag")
ap.add_argument("--wait", type=int, default=420)
a = ap.parse_args()

code = next(p for p in ["/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd"] if os.path.exists(p))
vars_src = code.replace("CODE", "VARS")
vars_dst = f"/tmp/{a.tag}-vars.fd"
if not os.path.exists("/tmp/ovmf-vars.fd"):
    shutil.copy(vars_src, "/tmp/ovmf-vars.fd")   # same NVRAM across boots
qmp = f"/tmp/{a.tag}.qmp"
serial = os.path.join(a.out, f"{a.tag}-serial.log")
cmd = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host",
       "-smp", "4", "-m", "6144", "-nic", "none",
       "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
       "-drive", "if=pflash,format=raw,file=/tmp/ovmf-vars.fd",
       "-drive", f"file={a.disk},format=qcow2,if=virtio",
       "-vga", "virtio", "-display", "none",
       "-serial", f"file:{serial}", "-qmp", f"unix:{qmp},server,nowait"]
print(" ".join(cmd), flush=True)
p = subprocess.Popen(cmd)
for _ in range(50):
    if os.path.exists(qmp): break
    time.sleep(0.2)
s = socket.socket(socket.AF_UNIX); s.connect(qmp); f = s.makefile("rw")
def q(c, **args):
    f.write(json.dumps({"execute": c, "arguments": args} if args else {"execute": c}) + "\n"); f.flush()
    while True:
        r = json.loads(f.readline())
        if "return" in r or "error" in r: return r
f.readline(); q("qmp_capabilities")
t0 = time.time(); n = 0
while time.time() - t0 < a.wait and p.poll() is None:
    time.sleep(30); n += 1
    q("screendump", filename=os.path.join(a.out, "shots", f"{a.tag}-{n:02d}-{int(time.time()-t0)}s.ppm"))
q("system_powerdown")
try:
    p.wait(timeout=180)
except subprocess.TimeoutExpired:
    print("guest did not power off in 180s; quitting QEMU", flush=True)
    q("quit"); p.wait(timeout=30)
print(f"{a.tag}: qemu exit {p.returncode}, {n} screenshots", flush=True)
# convert ppm -> png if available, keep ppm otherwise
if shutil.which("pnmtopng") is None:
    subprocess.run(["sudo", "apt-get", "install", "-yq", "netpbm"], stdout=subprocess.DEVNULL)
for fn in sorted(os.listdir(os.path.join(a.out, "shots"))):
    if fn.startswith(a.tag) and fn.endswith(".ppm"):
        src = os.path.join(a.out, "shots", fn)
        with open(src[:-4] + ".png", "wb") as o:
            if subprocess.run(["pnmtopng", src], stdout=o).returncode == 0: os.remove(src)
sys.exit(0 if p.returncode in (0, None) or n > 0 else 1)
