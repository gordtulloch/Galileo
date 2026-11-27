#!/usr/bin/env bash
# Build and install the newest INDI sources (core and 3rd party master) on Arch Linux.
# Bleeding edge: it can fail to build or be unstable. Prefer build_indi_stable.sh.
#
#   bash scripts/build_indi_nightly.sh
#
# Run it again to update. Overrides are listed in indi_build_common.sh.
# Only one INDI build can be installed at a time; this replaces a stable build.

set -euo pipefail

FLAVOUR=nightly
INDI_REF=master
INDI_3RD_REF=master

# shellcheck source=indi_build_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/indi_build_common.sh"
build_indi
