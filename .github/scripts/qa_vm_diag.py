#!/usr/bin/env python3
"""QA diag boot (Faye 11-24): boot a fresh qcow2 overlay with no network and a
test-only login that exists ONLY as QEMU SMBIOS systemd credentials (nothing is
written to the disk host-side). Serial goes through a chardev socket (driven
here) and is also logged in full by QEMU. Wait for the second boot's login
prompt, log in on ttyS0, sudo -S to root, run qa_diag_guest.sh and split its
markers into files. Fallback (only if login fails): reboot the same overlay
with the script delivered as a systemd.extra-unit credential that dumps the
same sections to ttyS0. The password is read from --pwfile, never printed,
and redacted from every output file."""
import argparse, base64, json, lzma, os, re, shutil, socket, subprocess, sys, threading, time

ap = argparse.ArgumentParser()
ap.add_argument("--disk", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--pwfile", default=None); ap.add_argument("--script", required=True)
ap.add_argument("--unit-only", action="store_true", help="no login: diag unit via systemd.extra-unit credential on every boot from first power-on")
ap.add_argument("--done-wait", type=int, default=1200)
ap.add_argument("--boot-wait", type=int, default=600)
a = ap.parse_args()
PW = open(a.pwfile).read().strip() if a.pwfile else None
assert a.unit_only or (PW and re.fullmatch(r"[0-9a-f]{32}", PW))
TMP = os.environ.get("RUNNER_TEMP", "/tmp")
SHOTS = os.path.join(a.out, "shots"); os.makedirs(SHOTS, exist_ok=True)
DIAG = os.path.join(a.out, "diag"); os.makedirs(DIAG, exist_ok=True)
SCRIPT = open(a.script, "rb").read()
code = next(p for p in ["/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd"] if os.path.exists(p))
VARS = os.path.join(TMP, "diag-vars.fd"); shutil.copy(code.replace("CODE", "VARS"), VARS)
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def cred_files(tag, fallback):
    b64 = lambda s: base64.b64encode(s.encode() if isinstance(s, str) else s).decode()
    creds = [] if a.unit_only else [
        ("binary", "sysusers.extra", b64('u qadiag - "QA diag" /var/qadiag /bin/bash\nm qadiag wheel\n')),
        ("text", "passwd.plaintext-password.qadiag", PW),
        ("text", "passwd.plaintext-password.root", PW),  # fallback; sysusers likely ignores (root exists)
    ]
    if fallback:
        unit = ("[Unit]\nDescription=QA diag dump to ttyS0 (credential-only, test VM)\n"
                "ConditionPathExists=!/etc/initrd-release\nAfter=bootloader-update.service\n"
                "[Service]\nType=simple\nImportCredential=qadiag.script\n"
                "ExecStart=/bin/bash -c 'bash $CREDENTIALS_DIRECTORY/qadiag.script > /dev/ttyS0 2>&1'\n")
        creds += [("text", "getty.ttys.serial", "ttyS0"),
                  ("binary", "qadiag.script", b64(SCRIPT)),
                  ("binary", "systemd.extra-unit.qadiag-dump.service", b64(unit)),
                  ("binary", "systemd.unit-dropin.multi-user.target~qadiag", b64("[Unit]\nWants=qadiag-dump.service\n"))]
    args = []
    for i, (kind, name, val) in enumerate(creds):
        p = os.path.join(TMP, f"cred-{tag}-{i}")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        pre = "io.systemd.credential.binary:" if kind == "binary" else "io.systemd.credential:"
        os.write(fd, f"{pre}{name}={val}".encode()); os.close(fd)
        args += ["-smbios", f"type=11,path={p}"]
    log(f"{tag}: credentials: " + ", ".join(n for _, n, _ in creds))
    return args

class VM:
    def __init__(self, tag, fallback=False):
        self.tag = tag; self.buf = bytearray(); self.lock = threading.Lock()
        self.serial_log = os.path.join(a.out, f"{tag}-serial.log")
        qmp = os.path.join(TMP, f"{tag}.qmp"); sock = os.path.join(TMP, f"{tag}.ser")
        cmd = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host",
               "-smp", "4", "-m", "6144", "-nic", "none",
               "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
               "-drive", f"if=pflash,format=raw,file={VARS}",
               "-drive", f"file={a.disk},format=qcow2,if=virtio",
               "-vga", "virtio", "-display", "none",
               "-chardev", f"socket,id=ser0,path={sock},server=on,wait=on,logfile={self.serial_log},logappend=on",
               "-serial", "chardev:ser0", "-qmp", f"unix:{qmp},server=on,wait=off"]
        cmd += cred_files(tag, fallback)
        log(f"{tag}: " + " ".join(c for c in cmd))  # creds are file paths, no secrets on the command line
        self.p = subprocess.Popen(cmd)
        for _ in range(100):
            if os.path.exists(sock): break
            time.sleep(0.1)
        self.s = socket.socket(socket.AF_UNIX); self.s.connect(sock)   # guest starts once we connect
        for _ in range(100):
            if os.path.exists(qmp): break
            time.sleep(0.1)
        self.q = socket.socket(socket.AF_UNIX); self.q.connect(qmp); self.qf = self.q.makefile("rw")
        self.qf.readline(); self.qmp("qmp_capabilities")
        self.t0 = time.time(); self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._shots, daemon=True).start()
    def qmp(self, c, **kw):
        self.qf.write(json.dumps({"execute": c, "arguments": kw} if kw else {"execute": c}) + "\n"); self.qf.flush()
        while True:
            r = json.loads(self.qf.readline())
            if "return" in r or "error" in r: return r
    def _reader(self):
        while True:
            try: d = self.s.recv(65536)
            except OSError: break
            if not d: break
            with self.lock: self.buf += d
        self.alive = False
    def _shots(self):
        n = 0
        while self.alive and self.p.poll() is None:
            time.sleep(30); n += 1
            try: self.qmp("screendump", filename=os.path.join(SHOTS, f"{self.tag}-{n:02d}-{int(time.time()-self.t0)}s.ppm"))
            except Exception: break
    def text(self, start=0):
        with self.lock: b = bytes(self.buf[start:])
        return b.decode("utf-8", "replace")
    def size(self):
        with self.lock: return len(self.buf)
    def send(self, s): self.s.sendall(s.encode())
    def wait(self, rx, timeout, start=0):
        r = re.compile(rx); end = time.time() + timeout
        while time.time() < end:
            m = r.search(self.text(start))
            if m: return m
            if self.p.poll() is not None: return None
            time.sleep(0.5)
        return None
    def stop(self):
        if self.p.poll() is None:
            try: self.qmp("system_powerdown")
            except Exception: pass
            try: self.p.wait(timeout=180)
            except subprocess.TimeoutExpired:
                log(f"{self.tag}: no power-off in 180 s; quit"); 
                try: self.qmp("quit")
                except Exception: pass
                self.p.wait(timeout=30)
        log(f"{self.tag}: qemu exit {self.p.returncode} at {int(time.time()-self.t0)} s")

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1bP[^\x1b]*\x1b\\|\x1b[=>78M]")
def split_sections(txt, prefix):
    txt = ANSI.sub("", txt).replace("\r", "")
    names = []
    for m in re.finditer(r"@@BEGIN (\S+)@@\n(.*?)\n@@END \1 rc=(\d+)@@", txt, re.S):
        fn = os.path.join(DIAG, f"{prefix}{m.group(1)}.txt")
        open(fn, "w").write(f"##### {m.group(1)}  (exit {m.group(3)})\n{m.group(2)}\n")
        names.append(m.group(1))
    for m in re.finditer(r"@@B64BEGIN (\S+)@@\n(.*?)@@B64END \1@@", txt, re.S):
        fn = os.path.join(DIAG, f"{prefix}{m.group(1)}.log")
        try: open(fn, "wb").write(lzma.decompress(base64.b64decode(re.sub(r"\s", "", m.group(2)))))
        except Exception as e: open(fn + ".decode-error", "w").write(f"{e}\n")
        names.append(m.group(1))
    with open(os.path.join(DIAG, f"{prefix}ALL.txt"), "w") as o:
        for fn in sorted(os.listdir(DIAG)):
            if fn.startswith(prefix) and fn.endswith(".txt") and not fn.endswith("ALL.txt"):
                o.write(open(os.path.join(DIAG, fn)).read() + "\n")
    return names

