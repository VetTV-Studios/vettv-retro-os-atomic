#!/bin/bash
# Guest-side diagnostics for bootloader-update.service (run as root inside the
# QA VM). Every section is framed by @@BEGIN/@@END markers on stdout so the host
# can split the serial stream; large journals go out as xz+base64.
trap '' HUP   # serial-getty@ttyS0 vhangup()s the tty when it starts
export SYSTEMD_COLORS=0 SYSTEMD_PAGER=cat SYSTEMD_LESS= PAGER=cat LANG=C.UTF-8 COLUMNS=250 TERM=dumb
[ -t 1 ] && stty cols 250 rows 60 2>/dev/null
dmesg -n 1 2>/dev/null; kill -s RTMIN+21 1 2>/dev/null   # keep kernel/systemd status off ttyS0 while dumping
sec(){ n=$1; shift; printf '\n@@BEGIN %s@@\n$ %s\n' "$n" "$*"; ( eval "$*" ) 2>&1; rc=$?; printf '\n@@END %s rc=%s@@\n' "$n" "$rc"; }
secb(){ n=$1; shift; printf '\n@@B64BEGIN %s@@\n' "$n"; ( eval "$*" ) 2>&1 | xz -9 | base64 -w 76; printf '@@B64END %s@@\n' "$n"; }
BOOTS=($(journalctl --list-boots -q --no-pager 2>/dev/null | awk '{print $2}'))
FIRST=${BOOTS[0]}
printf '@@INFO boots=%s first=%s@@\n' "${#BOOTS[@]}" "$FIRST"
ALEPH='cat /sysroot/.bootc-aleph.json; echo; echo "--- version field:"; grep -o "\"version\":[^,}]*" /sysroot/.bootc-aleph.json'
if [ "${#BOOTS[@]}" -le 1 ]; then
  # first power-on boot 1: quick capture before bazzite-hardware-setup reboots (~47 s)
  sec b1-01-systemctl-status-bootloader-update 'systemctl status bootloader-update --no-pager -l'
  sec b1-02-journal-bootloader-update 'journalctl -b 0 -u bootloader-update --no-pager -o short-monotonic'
  sec b1-03-aleph "$ALEPH"
  sec b1-04-bootupctl-status 'bootupctl status'
  sec b1-05-systemctl-failed 'systemctl --failed --no-pager'
  printf '\n@@BOOT1DONE@@\n'
  exit 0
