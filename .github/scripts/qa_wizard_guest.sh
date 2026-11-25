#!/bin/bash
# QA wizard gate guest unit (test VM only; delivered as a QEMU SMBIOS
# credential, nothing on the image). Runs as root on every boot. Each write
# opens /dev/ttyS0 anew (serial-getty's vhangup kills held fds, run
# 45518216557) and every section is also kept in /var/lib/vettv-qa/ so the
# host can read it from the disk afterwards. Prints no secrets.
trap '' HUP
export SYSTEMD_COLORS=0 SYSTEMD_PAGER= LC_ALL=C
B=$(journalctl --list-boots -q 2>/dev/null | wc -l)
D=/var/lib/vettv-qa/boot$B; mkdir -p "$D"
tty() { ( flock 9; cat > /dev/ttyS0 2>/dev/null ) 9>/run/qawiz.lock || true; }   # settle & monitor write concurrently
mark() { printf '@@%s@@\n' "$*" | tty; echo "$(date +%T) $*" >> "$D/markers.txt"; }
sec() { local n=$1; shift; local o rc; o=$( "$@" 2>&1 ); rc=$?
  printf '%s\n' "$o" > "$D/$n.txt"; printf '@@BEGIN %s@@\n%s\n@@END %s rc=%s@@\n' "$n" "$o" "$n" "$rc" | tty; }
regular() { getent passwd | awk -F: '$3>=1000 && $3<=60000 {print $1}'; }

mark "QA boot=$B up=$(cut -d' ' -f1 /proc/uptime)"
sec b${B}-00-ids bash -c 'cat /proc/cmdline; cat /proc/sys/kernel/random/boot_id; systemctl --version | head -1'
sec b${B}-01-aleph cat /sysroot/.bootc-aleph.json
sec b${B}-02-wizard-unit bash -c 'systemctl cat plasma-setup.service; echo; systemctl show plasma-setup.service -p ActiveState,SubState,Result,ExecMainStatus,ConditionResult,ConditionTimestamp,ExecMainStartTimestamp; echo; /usr/libexec/vettv/no-regular-user; echo "no-regular-user rc=$?"; ls -l /etc/plasma-setup-done 2>&1; rpm -q plasma-setup'
sec b${B}-03-users bash -c 'getent passwd | awk -F: "\$3>=1000 && \$3<=60000"; echo "-- plasma-setup sysuser"; getent passwd plasma-setup; echo "-- wheel"; getent group wheel'
sec b${B}-04-dm-config bash -c 'for f in /etc/plasmalogin.conf.d/* /etc/sddm.conf.d/*; do [ -f "$f" ] && { echo "### $f"; cat "$f"; }; done; echo "-- /etc/xdg/autostart"; ls /etc/xdg/autostart; echo "-- dm"; systemctl status display-manager.service --no-pager -n 0 2>&1 | head -5'

monitor() {
  local w=0 g=0 s="" u=""
  for _ in $(seq 1 400); do
    if [ $w = 0 ] && { pgrep -u plasma-setup -x plasma-setup || pgrep -u plasma-setup -f 'libexec/plasma-setup( |$)'; } >/dev/null 2>&1; then
      w=1; mark "WIZARD-UP boot=$B"; sec b${B}-10-wizard-procs bash -c 'ps -o pid,user,etime,args -u plasma-setup; journalctl -b -u plasma-setup.service --no-pager -o short-monotonic'
    fi
    if [ $g = 0 ] && pgrep -f 'plasma-?login-greeter|plasmalogin-greeter' >/dev/null 2>&1; then g=1; mark "GREETER-UP boot=$B"; fi
    if [ -z "$u" ]; then u=$(regular | head -1)
      if [ -n "$u" ]; then mark "USER-PRESENT $u boot=$B"
        sec b${B}-11-user bash -c "id $u; echo '-- getent group wheel'; getent group wheel; echo '-- passwd -S'; passwd -S $u; echo '-- home'; ls -ld /home/$u /var/home/$u 2>&1; ls -l /etc/plasma-setup-done 2>&1"
      fi
    fi
    ns=$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $3}' | sort -u | tr '\n' ' ')
    if [ "$ns" != "$s" ]; then s=$ns; mark "SESSIONS [$s] boot=$B"; fi
    sleep 3
  done
}
settle() {
  timeout 240 systemctl is-system-running --wait >/dev/null 2>&1; sleep 20
  sec b${B}-20-bootloader-update bash -c 'systemctl status bootloader-update.service --no-pager -n 0; journalctl -b -u bootloader-update.service --no-pager -o short-monotonic'
  sec b${B}-21-bootupctl-status bootupctl status
  sec b${B}-22-failed systemctl --failed --no-pager
  sec b${B}-23-rpm-ostree bash -c 'rpm-ostree status -v --booted; echo; bootc status --booted 2>&1 | head -40'
  sec b${B}-25-wizard-unit-settled bash -c 'systemctl show plasma-setup.service -p ActiveState,SubState,Result,ExecMainStatus,ConditionResult,ExecMainStartTimestamp; /usr/libexec/vettv/no-regular-user; echo "no-regular-user rc=$?"; ls -l /etc/plasma-setup-done 2>&1; journalctl -b -u plasma-setup.service --no-pager -o short-monotonic | tail -20'
  sec b${B}-24-wizard-journal bash -c 'journalctl -b --no-pager -o short-monotonic | grep -Ei "plasma-setup|plasmasetup|no-regular-user|createuser|plasmalogin" | head -150'
  mark "SETTLED boot=$B"
}
settle &
monitor
