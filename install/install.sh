#!/usr/bin/env bash
# Galileo Installation Script for macOS
# Clones (or updates) the Galileo repository, ensures Python 3.11+ and
# Homebrew/git are present, creates a virtual environment, installs
# dependencies, and creates a desktop alias.
#
# Usage:
#   From inside an existing checkout:  bash install/install.sh
#   Standalone (fetches the repo too): bash install.sh --install-dir ~/Galileo
#
# This script is safe to re-run at any time - it refreshes dependencies and
# the desktop alias rather than reinstalling from scratch.  The desktop alias
# (install/launch_galileo.sh) also checks for updates on every launch, so
# most users never need to re-run this script; see install/launch_galileo.sh
# and install/upgrade.sh for the update system.

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
INSTALL_DIR="$HOME/Galileo"
REPO_URL="https://github.com/gordtulloch/Galileo.git"
BRANCH="main"
FORCE=0
QUIET=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --repo-url)    REPO_URL="$2";    shift 2 ;;
        --branch)      BRANCH="$2";      shift 2 ;;
        --force)       FORCE=1;          shift   ;;
        --quiet)       QUIET=1;          shift   ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo -e "\033[0;36m$*\033[0m"; }
success() { echo -e "\033[0;32m$*\033[0m"; }
warn()    { echo -e "\033[0;33m$*\033[0m"; }
error()   { echo -e "\033[0;31m$*\033[0m" >&2; }

