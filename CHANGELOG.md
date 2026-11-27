# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Removed

- **The scripts to build INDI from source on Arch Linux are gone** (`build_indi_stable.sh`, `build_indi_nightly.sh`, `indi_build_common.sh`). They were never part of a release, and Arch Linux / StellarMate OS is no longer a platform we are pursuing for this. The wiki's Installation page no longer mentions them.

### Fixed

- **Set Park Position no longer claims success when the mount refuses (`EQP-MNT-010`).** Over INDI, Galileo sent the command and never read the answer, so a refusal (the ZWO AM5 refuses on old firmware, in alt-az mode, before homing, while moving, or when a park position already exists) looked like success and the next Park went elsewhere. Galileo now waits for the driver's reply and shows its reason in the status bar, with the mount firmware (where the driver reports it) and the INDI driver version. The Mount screen's help lists the AM3/AM5 conditions.

### Added

- **A remote capture now uses the filter it names (`CSURF-120`).** `imaging.capture` accepted a filter but only wrote it into the frame's header; the wheel did not move, so a frame could be labelled with a filter it was not taken through. The Master now moves the wheel first (applying the filter's focus offset), refuses a filter the wheel does not have, and, when none is named, records the filter the wheel is on. Needs the Master restarted; no plugin reinstall.

- **Remote clients can watch an autofocus run.** Each autofocus exposure now becomes the Pier's latest frame for previews (`PREV-070`), so the Focus screen picture in the MobileConnect apps updates point by point. The same frame is what other clients' current-frame views show until the next capture. Needs the Master restarted; no plugin reinstall.

- **Flats runs say what they are doing (`CAL-110`).** The Flats Assistant and session Flat Capture blocks now post notices when starting, preparing the mount or flat panel, changing filter, adjusting exposure or panel brightness, capturing each frame, and finishing, stopping or failing.

### Changed

- **Flats appear on the Imaging screen like other frames.** Each exposure is shown in the preview, and the status line reports how many flats reached the Library. Saved flats now carry the full FITS header (telescope, camera, gain, temperature and so on), so the Library no longer files them with those unknown.

## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.10alpha | 2026-11-25 | [Changelog](docs/changelog/0.9.10alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.10alpha) |
| 0.9.09alpha | 2026-11-23 | [Changelog](docs/changelog/0.9.09alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.09alpha) |
| 0.9.08alpha | 2026-11-18 | [Changelog](docs/changelog/0.9.08alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.08alpha) |
| 0.9.07alpha | 2026-11-12 | [Changelog](docs/changelog/0.9.07alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.07alpha) |
| 0.9.06alpha | 2026-11-09 | [Changelog](docs/changelog/0.9.06alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.06alpha) |
| 0.9.05alpha | 2026-11-05 | [Changelog](docs/changelog/0.9.05alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.05alpha) |
| 0.9.04alpha | 2026-11-03 | [Changelog](docs/changelog/0.9.04alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.04alpha) |
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
