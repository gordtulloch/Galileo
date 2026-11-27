# shellcheck shell=bash
# Shared steps for build_indi_stable.sh and build_indi_nightly.sh (Arch Linux).
# Not meant to be run directly: the two scripts set FLAVOUR, INDI_REF and
# INDI_3RD_REF, source this file and call build_indi.
#
# Adapted for Arch Linux from Dušan Poizl's Debian scripts:
#   https://gitea.nouspiro.space/nou/astro-soft-build
#
# Environment overrides:
#   BUILD_DIR              parent of the source/build directory (default: $HOME)
#   JOBS                   parallel compile jobs (default: CPU count, 2 if low on memory)
#   SKIP_DEPS=1            do not run pacman
#   INDI_CMAKE_ARGS        extra cmake options for INDI core
#   INDI_3RDPARTY_CMAKE_ARGS
#                          extra cmake options for indi-3rdparty, applied to both the
#                          library and driver passes, e.g. "-DWITH_LIMESDR=Off"

INDI_REPO="https://github.com/indilib/indi.git"
INDI_3RD_REPO="https://github.com/indilib/indi-3rdparty.git"

# Arch equivalents of the upstream apt list, limited to what INDI and
# indi-3rdparty use. Arch ships headers with the libraries (no -dev packages).
ARCH_DEPS=(
    base-devel git cmake pkgconf
    # INDI core
    libnova cfitsio libusb zlib gsl libjpeg-turbo curl fftw libev systemd-libs
    libtheora libxisf rtl-sdr
    # indi-3rdparty drivers
    libtiff libftdi gpsd libraw libdc1394 libgphoto2 boost limesuite ffmpeg
    zeromq hidapi mosquitto libgpiod bluez-libs i2c-tools python
)

die() {
    echo "ERROR: $*" >&2
    exit 1
}

step() {
    printf '\n==> %s\n' "$*"
}

check_system() {
    command -v pacman >/dev/null || die "pacman not found; this script is for Arch Linux."
    [ "$(id -u)" -ne 0 ] || die "Run as a normal user; sudo is used where needed."

    # 'make install' into /usr would silently overwrite files pacman owns.
    local packaged
    packaged=$(pacman -Qq | grep -E '^(libindi(-git)?|indi-.+|lib(apogee|asi|atik|fli|playerone|qhy|qhyccd|sbig|svbony|toupcam)(-git)?)$' || true)
    if [ -n "$packaged" ]; then
        echo "These installed packages conflict with a source build:" >&2
        echo "$packaged" >&2
        die "Remove them first (sudo pacman -Rns <package>), then run this again."
    fi
}

install_dependencies() {
    if [ "${SKIP_DEPS:-0}" = "1" ]; then
        step "SKIP_DEPS=1, not installing dependencies"
        return
    fi
    step "Installing build dependencies"
    # -Syu, not -Sy: Arch does not support partial upgrades.
    sudo pacman -Syu --needed "${ARCH_DEPS[@]}"
}

choose_jobs() {
    if [ -n "${JOBS:-}" ]; then
        return
    fi
    JOBS=$(nproc)
    # 64-bit compilation needs more memory per job.
    if [ "$(getconf LONG_BIT)" -eq 64 ] &&
        [ "$(awk '/^MemTotal/ {print $2}' /proc/meminfo)" -lt 5000000 ]; then
        echo "Low memory, limiting to JOBS=2"
        JOBS=2
    fi
}

# fetch_source <directory> <repository> <ref>
fetch_source() {
    local dir="$ROOTDIR/$1" repo="$2" ref="$3"
    step "Fetching $1 ($ref)"
    if [ ! -d "$dir/.git" ]; then
        git init -q "$dir"
        git -C "$dir" remote add origin "$repo"
    fi
    git -C "$dir" fetch --depth=1 origin "$ref"
    # Local edits in these build checkouts are discarded.
    git -C "$dir" switch -q --detach --discard-changes FETCH_HEAD
    git -C "$dir" log -1 --format='    %h %cd %s' --date=short
}

# build_component <source directory> <build directory> [cmake options...]
build_component() {
    local src="$ROOTDIR/$1" build="$ROOTDIR/$2"
    shift 2
    step "Building $(basename "$build")"
    # Install under /usr: Arch's loader does not search /usr/local/lib by default.
    cmake -S "$src" -B "$build" \
        -DCMAKE_INSTALL_PREFIX=/usr \
        -DCMAKE_BUILD_TYPE=Release \
        -DUDEVRULES_INSTALL_DIR=/usr/lib/udev/rules.d \
        "$@" || die "Configuration of $(basename "$build") failed"
    cmake --build "$build" --parallel "$JOBS" || die "Compilation of $(basename "$build") failed"

    # Remove what the previous run installed, only now that the new build succeeded.
    if [ -f "$build/install_manifest.txt" ]; then
        tr -d '\r' <"$build/install_manifest.txt" | sudo xargs -r -d '\n' rm -f --
    fi
    sudo cmake --install "$build" || die "Installation of $(basename "$build") failed"
    sudo ldconfig
}

build_indi() {
    check_system
    install_dependencies
    choose_jobs

    export CFLAGS="-march=native -w -Wno-psabi -D_FILE_OFFSET_BITS=64"
    export CXXFLAGS="$CFLAGS"
    # CMake 4 (Arch) rejects projects declaring a minimum below 3.5.
    export CMAKE_POLICY_VERSION_MINIMUM=3.5

    ROOTDIR="${BUILD_DIR:-$HOME}/indi-$FLAVOUR"
    mkdir -p "$ROOTDIR"

    local core_args=() third_args=()
    read -r -a core_args <<<"${INDI_CMAKE_ARGS:-}"
    read -r -a third_args <<<"${INDI_3RDPARTY_CMAKE_ARGS:-}"

    fetch_source indi "$INDI_REPO" "$INDI_REF"
    fetch_source indi-3rdparty "$INDI_3RD_REPO" "$INDI_3RD_REF"

    build_component indi build-indi "${core_args[@]}"
    # The vendor libraries must be installed before the drivers can be configured.
    build_component indi-3rdparty build-indi-lib -DBUILD_LIBS=1 "${third_args[@]}"
    build_component indi-3rdparty build-indi-3rdparty "${third_args[@]}"

    sudo udevadm control --reload-rules || echo "Could not reload udev rules; reboot to apply them."

    step "INDI $FLAVOUR build installed (sources and build files in $ROOTDIR)"
    if ! id -nG | grep -qw uucp; then
        echo "For serial devices, add yourself to the 'uucp' group and log in again:"
        echo "    sudo usermod -aG uucp $(id -un)"
    fi
}