def try_login(vm):
    # Wait for the 2nd kernel boot (boot 1 auto-reboots) and its login prompt.
    m = vm.wait(r"(?s)Command line: BOOT_IMAGE.*Command line: BOOT_IMAGE.*login: ", a.boot_wait)
    if not m:
        log("no 2nd-boot login prompt; checking for any login prompt")
        if not vm.wait(r"login: ", 60): return "no login prompt"
    log(f"login prompt at {int(time.time()-vm.t0)} s; settling 45 s")
    time.sleep(45)
    for attempt in (1, 2):
        st = vm.size(); vm.send("\r"); vm.wait(r"login: ", 20, st)
        st = vm.size(); vm.send("qadiag\r")
        if not vm.wait(r"[Pp]assword: ?", 30, st): return "no Password: prompt"
        st = vm.size(); vm.send(PW + "\r")
        m = vm.wait(r"Login incorrect|\$ ?$|qadiag@|Last login|No directory", 40, st)
        out = vm.text(st)
        log(f"login attempt {attempt}: " + ("incorrect" if "incorrect" in out else ("ok?" if m else "timeout")))
        if m and "incorrect" not in out: break
        time.sleep(5)
    else:
        return "login incorrect"
    time.sleep(3)
    st = vm.size(); vm.send("stty -echo; printf '@@US''ER %s@@\\n' \"$(id -un)\"\r")
    if not vm.wait(r"@@USER qadiag@@", 20, st): return "no user shell"
    st = vm.size(); vm.send("sudo -S -p '' bash --norc --noprofile\r"); time.sleep(2); vm.send(PW + "\r"); time.sleep(3)
    vm.send("stty -echo; printf '@@RO''OT %s@@\\n' \"$(id -u)\"\r")
    if not vm.wait(r"@@ROOT 0@@", 30, st):
        return "sudo failed: " + ANSI.sub("", vm.text(st)).replace(PW, "[REDACTED]")[-300:]
    return None

