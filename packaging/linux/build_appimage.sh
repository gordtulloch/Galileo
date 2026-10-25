#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
# Wrap dist/Galileo into dist/Galileo-<version>-linux-<arch>.AppImage (x86_64 or aarch64 / Raspberry Pi 5).
# Usage: packaging/linux/build_appimage.sh <version>   (run from the repo root, after packaging/build.py)
set -euo pipefail
VERSION="${1:?version required}"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) ;;
    aarch64|arm64) ARCH=aarch64 ;;
    *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

APPDIR="build/Galileo.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications"
cp -R dist/Galileo "$APPDIR/usr/lib/galileo"
# The GLib stack must come from the host: the build machine's (older) copy clashes with the host's
# gio/gvfs/dconf modules ("undefined symbol: g_task_set_static_name") and corrupts Qt's use of them.
find "$APPDIR/usr/lib/galileo" \( -name 'libglib-2.0.so*' -o -name 'libgio-2.0.so*' -o -name 'libgobject-2.0.so*' \
    -o -name 'libgmodule-2.0.so*' -o -name 'libgthread-2.0.so*' \) -delete
cp assets/images/logo.png "$APPDIR/galileo.png"
cp "$APPDIR/galileo.png" "$APPDIR/.DirIcon"

cat > "$APPDIR/galileo.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Galileo
Comment=Astrophotography imaging suite
Exec=Galileo
Icon=galileo
Categories=Science;Astronomy;Graphics;
Terminal=false
DESKTOP
cp "$APPDIR/galileo.desktop" "$APPDIR/usr/share/applications/"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/galileo/Galileo" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

TOOL="build/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    wget -q -O "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

OUT="dist/Galileo-${VERSION}-linux-${ARCH}.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" "$APPDIR" "$OUT"
echo "Built $OUT"
