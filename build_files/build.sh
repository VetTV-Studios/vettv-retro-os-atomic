#!/bin/bash
# VetTV Retro OS image build (base: ghcr.io/ublue-os/bazzite-nvidia-open stable, pinned by digest in Containerfile; KDE Plasma).
set -ouex pipefail

# VetTV overlay: art, SDDM/lock-screen/wallpaper defaults, first-boot services.
cp -avf "/ctx/system_files"/. /

### Branding: drop Fedora logos/marks for neutral generic-logos, then VetTV art on top.
# Bazzite may ship its own logo package instead of fedora-logos; only swap what is installed.
if rpm -q fedora-logos >/dev/null 2>&1; then
  dnf5 -y swap fedora-logos generic-logos || echo "WARN: fedora-logos swap skipped"
fi
for f in fedora-logos-httpd fedora-logos-classic; do rpm -q "$f" >/dev/null 2>&1 && dnf5 -y remove "$f" || true; done

### Packages
dnf5 -y install \
  wine wine-core.i686 winetricks \
  kvantum \
  plymouth-plugin-script \
  flatpak
# NOTE: DOSBox-X ships ONLY as the pinned Flathub Flatpak (first boot, Wolf gate), never the Fedora RPM.

### First-run wizard (raw/qcow2 disks ship with no user account; no default user or password in the image)
# KDE plasma-setup creates the first user (always added to wheel), language, keyboard, time zone.
# Gated by plasma-setup.service.d/50-vettv-no-regular-user.conf (runs only while no UID>=1000 user exists).
rpm -q plasma-setup || dnf5 -y install --setopt=install_weak_deps=False plasma-setup
rpm -q plasma-setup
test -f /usr/lib/systemd/system/plasma-setup.service
test ! -e /etc/plasma-setup-done

### os-release (Fedora/uBlue name replaced; upstream license notices kept under /usr/share/licenses)
FEDORA_VER="$(rpm -E %fedora)"
cat > /usr/lib/os-release <<EOF
NAME="VetTV Retro OS"
PRETTY_NAME="VetTV Retro OS ${FEDORA_VER} (Bazzite / Universal Blue base)"
ID=vettv-retro-os
ID_LIKE="fedora"
VERSION_ID="${FEDORA_VER}"
VARIANT="KDE Plasma"
VARIANT_ID=kde
PLATFORM_ID="platform:f${FEDORA_VER}"
ANSI_COLOR="0;36"
LOGO=vettv-mark
HOME_URL="https://vettvretro.com/"
DEFAULT_HOSTNAME="vettv-retro-os"
EOF
echo "VetTV Retro OS ${FEDORA_VER}" > /etc/vettv-release

### Theme defaults
plymouth-set-default-theme vettv-retro-os
gtk-update-icon-cache -f /usr/share/icons/VetTV || true
ln -sf /usr/share/pixmaps/vettv-retro-os/vettv-mark.svg /usr/share/pixmaps/vettv-mark.svg
for s in 16 24 32 48 64 128 256; do
  install -Dm644 /usr/share/pixmaps/vettv-retro-os/vettv-mark_${s}.png /usr/share/icons/hicolor/${s}x${s}/apps/vettv-mark.png
done

### Rebuild initramfs so the VetTV Plymouth theme is used at boot
KVER="$(ls /usr/lib/modules | sort -V | tail -1)"
dracut --no-hostonly --kver "$KVER" --reproducible -v --add ostree -f "/usr/lib/modules/$KVER/initramfs.img"
chmod 0600 "/usr/lib/modules/$KVER/initramfs.img"

### Services
systemctl enable vettv-dosbox-x-flatpak.service
systemctl enable vettv-grow-root.service
systemctl enable plasma-setup.service

### Policy guard: no ROMs/BIOS/Microsoft system files in the image
hits=$(find / -xdev \( -iname '*.rom' -o -iname 'bios*.bin' -o -iname '*.bios' \
  -o -iname 'msdos.sys' -o -iname 'io.sys' -o -iname 'command.com' -o -iname 'win.com' \) \
  -not -path '/proc/*' -not -path '/sys/*' -not -path '*/wine/*' -not -path '*/firmware/*' 2>/dev/null || true)
if [ -n "$hits" ]; then echo "POLICY FAIL:"; echo "$hits"; exit 1; fi
