#!/usr/bin/env bash
# Inspect a powered-off guest disk read-only from the host: partitions, root
# growth, grow-root unit result + stamp, failed units, os-release, booted digest.
set -u
DISK=$1; OUT=$2
exec > >(tee "$OUT") 2>&1
modprobe nbd max_part=16
qemu-nbd --read-only --connect=/dev/nbd0 "$DISK"; sleep 2; partprobe /dev/nbd0 || true; sleep 1
echo "== lsblk"; lsblk -b -o NAME,SIZE,FSTYPE,PARTLABEL /dev/nbd0
echo "== sgdisk -v"; sgdisk -v /dev/nbd0
echo "== sgdisk -p"; sgdisk -p /dev/nbd0
ROOT=$(lsblk -nrpo NAME,FSTYPE /dev/nbd0 | awk '$2=="btrfs"{print $1}' | tail -1)
echo "root partition: $ROOT size $(blockdev --getsize64 "$ROOT") bytes"
M=/tmp/qa-root; mkdir -p $M
mount -o ro,subvolid=5 "$ROOT" $M || mount -o ro "$ROOT" $M
echo "== btrfs filesystem show"; btrfs filesystem show "$ROOT"
echo "== btrfs usage"; btrfs filesystem usage -b $M | head -8
VAR=$(find $M -maxdepth 6 -type d -path '*/deploy/*/var' | head -1); echo "var dir: $VAR"
[ -d "$M/var" ] && [ -z "$VAR" ] && VAR=$M/var
echo "== stamp"; ls -l "$VAR/lib/vettv/grow-root.done" 2>&1
ETC=$(find $M -maxdepth 6 -type d -path '*/deploy/*/deploy/*/etc' | head -1)
echo "== os-release"; cat "$ETC/os-release" 2>/dev/null || cat "$(dirname "$ETC")/usr/lib/os-release"
echo "== ostree deployments"; ls "$M"/ostree/deploy/*/deploy/ 2>&1
J="$VAR/log/journal"
if [ -d "$J" ]; then
  echo "== boots"; journalctl -D "$J" --list-boots --no-pager
  echo "== vettv-grow-root (all boots)"; journalctl -D "$J" -u vettv-grow-root.service --no-pager -o short-monotonic
  echo "== failed units (last boot)"; journalctl -D "$J" -b 0 --no-pager -o cat | grep -E "Failed with result|Failed to start|entered failed state" | sort | uniq -c
  echo "== greeter/login (last boot)"; journalctl -D "$J" -b 0 --no-pager -o short-monotonic | grep -Ei "sddm|plasma-setup|initial-setup|Reached target graphical" | head -40
  echo "== network (should be none)"; journalctl -D "$J" -b 0 --no-pager -o cat | grep -Ei "link becomes ready|DHCP" | head
  echo "== errors (last boot, prio<=3)"; journalctl -D "$J" -b 0 -p 3 --no-pager -o short-monotonic | head -80
else
  echo "no persistent journal at $J"
fi
umount $M; qemu-nbd --disconnect /dev/nbd0
