#!/bin/sh
# VetTV Retro OS: set the default CRT Glow wallpaper once per new account, then disable itself.
plasma-apply-wallpaperimage /usr/share/wallpapers/VetTV-CRT-Glow >/dev/null 2>&1 || exit 0
rm -f "$HOME/.config/autostart/vettv-plasma-first-login.desktop"
