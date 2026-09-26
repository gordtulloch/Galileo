#!/usr/bin/env bash
# Galileo Installation Script for Linux (Debian/Ubuntu)
# Clones (or updates) the Galileo repository, ensures git, Python 3.11+ and
# required system packages are present (installing via apt if needed), creates
# a virtual environment, installs Python dependencies, and creates a desktop
# launcher (.desktop file) and optional application-menu entry.
#
# Usage:
#   From inside an existing checkout:  bash install/install-linux.sh
#   Standalone (fetches the repo too): bash install-linux.sh --install-dir ~/Galileo
#
# This script is safe to re-run at any time - it refreshes dependencies and
# the desktop launcher rather than reinstalling from scratch.  The launcher
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
    if [[ $QUIET -eq 1 ]]; then return 0; fi
    local answer
    read -r -p "$1 [Y/n] " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

# ---------------------------------------------------------------------------
# apt helper - only calls sudo apt-get when something is actually missing
# ---------------------------------------------------------------------------
APT_UPDATED=0
apt_install() {
    local pkgs=("$@")
    local missing=()
    for pkg in "${pkgs[@]}"; do
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
    done
    [[ ${#missing[@]} -eq 0 ]] && return 0

    if ! command -v sudo >/dev/null 2>&1; then
        error "sudo is required to install packages: ${missing[*]}"
        error "Run this script as root, or install them manually: apt-get install ${missing[*]}"
        exit 1
    fi

    if [[ $APT_UPDATED -eq 0 ]]; then
        info "Running apt-get update..."
        sudo apt-get update -qq
        APT_UPDATED=1
    fi
    info "Installing: ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
}

# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
ensure_git() {
    if command -v git >/dev/null 2>&1; then return 0; fi
    warn "git was not found."
    if ask_yes "Install git via apt now?"; then
        apt_install git
    else
        error "git is required. Install it with:  sudo apt-get install git"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Distro detection
# ---------------------------------------------------------------------------
# Populate DISTRO_ID, DISTRO_LIKE, DISTRO_CODENAME, DISTRO_PRETTY from
# /etc/os-release.  ID_LIKE is a space-separated list of parent distros, e.g.
# Stellarmate / LUbuntu have  ID=lubuntu  ID_LIKE="ubuntu debian"
# Raspberry Pi OS has         ID=raspbian  ID_LIKE=debian
# Linux Mint has              ID=linuxmint ID_LIKE="ubuntu debian"
# Pop!_OS has                 ID=pop       ID_LIKE="ubuntu debian"
DISTRO_ID=""
DISTRO_LIKE=""
DISTRO_CODENAME=""
DISTRO_PRETTY=""

detect_distro() {
    if [[ -f /etc/os-release ]]; then
        # Use a subshell so the sourced variables don't pollute the environment.
        eval "$(grep -E '^(ID|ID_LIKE|VERSION_CODENAME|PRETTY_NAME)=' /etc/os-release \
              | sed 's/^/DISTRO_OS_/; s/=ID=/=DISTRO_ID=/; s/^DISTRO_OS_ID=/DISTRO_ID=/;
                     s/^DISTRO_OS_ID_LIKE=/DISTRO_LIKE=/;
                     s/^DISTRO_OS_VERSION_CODENAME=/DISTRO_CODENAME=/;
                     s/^DISTRO_OS_PRETTY_NAME=/DISTRO_PRETTY=/' \
              | grep -E '^(DISTRO_ID|DISTRO_LIKE|DISTRO_CODENAME|DISTRO_PRETTY)=' || true)"
        # Simpler, more portable approach
        DISTRO_ID="$(     grep -E '^ID='             /etc/os-release | cut -d= -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]' || true)"
        DISTRO_LIKE="$(   grep -E '^ID_LIKE='        /etc/os-release | cut -d= -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]' || true)"
        DISTRO_CODENAME="$(grep -E '^VERSION_CODENAME=' /etc/os-release | cut -d= -f2 | tr -d '"' | tr '[:upper:]' '[:lower:]' || true)"
        DISTRO_PRETTY="$( grep -E '^PRETTY_NAME='   /etc/os-release | cut -d= -f2 | tr -d '"' || true)"
    fi
}

# Returns 0 if the distro is Ubuntu or Ubuntu-family (LUbuntu, Stellarmate,
# Linux Mint, Pop!_OS, etc.) - i.e. the deadsnakes PPA will work.
is_ubuntu_family() {
    echo "${DISTRO_ID} ${DISTRO_LIKE}" | grep -qwi "ubuntu"
}

# Returns 0 if the distro is Debian or Debian-family but NOT Ubuntu-family
# (Raspberry Pi OS, Armbian on non-Ubuntu base, vanilla Debian, etc.)
is_debian_only() {
    ! is_ubuntu_family && echo "${DISTRO_ID} ${DISTRO_LIKE}" | grep -qwi "debian"
}

# ---------------------------------------------------------------------------
# Python 3.11+
# ---------------------------------------------------------------------------
find_python311() {
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

# Build Python 3.11 from source via pyenv.
# Used when apt cannot supply 3.11 (e.g. RPi OS Bullseye, old Debian, any
# non-apt distro).  Takes ~5 min on RPi 5, ~15 min on RPi 4.
install_python_pyenv() {
    info "Installing Python 3.11 from source via pyenv..."
    info "This can take 5-20 minutes depending on your hardware."

    # Build dependencies
    apt_install \
        make build-essential libssl-dev zlib1g-dev libbz2-dev \
        libreadline-dev libsqlite3-dev curl libncursesw5-dev \
        xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

    PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"

    if [[ ! -d "$PYENV_ROOT" ]]; then
        info "Downloading pyenv..."
        curl -fsSL https://pyenv.run | bash
    else
        warn "pyenv already present at $PYENV_ROOT - skipping download."
    fi

    export PYENV_ROOT
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)" 2>/dev/null || true

    info "Building Python 3.11.9 (please be patient)..."
    pyenv install --skip-existing 3.11.9
    pyenv global 3.11.9

    # Persist pyenv in the user's shell profile so future terminals find it.
    for profile in "$HOME/.bashrc" "$HOME/.profile" "$HOME/.zshrc"; do
        if [[ -f "$profile" ]] && ! grep -q 'pyenv init' "$profile"; then
            cat >> "$profile" <<'PYENVRC'

# Added by Galileo installer
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
PYENVRC
        fi
    done

    success "Python 3.11.9 installed via pyenv."
}

install_python311() {
    detect_distro

    # Show what Python IS available so the user knows where they stand.
    FOUND_PY_VER=""
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            FOUND_PY_VER="$($cmd --version 2>&1 || true)"
            break
        fi
    done

    warn "Python 3.11+ was not found."
    [[ -n "$FOUND_PY_VER" ]] && warn "Highest available Python: $FOUND_PY_VER"
    info "Detected OS: ${DISTRO_PRETTY:-unknown Linux} (codename: ${DISTRO_CODENAME:-unknown})"
    echo

    if ! ask_yes "Attempt to install Python 3.11 automatically now?"; then
        error "Please install Python 3.11+ manually and re-run this script."
        error "  sudo apt-get install python3.11 python3.11-venv python3.11-dev"
        exit 1
    fi

    # ------------------------------------------------------------------
    # Strategy 1: python3.11 is already in the apt cache (Bookworm,
    # Ubuntu 23.04+, Ubuntu 24.04, etc.)
    # ------------------------------------------------------------------
    if apt-cache show python3.11 >/dev/null 2>&1; then
        apt_install python3.11 python3.11-venv python3.11-dev
        success "Python 3.11 installed."
        return
    fi

    # ------------------------------------------------------------------
    # Strategy 2: Ubuntu family (includes Stellarmate/LUbuntu, Mint,
    # Pop!_OS …) → offer the deadsnakes PPA.
    # ------------------------------------------------------------------
    if is_ubuntu_family; then
        warn "python3.11 is not in your current apt sources."
        warn "Ubuntu ${DISTRO_CODENAME:+(}${DISTRO_CODENAME}${DISTRO_CODENAME:+)} ships an older Python by default."
        if ask_yes "Add the deadsnakes PPA (ppa:deadsnakes/ppa) to get Python 3.11?"; then
            apt_install software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            APT_UPDATED=0
            apt_install python3.11 python3.11-venv python3.11-dev
            success "Python 3.11 installed via deadsnakes PPA."
            return
        fi
        # User declined PPA - fall through to pyenv offer below.
    fi

    # ------------------------------------------------------------------
    # Strategy 3: Debian / Raspberry Pi OS without Python 3.11 in apt
    # (typically Bullseye / Debian 11 or older).
    # ------------------------------------------------------------------
    if is_debian_only; then
        warn "Your system (${DISTRO_PRETTY:-Debian}) does not include Python 3.11 in apt."
        if [[ "$DISTRO_CODENAME" == "bullseye" || "$DISTRO_CODENAME" == "buster" || \
              "$DISTRO_CODENAME" == "stretch" ]]; then
            warn "Raspberry Pi OS / Debian '${DISTRO_CODENAME}' ships Python 3.9 or older."
            warn "The easiest fix is to upgrade your OS to Bookworm (Debian 12):"
            warn "  https://www.raspberrypi.com/documentation/computers/os.html"
            warn "Alternatively, Python 3.11 can be built from source via pyenv (~15 min on RPi 4)."
        fi
    fi

    # ------------------------------------------------------------------
    # Strategy 4 (universal fallback): build from source via pyenv.
    # ------------------------------------------------------------------
    warn "python3.11 is not available in apt on this system."
    if ask_yes "Build Python 3.11 from source via pyenv? (takes 5-20 min)"; then
        install_python_pyenv
    else
        error "Cannot continue without Python 3.11+."
        error "Options:"
        error "  • Upgrade to a newer OS release that ships Python 3.11+"
        error "  • Install pyenv manually: https://github.com/pyenv/pyenv"
        error "  • Install Python 3.11 from source: https://www.python.org/downloads/"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# System packages required at runtime (Qt6 / PySide6 needs several)
# ---------------------------------------------------------------------------
install_system_deps() {
    info "Checking required system packages..."
    # libxcb-* and libGL are needed by PySide6/Qt6 on a headless or minimal desktop install.
    # python3-pip is the bootstrap; pip inside the venv is upgraded separately.
    apt_install \
        git \
        python3-pip \
        python3-venv \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 \
        libgl1 \
        libglib2.0-0
}

# ---------------------------------------------------------------------------
# Locate (or clone) the Galileo repository
# ---------------------------------------------------------------------------
info "========================================"
info "Galileo Installation Script for Linux"
info "(Debian / Ubuntu and derivatives)"
info "========================================"
echo

detect_distro
[[ -n "$DISTRO_PRETTY" ]] && info "Detected OS: $DISTRO_PRETTY"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$PARENT_DIR/pyproject.toml" ]]; then
    REPO_ROOT="$PARENT_DIR"
else
    ensure_git

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
install_system_deps

info "Checking Python installation..."
PYTHON_CMD="$(find_python311 || true)"
if [[ -z "$PYTHON_CMD" ]]; then
    install_python311
    PYTHON_CMD="$(find_python311 || true)"
fi
if [[ -z "$PYTHON_CMD" ]]; then
    error "Still could not find Python 3.11+ after installation."
    error "Open a new terminal and re-run this script."
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

info "Installing dependencies from requirements.txt (allow a few minutes for scientific packages)..."
"$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"
success "Dependencies installed."
echo

# ---------------------------------------------------------------------------
# Desktop launcher (.desktop file)
# ---------------------------------------------------------------------------
CREATE_LAUNCHER=1
if [[ $QUIET -eq 0 ]]; then
    ask_yes "Create a desktop launcher?" || CREATE_LAUNCHER=0
fi

if [[ $CREATE_LAUNCHER -eq 1 ]]; then
    LAUNCHER_SRC="$REPO_ROOT/install/launch_galileo.sh"
    chmod +x "$LAUNCHER_SRC"

    # Resolve icon path (prefer PNG for Linux)
    ICON_PATH=""
    for f in "$REPO_ROOT/assets/images/galileo.png" \
              "$REPO_ROOT/assets/images/galileo.svg" \
              "$REPO_ROOT/assets/images/galileo.ico"; do
        if [[ -f "$f" ]]; then ICON_PATH="$f"; break; fi
    done

    DESKTOP_FILE="$HOME/Desktop/Galileo.desktop"
    mkdir -p "$HOME/Desktop"

    cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Galileo
Comment=Galileo Astrophotography Imaging Suite
Exec=bash "$LAUNCHER_SRC"
Icon=$ICON_PATH
Terminal=false
Categories=Science;Astronomy;
StartupNotify=true
DESKTOP

    chmod +x "$DESKTOP_FILE"

    # Mark as trusted (GNOME / Nautilus)
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
    fi

    # Also install into ~/.local/share/applications for the app menu
    APPS_DIR="$HOME/.local/share/applications"
    mkdir -p "$APPS_DIR"
    cp "$DESKTOP_FILE" "$APPS_DIR/Galileo.desktop"

    success "Desktop launcher created: $DESKTOP_FILE"
    success "Application menu entry created: $APPS_DIR/Galileo.desktop"
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