def run_script(vm):
    b = base64.b64encode(SCRIPT).decode()
    vm.send("rm -f /tmp/qd.b64\r")
    for i in range(0, len(b), 900):
        vm.send(f"printf %s '{b[i:i+900]}' >> /tmp/qd.b64\r"); time.sleep(0.15)
    st = vm.size()
    vm.send("base64 -d /tmp/qd.b64 > /tmp/qd.sh && sha256sum /tmp/qd.sh && bash /tmp/qd.sh\r")
    m = vm.wait(r"@@ALLDONE@@", 1500, st)
    return st, bool(m)

def main_unit():
    result = {"mode": "unit-only"}
    vm = VM("D1", fallback=True)
    b1 = vm.wait(r"@@BOOT1DONE@@", 300)
    result["boot1_captured"] = bool(b1)
    log(f"boot-1 capture: {bool(b1)} at {int(time.time()-vm.t0)} s")
    m = vm.wait(r"@@ALLDONE@@", a.done_wait)
    result["complete"] = bool(m)
    names = split_sections(vm.text(), "")
    log(f"captured {len(names)} sections, complete={bool(m)}")
    vm.stop()
    return result

def main():
    if a.unit_only:
        result = main_unit()
        json.dump(result, open(os.path.join(a.out, "diag-result.json"), "w"), indent=1)
        for fn in os.listdir(TMP):
            if fn.startswith("cred-"): os.remove(os.path.join(TMP, fn))
        pngs()
        log(json.dumps(result)); return
    result = {}
    vm = VM("D1")
    err = try_login(vm)
    if err is None:
        log("root shell on ttyS0; running diagnostics")
        st, done = run_script(vm)
        result["mode"] = "login"; result["complete"] = done
        names = split_sections(vm.text(st), "")
        log(f"captured {len(names)} sections, complete={done}")
        vm.send("systemctl poweroff\r"); time.sleep(5)
        vm.stop()
    else:
        log(f"LOGIN FAILED: {err}")
        result["login_error"] = err
        vm.stop()
        log("fallback: reboot same overlay with systemd.extra-unit credential")
        vm2 = VM("D2", fallback=True)
        m = vm2.wait(r"@@ALLDONE@@", 1500)
        result["mode"] = "extra-unit"; result["complete"] = bool(m)
        names = split_sections(vm2.text(), "")
        log(f"captured {len(names)} sections, complete={bool(m)}")
        vm2.stop()
    for fn in os.listdir(TMP):
        if fn.startswith("cred-"): os.remove(os.path.join(TMP, fn))
    json.dump(result, open(os.path.join(a.out, "diag-result.json"), "w"), indent=1)
    pngs()
    log(json.dumps(result))

def pngs():
    if shutil.which("pnmtopng"):
        for fn in sorted(os.listdir(SHOTS)):
            if fn.endswith(".ppm"):
                src = os.path.join(SHOTS, fn)
                with open(src[:-4] + ".png", "wb") as o:
                    if subprocess.run(["pnmtopng", src], stdout=o, stderr=subprocess.DEVNULL).returncode == 0: os.remove(src)
main()
