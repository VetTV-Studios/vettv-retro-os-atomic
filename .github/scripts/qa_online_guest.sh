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
  [ "${t:-0}" != 0 ] && break
  # Passed-gate path: earlier boot already wrote the stamp, so this boot skips the unit.
  [ -e /var/lib/vettv/dosbox-x-flatpak.done ] && break
  sleep 3
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
sec o${B}-09-flatpak-app-commit flatpak info --system --show-commit com.dosbox_x.DOSBox-X
sec o${B}-10-flatpak-runtime-commit flatpak info --system --show-commit org.freedesktop.Platform//26.08
sec o${B}-11-flatpak-mask flatpak mask --system
sec o${B}-12-flatpak-override flatpak override --system --show com.dosbox_x.DOSBox-X
sec o${B}-13-done-stamp bash -c 'if [ -e /var/lib/vettv/dosbox-x-flatpak.done ]; then echo "done-stamp: present"; ls -l /var/lib/vettv/dosbox-x-flatpak.done; echo "-- contents --"; cat /var/lib/vettv/dosbox-x-flatpak.done; else echo "done-stamp: MISSING"; ls -la /var/lib/vettv/ 2>&1; fi'
sec o${B}-14-failed-units systemctl --failed --no-pager
# Launch check as qatest in a real login session (Faye/Naomi/Priya).
# The online job boots a fresh overlay, so the wizard has not created qatest;
# we create the same uid 1000 / wheel / home user as test setup only.
# Do not invent a display (no Xvfb, do not set or unset DISPLAY/WAYLAND).
# No secrets (any password is random and never printed).
launch_as_qatest() {
  if ! getent passwd qatest >/dev/null; then
    if getent passwd 1000 >/dev/null; then
      echo "test-setup: uid 1000 already exists but is not qatest:"
      getent passwd 1000
      return 1
    fi
    useradd -m -u 1000 -U -G wheel -s /bin/bash qatest || { echo "test-setup: useradd qatest failed"; return 1; }
    # Unlock a random password so a login session is allowed; never print it.
    pw=$(openssl rand -base64 18 2>/dev/null || head -c 18 /dev/urandom | base64)
    if ! echo "qatest:${pw}" | chpasswd >/dev/null 2>&1; then
      pw=
      echo "test-setup: chpasswd failed (continuing; machinectl may still work)"
    else
      pw=
      echo "test-setup: created qatest uid 1000 with home and wheel (password set, not logged)"
    fi
  else
    echo "test-setup: qatest already exists"
    getent passwd qatest
  fi
  if ! getent passwd qatest >/dev/null; then
    echo "test-setup: qatest missing after setup"
    return 1
  fi
  loginctl enable-linger qatest >/dev/null 2>&1 || true
  systemctl start user@1000.service >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    [ -d /run/user/1000 ] && break
    sleep 1
  done
  echo "test-setup: /run/user/1000 $( [ -d /run/user/1000 ] && echo present || echo missing )"

  inner=/run/qaonl-flatpak-version.sh
  cat > "$inner" <<'INNER'
#!/bin/bash
# Runs inside the qatest login session. Do not set or unset DISPLAY/WAYLAND.
printf 'id: '; id
printf 'HOME=%s\n' "${HOME-}"
printf 'USER=%s\n' "${USER-}"
if [ -z "${XDG_RUNTIME_DIR+x}" ]; then echo 'XDG_RUNTIME_DIR: unset'; else printf 'XDG_RUNTIME_DIR=%s\n' "$XDG_RUNTIME_DIR"; fi
if [ -z "${DBUS_SESSION_BUS_ADDRESS+x}" ]; then echo 'DBUS_SESSION_BUS_ADDRESS: unset'; else printf 'DBUS_SESSION_BUS_ADDRESS=%s\n' "$DBUS_SESSION_BUS_ADDRESS"; fi
if [ -z "${DISPLAY+x}" ]; then echo 'DISPLAY: unset'; else printf 'DISPLAY=%s\n' "$DISPLAY"; fi
if [ -z "${WAYLAND_DISPLAY+x}" ]; then echo 'WAYLAND_DISPLAY: unset'; else printf 'WAYLAND_DISPLAY=%s\n' "$WAYLAND_DISPLAY"; fi
printf 'inner-command: /usr/bin/flatpak run com.dosbox_x.DOSBox-X --version\n'
set +e
output=$(timeout 60 /usr/bin/flatpak run com.dosbox_x.DOSBox-X --version 2>&1)
rc=$?
set -e
printf 'exit: %s\n' "$rc"
printf 'output:\n%s\n' "$output"
printf 'informational command: /usr/bin/flatpak run com.dosbox_x.DOSBox-X -version\n'
set +e
iv=$(timeout 60 /usr/bin/flatpak run com.dosbox_x.DOSBox-X -version 2>&1)
irc=$?
set -e
printf 'informational -version exit: %s\n' "$irc"
printf 'informational -version output:\n%s\n' "$iv"
exit "$rc"
INNER
  chmod 0755 "$inner"
  chown qatest:qatest "$inner" 2>/dev/null || true

  rc=1
  if command -v machinectl >/dev/null; then
    echo 'method: machinectl'
    echo 'command: machinectl shell qatest@ /usr/bin/bash /run/qaonl-flatpak-version.sh'
    set +e
    machinectl shell qatest@ /usr/bin/bash "$inner"
    rc=$?
    set -e
  elif command -v systemd-run >/dev/null; then
    echo 'method: systemd-run --machine=qatest@ --user --wait --pipe (machinectl not found)'
    echo 'command: systemd-run --machine=qatest@ --user --wait --pipe /usr/bin/bash /run/qaonl-flatpak-version.sh'
    set +e
    systemd-run --machine=qatest@ --user --wait --pipe /usr/bin/bash "$inner"
    rc=$?
    set -e
  elif command -v runuser >/dev/null; then
    echo 'method: runuser -l (last resort; machinectl and systemd-run --machine unavailable)'
    echo 'command: runuser -l qatest -c /usr/bin/bash /run/qaonl-flatpak-version.sh'
    set +e
    runuser -l qatest -c "/usr/bin/bash $inner"
    rc=$?
    set -e
  else
    echo 'method: none (machinectl, systemd-run, and runuser missing)'
    echo 'command: (missing)'
    return 1
  fi
  return "$rc"
}

sec o${B}-15-flatpak-version launch_as_qatest
printf '@@ONLINE-DONE boot=%s@@\n' "$B" | tty
# After a successful first install, reboot once so boot 2 can prove the service
# is skipped by ConditionPathExists. A first-boot auto-reboot may already be
# coming; a second request is harmless.
if [ "$B" = 1 ] && [ -e /var/lib/vettv/dosbox-x-flatpak.done ]; then
  sleep 2
  systemctl reboot || /sbin/reboot
fi
