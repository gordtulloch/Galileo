#!/usr/bin/env bash
# Build and install the latest tested INDI release (core and 3rd party) on Arch Linux.
#
#   bash scripts/build_indi_stable.sh
#
# To build a different release, set INDI_VERSION (and INDI_3RD_VERSION if the
# 3rd-party tag differs). Other overrides are listed in indi_build_common.sh.
# Only one INDI build can be installed at a time; this replaces a nightly build.

set -euo pipefail

INDI_VERSION="${INDI_VERSION:-v2.2.5}"
INDI_3RD_VERSION="${INDI_3RD_VERSION:-$INDI_VERSION}"

FLAVOUR=stable
INDI_REF="refs/tags/$INDI_VERSION"
INDI_3RD_REF="refs/tags/$INDI_3RD_VERSION"

# shellcheck source=indi_build_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/indi_build_common.sh"
build_indi
