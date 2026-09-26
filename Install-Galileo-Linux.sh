#!/usr/bin/env bash
# Galileo Setup for Linux (Debian/Ubuntu) - the one file to download for a fresh install.
# Download this file, then run it:
#   chmod +x Install-Galileo-Linux.sh && ./Install-Galileo-Linux.sh
#
# It fetches install/install-linux.sh from GitHub and runs it, which clones
# Galileo, ensures Python 3.11+, git and required system packages are present,
# creates a virtual environment, installs dependencies, and creates a desktop
# launcher entry.  Safe to re-run.

set -euo pipefail

INSTALLER_URL="https://raw.githubusercontent.com/gordtulloch/Galileo/main/install/install-linux.sh"
TEMP_SCRIPT="$(mktemp /tmp/galileo-install.XXXXXX.sh)"

echo "========================================"
echo " Galileo Setup for Linux (Debian/Ubuntu)"
echo "========================================"
echo
echo "This will download the Galileo installer and set up Galileo on this machine."
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required but was not found.  Installing it now..." >&2
    if command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y curl
    else
        echo "Error: please install curl (apt-get install curl) and re-run." >&2
        exit 1
    fi
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
