#!/usr/bin/env bash
# Galileo launcher for macOS: checks for updates, then starts the app.
# Created by install/install.sh as the desktop app icon's target.
# See install/upgrade.sh for a manual, on-demand update that does not
# also start the app.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------
if [[ -d ".git" ]] && command -v git >/dev/null 2>&1; then
    echo "Checking for updates..."
    if git fetch origin main 2>/dev/null; then
        BEHIND="$(git rev-list HEAD..origin/main --count 2>/dev/null || echo 0)"
        if [[ "$BEHIND" -gt 0 ]]; then
            DIRTY="$(git status --porcelain)"
            if [[ -n "$DIRTY" ]]; then
                echo "Local changes found - skipping auto-update. Run install/upgrade.sh to update by hand."
            else
                echo "Updating to the latest version ($BEHIND commit(s) behind)..."
                git reset --hard origin/main >/dev/null
                echo "Updated."
            fi
        else
            echo "Already up to date."
        fi
    else
        echo "Could not check for updates (offline?). Continuing with the current version."
    fi
    echo
fi

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Galileo's virtual environment was not found." >&2
    echo "Run install/install.sh first." >&2
    # On macOS show a dialog if running as a .app bundle
    if command -v osascript >/dev/null 2>&1; then
        osascript -e 'display dialog "Galileo'\''s virtual environment was not found.\n\nRun install/install.sh first." buttons {"OK"} default button "OK" with icon stop with title "Galileo"' 2>/dev/null || true
    fi
    exit 1
fi

echo "Starting Galileo..."
exec "$VENV_PYTHON" -m galileo.app
