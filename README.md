# VetTV Retro OS (Atomic)

VetTV Retro OS is VetTV Studios' retro PC gaming distro: DOS, Win16 and Windows 98/2000-era games on KDE Plasma.
It is a custom [bootc](https://github.com/bootc-dev/bootc) image built from [ublue-os/image-template](https://github.com/ublue-os/image-template)
on top of `ghcr.io/ublue-os/kinoite-main` (Universal Blue, Fedora Atomic KDE).

**Status: pre-release test builds only.** No image here is a stable release, and nothing should be flashed until VetTV QA passes that exact image digest / ISO hash.

- Image: `ghcr.io/vettv-studios/vettv-retro-os` (signed with cosign; public key `cosign.pub`)
- DOSBox-X ships as a pinned Flathub Flatpak installed at first boot, gated by QA's Wolf3D Floor 1 check.
- No games, ROMs, BIOS files or Microsoft system files are included. Bring your own legally owned software.

## Branding and trademarks
VetTV Retro OS is not affiliated with or endorsed by the Fedora Project, Red Hat, or Universal Blue.
Fedora logos are replaced with `generic-logos` plus original VetTV art. Upstream license notices are kept unchanged.

## License (OPEN)
- VetTV-authored code and config in this repo: Apache-2.0 by default (same as the template, see `LICENSE`). **OPEN: final license not yet decided by VetTV Studios.**
- VetTV art (wallpapers, logos, icons, Plymouth, SDDM, cursors under `system_files/`): © VetTV Studios, all rights reserved, under VetTV's own terms (OPEN), not covered by Apache-2.0.
- Packages in the image keep their own upstream licenses.

The original template documentation is in `README-image-template.md`.
