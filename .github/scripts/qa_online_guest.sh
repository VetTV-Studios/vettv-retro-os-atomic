#!/bin/bash
# QA online first-boot probe (test VM only, SMBIOS credential, root). Waits for
# vettv-dosbox-x-flatpak.service to finish on this boot, then dumps its result,
# journal, installed Flatpaks and the on-image pins env to ttyS0. No secrets.
trap '' HUP
export SYSTEMD_COLORS=0 SYSTEMD_PAGER= LC_ALL=C
B=$(journalctl --list-boots -q 2>/dev/null | wc -l)
tty() { ( flock 9; cat > /dev/ttyS0 2>/dev/null ) 9>/run/qaonl.lock || true; }
sec() { local n=$1; shift; local o rc; o=$( "$@" 2>&1 ); rc=$?
  printf '@@BEGIN %s@@\n%s\n@@END %s rc=%s@@\n' "$n" "$o" "$n" "$rc" | tty; }
printf '@@QA boot=%s@@\n' "$B" | tty
for _ in $(seq 1 200); do
  t=$(systemctl show -p ExecMainExitTimestampMonotonic --value vettv-dosbox-x-flatpak.service)
  [ "${t:-0}" != 0 ] && break; sleep 3
done
sleep 5
sec o${B}-01-net bash -c 'ip -br addr; ip route; getent hosts dl.flathub.org; curl -sS -o /dev/null -w "flathub HTTP %{http_code}\n" --max-time 20 https://dl.flathub.org/repo/summary.idx'
sec o${B}-02-service bash -c 'systemctl show vettv-dosbox-x-flatpak.service -p ActiveState,SubState,Result,ExecMainStatus,ExecMainCode,ConditionResult,ExecMainExitTimestamp; systemctl status vettv-dosbox-x-flatpak.service --no-pager -n 0'
sec o${B}-03-journal journalctl -b -u vettv-dosbox-x-flatpak.service --no-pager -o short-monotonic
sec o${B}-04-flatpak-apps flatpak list --system --app --columns=application,version,branch,active,origin
sec o${B}-05-flatpak-info flatpak info --system com.dosbox_x.DOSBox-X
sec o${B}-06-flatpak-all bash -c 'flatpak list --system --all --columns=ref,active; echo "-- remotes"; flatpak remotes --system; echo "-- grep 4964216d in flatpak repo/state"; H=$(grep -rl 4964216d /var/lib/flatpak/repo/refs /var/lib/flatpak/app /var/lib/flatpak/repo/config 2>/dev/null; flatpak list --system --all --columns=active 2>/dev/null | grep -c 4964216d | grep -v "^0$"); echo "$H"; echo "4964216d hits: $(printf %s "$H" | grep -c .)"; ls -la /var/lib/vettv/ 2>&1'
sec o${B}-07-pins-env cat /usr/share/vettv/flatpak-pins.env
sec o${B}-08-image bash -c 'rpm-ostree status --booted | head -8; cat /sysroot/.bootc-aleph.json'
printf '@@ONLINE-DONE boot=%s@@\n' "$B" | tty
