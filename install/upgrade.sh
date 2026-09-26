#!/usr/bin/env bash
# Galileo Upgrade Script for macOS
# Manually pulls the latest code and refreshes dependencies.
# The desktop launcher (install/launch_galileo.sh) already does this
# automatically on every launch, so this script is for:
#   - updating without starting the app, or
#   - after local changes blocked the automatic update.
#
# Usage:  bash install/upgrade.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo -e "\033[0;32m$*\033[0m"; }
warn()    { echo -e "\033[0;33m$*\033[0m"; }
error()   { echo -e "\033[0;31m$*\033[0m" >&2; }

show_dialog() {
    # Show a macOS dialog if osascript is available, otherwise just print.
    local msg="$1" title="${2:-Galileo}"
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display dialog \"$msg\" buttons {\"OK\"} default button \"OK\" with title \"$title\"" 2>/dev/null || true
    else
        echo "$msg"
    fi
}

info "========================================"
info "Galileo Upgrade"
info "========================================"
echo
info "Working directory: $REPO_ROOT"
echo

# ---------------------------------------------------------------------------
# git pull
# ---------------------------------------------------------------------------
if ! command -v git >/dev/null 2>&1; then
    error "git was not found on PATH."
    error "Install Xcode Command Line Tools with:  xcode-select --install"
    exit 1
fi

info "Running: git pull"
if ! git pull; then
    MSG="git pull failed.\n\nResolve any local changes or conflicts and try again."
    error "$MSG"
    show_dialog "$MSG" "Galileo Upgrade Failed"
    exit 1
fi
echo

# ---------------------------------------------------------------------------
# Dependency refresh
# ---------------------------------------------------------------------------
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    warn "Virtual environment not found at $VENV_PYTHON."
    warn "Run install/install.sh to perform a full installation first."
    exit 1
fi

info "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip

info "Refreshing dependencies from requirements.txt..."
if ! "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"; then
    MSG="Dependency installation failed.\n\nSee the terminal output for details."
    error "$MSG"
    show_dialog "$MSG" "Galileo Upgrade Failed"
    exit 1
fi

echo
info "========================================"
info "Galileo upgrade complete!"
info "========================================"
echo
echo "Start Galileo with:  $REPO_ROOT/install/launch_galileo.sh"
echo
show_dialog "Galileo has been updated successfully." "Galileo Upgrade"
