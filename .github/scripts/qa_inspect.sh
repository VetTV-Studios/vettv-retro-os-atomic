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
mount -o ro,subvolid=5 "$ROOT" $M || mount -o ro,subvolid=5,rescue=nologreplay "$ROOT" $M || mount -o ro "$ROOT" $M
echo "== btrfs filesystem show"; btrfs filesystem show "$ROOT"
echo "== btrfs usage"; btrfs filesystem usage -b $M | head -8
OS=$(find $M -maxdepth 3 -type d -name ostree -path '*ostree' | head -1); OS=${OS:-$M/ostree}; echo "ostree dir: $OS"
VAR=$(find $M -maxdepth 6 -type d -path '*/deploy/*/var' | head -1); echo "var dir: $VAR"
[ -d "$M/var" ] && [ -z "$VAR" ] && VAR=$M/var
echo "== stamp"; ls -l "$VAR/lib/vettv/grow-root.done" 2>&1
DEP=$(ls -d "$OS"/deploy/*/deploy/*.0 2>/dev/null | head -1); echo "deployment: $DEP"
echo "== os-release"; cat "$DEP/usr/lib/os-release"
echo "== ostree deployments"; ls "$OS"/deploy/*/deploy/ 2>&1
cat "$OS"/deploy/*/deploy/*.origin 2>/dev/null
echo "== image digest (ostree commit metadata)"
for c in $(ls "$OS"/deploy/*/deploy/ | grep -v origin | sed 's/\.[0-9]*$//' | sort -u); do
  ostree --repo="$OS/repo" show "$c" 2>/dev/null | grep -i digest
  ostree --repo="$OS/repo" show --print-metadata-key=ostree.manifest-digest "$c" 2>/dev/null
done
echo "== ESP and /boot file-content hashes (mounted ro, noload)"
for pn in $(lsblk -nrpo NAME,FSTYPE /dev/nbd0 | awk '$2=="vfat"||$2=="ext4"{print $1}'); do
  B=/tmp/qa-p; mkdir -p $B; o=ro; [ "$(lsblk -nro FSTYPE $pn)" = ext4 ] && o=ro,noload
  mount -o $o "$pn" $B && (cd $B && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | sed "s|-|$pn files|"; find . -type f | wc -l) ; umount $B
done
echo "== /boot loader layout (diagnosis only)"
BP=$(lsblk -nrpo NAME,FSTYPE /dev/nbd0 | awk '$2=="ext4"{print $1}' | head -1); B=/tmp/qa-b; mkdir -p $B
if mount -o ro,noload "$BP" $B; then
  ls -la $B $B/loader $B/loader/entries 2>&1
  for l in $(find $B -maxdepth 3 -type l); do echo "symlink $l -> $(readlink $l)"; done
  ls -la $B/loader.0 $B/loader.1 $B/loader.0/entries $B/loader.1/entries 2>&1
  echo "-- bootupd-state.json"; cat $B/bootupd-state.json 2>&1 | head -60
  umount $B
fi
ESPP=$(lsblk -nrpo NAME,FSTYPE /dev/nbd0 | awk '$2=="vfat"{print $1}' | head -1)
if mount -o ro "$ESPP" $B; then echo "-- ESP tree"; find $B -maxdepth 4 | sort; umount $B; fi
echo "-- bootloader-update unit"; cat "$DEP"/usr/lib/systemd/system/bootloader-update.service 2>&1
J="${J:-$VAR/log/journal}"
echo "-- bootloader-update journal (all boots)"; journalctl -D "$J" -u bootloader-update.service --no-pager -o short-monotonic 2>&1 | head -150
echo "-- bootupctl/bootupd lines (all boots)"; journalctl -D "$J" --no-pager -o short-monotonic 2>&1 | grep -Ei "bootupctl|bootupd|loader/entries" | head -80
echo "== ESP and /boot raw device hashes"
for pn in $(lsblk -nrpo NAME,FSTYPE,PARTLABEL /dev/nbd0 | awk '$2=="vfat"||$2=="ext4"||$2=="xfs"{print $1}'); do
  echo "$(sha256sum "$pn" | cut -d' ' -f1)  $pn ($(lsblk -nro FSTYPE,PARTLABEL "$pn"))"
done
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
