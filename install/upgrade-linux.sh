#!/usr/bin/env bash
# Galileo Upgrade Script for Linux (Debian/Ubuntu)
# Manually pulls the latest code and refreshes Python dependencies.
# The desktop launcher (install/launch_galileo.sh) already does this
# automatically on every launch, so this script is for:
#   - updating without starting the app, or
#   - after local changes blocked the automatic update.
#
# Usage:  bash install/upgrade-linux.sh

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

info "========================================"
info "Galileo Upgrade (Linux)"
info "========================================"
echo
info "Working directory: $REPO_ROOT"
echo

# ---------------------------------------------------------------------------
# git pull
# ---------------------------------------------------------------------------
if ! command -v git >/dev/null 2>&1; then
    error "git was not found on PATH."
    error "Install it with:  sudo apt-get install git"
    exit 1
fi

info "Running: git pull"
if ! git pull; then
    error "git pull failed."
    error "Resolve any local changes or conflicts and try again."
    exit 1
fi
echo

# ---------------------------------------------------------------------------
# Dependency refresh
# ---------------------------------------------------------------------------
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    warn "Virtual environment not found at $VENV_PYTHON."
    warn "Run install/install-linux.sh to perform a full installation first."
    exit 1
fi

info "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip

info "Refreshing dependencies from requirements.txt..."
if ! "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"; then
    error "Dependency installation failed. See the output above for details."
    exit 1
fi

echo
info "========================================"
info "Galileo upgrade complete!"
info "========================================"
echo
echo "Start Galileo with:  $REPO_ROOT/install/launch_galileo.sh"
echo
