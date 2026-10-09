#!/usr/bin/env bash
# Launches Galileo from the repository root.
# Usage: ./run.sh [args passed through to galileo.app]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer the project virtualenv if one exists, in either POSIX or Windows layout.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "No Python interpreter found (looked for .venv, python3, python)." >&2
    exit 1
fi

exec "$PYTHON" -m galileo.app "$@"