ask_yes() {
    # ask_yes "Question text" - returns 0 (yes) or 1 (no)
    if [[ $QUIET -eq 1 ]]; then return 0; fi
    local answer
    read -r -p "$1 [Y/n] " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

# ---------------------------------------------------------------------------
# Xcode Command Line Tools (provides git and other essentials on macOS)
# ---------------------------------------------------------------------------
ensure_xcode_clt() {
    if ! xcode-select -p >/dev/null 2>&1; then
        warn "Xcode Command Line Tools are not installed."
        if ask_yes "Install Xcode Command Line Tools now?"; then
            info "Requesting Xcode Command Line Tools install (a dialog will appear)..."
            xcode-select --install 2>/dev/null || true
            echo
            warn "After the dialog finishes, re-run this script to continue."
            exit 0
        else
            error "Xcode Command Line Tools are required (provides git and compilers)."
            error "Install them with:  xcode-select --install"
            exit 1
        fi
    fi
}

# ---------------------------------------------------------------------------
# Homebrew (optional but used to install Python if needed)
# ---------------------------------------------------------------------------
ensure_homebrew() {
    if command -v brew >/dev/null 2>&1; then return 0; fi
    warn "Homebrew was not found."
    if ask_yes "Install Homebrew now? (recommended - used to install Python 3.11)"; then
        info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add Homebrew to PATH for the remainder of this session
        if [[ -x /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -x /usr/local/bin/brew ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        success "Homebrew installed."
    else
        warn "Skipping Homebrew - Python 3.11+ must already be installed on PATH."
    fi
}

# ---------------------------------------------------------------------------
# Python 3.11+
# ---------------------------------------------------------------------------
find_python311() {
    # Returns the first python3 binary that is >= 3.11
    for cmd in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; exit(0 if sys.version_info[:2] >= (3, 11) else 1)" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

install_python() {
    warn "Python 3.11+ was not found."
    if ! ask_yes "Install Python 3.11 via Homebrew now?"; then
        error "Please install Python 3.11+ from https://www.python.org/downloads/macos/ and re-run this script."
        exit 1
    fi

    if ! command -v brew >/dev/null 2>&1; then
        error "Homebrew is required to install Python automatically. Install it first:"
        error "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi

    info "Installing Python 3.11 via Homebrew..."
    brew install python@3.11
    # Homebrew installs python3.11 into its prefix; update PATH so we see it
    if [[ -x /opt/homebrew/bin/python3.11 ]]; then
        export PATH="/opt/homebrew/bin:$PATH"
    elif [[ -x /usr/local/bin/python3.11 ]]; then
        export PATH="/usr/local/bin:$PATH"
    fi
    success "Python 3.11 installed."
}

# ---------------------------------------------------------------------------
# Locate (or clone) the Galileo repository
# ---------------------------------------------------------------------------
info "========================================"
info "Galileo Installation Script for macOS"
info "========================================"
echo

# If we are running from inside an existing checkout (install/install.sh),
# use that checkout in place. Otherwise clone/update at INSTALL_DIR.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$PARENT_DIR/pyproject.toml" ]]; then
    REPO_ROOT="$PARENT_DIR"
else
    ensure_xcode_clt

    if ! command -v git >/dev/null 2>&1; then
        error "git was not found even after ensuring Xcode CLT. Please open a new terminal and re-run."
        exit 1
    fi

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        warn "Existing Galileo checkout found at $INSTALL_DIR - updating..."
        cd "$INSTALL_DIR"
        DIRTY="$(git status --porcelain)"
        if [[ -n "$DIRTY" ]]; then
            warn "Warning: local changes found in $INSTALL_DIR - skipping git pull."
        else
            git fetch origin "$BRANCH"
            git checkout "$BRANCH"
            git pull --ff-only origin "$BRANCH"
        fi
    else
        info "Cloning Galileo into $INSTALL_DIR..."
        git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    fi
    REPO_ROOT="$INSTALL_DIR"
fi

cd "$REPO_ROOT"
success "Installing into: $REPO_ROOT"
echo

# ---------------------------------------------------------------------------
# Ensure prerequisites
# ---------------------------------------------------------------------------
ensure_xcode_clt
ensure_homebrew

info "Checking Python installation..."
PYTHON_CMD="$(find_python311 || true)"
if [[ -z "$PYTHON_CMD" ]]; then
    install_python
    PYTHON_CMD="$(find_python311 || true)"
fi
if [[ -z "$PYTHON_CMD" ]]; then
    error "Still could not find Python 3.11+ after installation."
    error "Open a new terminal (so PATH updates take effect) and re-run this script."
    exit 1
fi
success "Using $("$PYTHON_CMD" --version) ($PYTHON_CMD)"
echo

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------
VENV_DIR="$REPO_ROOT/.venv"

if [[ -d "$VENV_DIR" && $FORCE -eq 1 ]]; then
    warn "Removing existing virtual environment (--force)..."
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
else
    success "Using existing virtual environment."
fi
echo

VENV_PYTHON="$VENV_DIR/bin/python"

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
info "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip

info "Installing dependencies from requirements.txt (this downloads several scientific packages - allow a few minutes)..."
"$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"
success "Dependencies installed."
echo

# ---------------------------------------------------------------------------
# Desktop alias (macOS)
# ---------------------------------------------------------------------------
# On macOS a true "shortcut" is an .app bundle or a Finder alias.
# We create a minimal wrapper .app bundle so the user can double-click it
# from the Desktop (or Dock) without opening a terminal.
# ---------------------------------------------------------------------------
CREATE_SHORTCUT=1
if [[ $QUIET -eq 0 ]]; then
    ask_yes "Create a desktop app icon?" || CREATE_SHORTCUT=0
fi

if [[ $CREATE_SHORTCUT -eq 1 ]]; then
    LAUNCHER_SRC="$REPO_ROOT/install/launch_galileo.sh"
    APP_NAME="Galileo"
    DESKTOP_APP="$HOME/Desktop/${APP_NAME}.app"
    APP_MACOS="$DESKTOP_APP/Contents/MacOS"
    APP_RESOURCES="$DESKTOP_APP/Contents/Resources"

    mkdir -p "$APP_MACOS" "$APP_RESOURCES"

    # Info.plist
    cat > "$DESKTOP_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>         <string>Galileo</string>
    <key>CFBundleDisplayName</key>  <string>Galileo</string>
    <key>CFBundleIdentifier</key>   <string>com.gordtulloch.galileo</string>
    <key>CFBundleVersion</key>      <string>1.0</string>
    <key>CFBundleExecutable</key>   <string>Galileo</string>
    <key>CFBundlePackageType</key>  <string>APPL</string>
    <key>LSUIElement</key>          <false/>
</dict>
</plist>
PLIST

    # Copy icon if it exists (convert .ico → .icns is non-trivial; use PNG if present)
    ICON_SRC=""
    for f in "$REPO_ROOT/assets/images/galileo.icns" \
              "$REPO_ROOT/assets/images/galileo.png" \
              "$REPO_ROOT/assets/images/galileo.ico"; do
        if [[ -f "$f" ]]; then ICON_SRC="$f"; break; fi
    done
    if [[ -n "$ICON_SRC" ]]; then
        cp "$ICON_SRC" "$APP_RESOURCES/"
        ICON_FILENAME="$(basename "$ICON_SRC")"
        # Add icon to plist
        /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string ${ICON_FILENAME%.*}" \
            "$DESKTOP_APP/Contents/Info.plist" 2>/dev/null || true
    fi

    # Executable wrapper
    cat > "$APP_MACOS/Galileo" <<APPSCRIPT
#!/usr/bin/env bash
exec bash "$LAUNCHER_SRC"
APPSCRIPT
    chmod +x "$APP_MACOS/Galileo"

    success "Desktop app icon created: $DESKTOP_APP"
fi

echo
success "========================================"
success "Galileo installation complete!"
success "========================================"
echo
info "Start Galileo from the desktop icon, or run:"
echo "  $REPO_ROOT/install/launch_galileo.sh"
echo
info "That launcher checks for updates (git pull) every time it starts."
info "To update by hand instead, run:  $REPO_ROOT/install/upgrade.sh"
echo