fi
timeout 240 systemctl is-system-running --wait; sleep 15
# reopen ttyS0: the fd opened at unit start was hung up when serial-getty@ttyS0 started (run 45518216557)
exec >/dev/ttyS0 2>&1
printf '@@INFO boot-2 dump starting@@\n'
sec 00-aleph "$ALEPH"
RX='ostree|rpm-ostree|bootc|reboot|finaliz|stag|rebase|signed|ublue|bazzite|first.?boot|systemctl reboot'
sec 01-systemctl-status-bootloader-update 'systemctl status bootloader-update --no-pager -l'
sec 02-journal-bootloader-update-b0 'journalctl -b 0 -u bootloader-update --no-pager -o short-monotonic'
sec 03-journal-bootloader-update-b-1 'journalctl -b -1 -u bootloader-update --no-pager -o short-monotonic'
sec 03b-journal-bootloader-update-first-boot "journalctl -b $FIRST -u bootloader-update --no-pager -o short-monotonic"
sec 03c-journal-bootloader-update-all-boots-verbose 'journalctl -u bootloader-update --no-pager -o verbose'
sec 03d-unit-bootloader-update 'systemctl cat bootloader-update --no-pager; systemctl show bootloader-update -p ExecStart -p Result -p ExecMainStatus -p ExecMainCode -p ActiveState --no-pager'
sec 04-bootupctl-status 'bootupctl status'
sec 05-bootupctl-status-json 'bootupctl status --json'
sec 05b-bootupd-version-state 'bootupctl --version; rpm -q bootupd ostree rpm-ostree bootc grub2-efi-x64 shim-x64; ls -la /usr/lib/bootupd /usr/lib/bootupd/updates; cat /usr/lib/bootupd/updates/*.json; echo; cat /boot/bootupd-state.json; echo'
sec 06-rpm-ostree-status-v 'rpm-ostree status -v'
sec 06b-bootc-status 'bootc status'
sec 07-systemctl-failed 'systemctl --failed --no-pager'
sec 08-df 'df -h /sysroot /var'
sec 09a-findmnt 'findmnt /boot /boot/efi /sysroot; echo; findmnt'
sec 09b-efibootmgr 'efibootmgr -v; ls /sys/firmware/efi | head'
sec 09c-ls-boot 'ls -la /boot /boot/loader /boot/loader/entries; readlink -f /boot/loader; echo; head -50 /boot/loader/entries/*.conf; echo; ls -laR /boot/efi | head -80; cat /boot/grub2/grubenv 2>&1; ls -la /boot/grub2'
sec 09d-cmdline-kargs 'cat /proc/cmdline; rpm-ostree kargs'
sec 10-list-boots 'journalctl --list-boots --no-pager'
sec 11-first-boot-grep "journalctl -b $FIRST --no-pager -o short-monotonic | grep -Ei '$RX'"
sec 11b-b-1-grep "journalctl -b -1 --no-pager -o short-monotonic | grep -Ei '$RX'"
sec 12-reboot-callers "journalctl -b $FIRST --no-pager -o short-monotonic | grep -Ei 'reboot|power.?off|shutdown|systemd-logind|initiated|Requested transaction'"
sec 12b-hardware-setup-journal "journalctl -b $FIRST -u bazzite-hardware-setup --no-pager -o short-monotonic; echo ----; journalctl -b 0 -u bazzite-hardware-setup --no-pager -o short-monotonic"
sec 12c-rpm-ostreed-journal "journalctl -b $FIRST -u rpm-ostreed -u ostree-finalize-staged -u ostree-finalize-staged-hold -u bootc-fetch-apply-updates --no-pager -o short-monotonic"
sec 12d-hardware-setup-unit 'systemctl cat bazzite-hardware-setup --no-pager; for f in $(systemctl show -p ExecStart --value bazzite-hardware-setup | grep -o "path=[^ ;]*" | cut -d= -f2); do echo "=== $f"; cat "$f"; done'
secb 13-journal-first-boot-full "journalctl -b $FIRST --no-pager -o short-monotonic"
secb 13b-journal-current-boot-full 'journalctl -b 0 --no-pager -o short-monotonic'
sec 14a-ostree-admin-status 'ostree admin status'
sec 14b-origin 'for f in /ostree/deploy/default/deploy/*.origin; do echo "=== $f"; cat "$f"; done'
sec 15a-firstboot-unit-files "systemctl list-unit-files --no-pager | grep -Ei 'ublue|bazzite|rebase|signing|firstboot|first-boot'"
sec 15b-firstboot-unit-cat "for u in \$(systemctl list-unit-files --no-pager --no-legend | grep -Ei 'ublue|bazzite|rebase|signing|firstboot|first-boot' | awk '\$2==\"enabled\"||\$2==\"static\"||\$2==\"alias\"{print \$1}'); do echo \"===== \$u\"; systemctl cat \"\$u\" --no-pager; done"
sec 17-efi-boot-log 'journalctl -b 0 -k --no-pager | grep -Ei "efi|secure" | head -40; mokutil --sb-state 2>&1'
ESPH='cd /boot/efi && find . -type f -print0 | sort -z | xargs -0 sha256sum'
sec 18a-esp-tree-before-update "$ESPH | tee /run/esp-before.txt"
sec 18b-bootupctl-update-vvv 'bootupctl update -vvv'
sec 18c-esp-tree-after-update "$ESPH | tee /run/esp-after.txt"
sec 18d-esp-tree-diff 'diff /run/esp-before.txt /run/esp-after.txt && echo "ESP file tree UNCHANGED"'
sec 18e-bootupctl-status-after-update 'bootupctl status'
printf '\n@@ALLDONE@@\n' 
