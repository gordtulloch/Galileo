#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze Galileo into a self-contained one-folder app with PyInstaller.

Run from the repo root on the platform being targeted (PyInstaller cannot cross-compile):

    pip install -e . pyinstaller
    python packaging/build.py

Output: dist/Galileo/ (Windows, Linux) or dist/Galileo.app (macOS).  The per-platform
wrappers (windows/galileo.iss, macos/build_dmg.sh, linux/build_appimage.sh) turn that
into the single installable file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
SEP = ";" if sys.platform == "win32" else ":"


def main() -> None:
    args = [
        str(ROOT / "packaging" / "launcher.py"),
        "--name", "Galileo",
        "--noconfirm", "--clean",
        "--windowed",
        "--paths", str(ROOT),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        # galileo/app.py resolves assets as <package parent>/assets, i.e. <bundle>/assets.
        "--add-data", f"{ROOT / 'assets' / 'images'}{SEP}assets/images",
        # peewee-migrate loads these .py files from a directory at run time, so they are data, not imports.
        "--add-data", f"{ROOT / 'galileo' / 'library' / 'migrations'}{SEP}galileo/library/migrations",
        # In-app help is Markdown read from disk at run time (galileo/help/__init__.py).
        "--add-data", f"{ROOT / 'galileo' / 'help' / 'content'}{SEP}galileo/help/content",
        "--collect-submodules", "galileo",
        "--collect-submodules", "peewee_migrate",
        "--collect-data", "astropy",
        "--collect-data", "astroquery",
        "--collect-data", "photutils",
        "--collect-data", "certifi",
        "--copy-metadata", "keyring",
        "--hidden-import", "keyring.backends",
    ]
    if sys.platform == "win32":
        args += ["--icon", str(ROOT / "assets" / "images" / "galileo.ico")]
    elif sys.platform == "darwin":
        icns = ROOT / "packaging" / "macos" / "galileo.icns"
        if icns.exists():
            args += ["--icon", str(icns)]
        args += ["--osx-bundle-identifier", "com.gordtulloch.galileo"]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
