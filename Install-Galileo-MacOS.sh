#!/usr/bin/env bash
# Galileo Setup for macOS - the one file to download for a fresh install.
# Download this file, then run it:
#   chmod +x Install-Galileo-MacOS.sh && ./Install-Galileo-MacOS.sh
#
# It fetches install/install.sh from GitHub and runs it, which clones
# Galileo, ensures Python 3.11+ and git are present, creates a virtual
# environment, installs dependencies, and creates a desktop alias.
# Safe to re-run.

set -euo pipefail

INSTALLER_URL="https://raw.githubusercontent.com/gordtulloch/Galileo/main/install/install.sh"
TEMP_SCRIPT="$(mktemp /tmp/galileo-install.XXXXXX.sh)"

echo "========================================"
echo " Galileo Setup for macOS"
echo "========================================"
echo
echo "This will download the Galileo installer and set up Galileo on this Mac."
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but was not found. Please install Xcode Command Line Tools:" >&2
    echo "  xcode-select --install" >&2
    exit 1
fi

echo "Downloading installer..."
if ! curl -fsSL "$INSTALLER_URL" -o "$TEMP_SCRIPT"; then
    echo "Error: failed to download the installer from GitHub." >&2
    echo "Check your internet connection and try again." >&2
    rm -f "$TEMP_SCRIPT"
    exit 1
fi

chmod +x "$TEMP_SCRIPT"
echo "Running installer..."
echo
bash "$TEMP_SCRIPT" "$@"
EXIT_CODE=$?
rm -f "$TEMP_SCRIPT"
exit $EXIT_CODE
