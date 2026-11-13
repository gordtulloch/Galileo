# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Added

- **`docs/Astrofiler Back Propogation.md`.** A running list of Library changes (`galileo/library`, `galileo/ui/library`, `galileo/commands`) to be applied to upstream AstroFiler; seeded with the faster SFTP download change. From now on every Library change is recorded there in the same turn. Docs only.

### Changed

- **Library: Seestar frames are precalibrated only when downloaded from the Seestar.** Correction to the 0.9.07alpha entry "Library no longer treats Seestar frames as precalibrated": frames Galileo captures from a Seestar as INDI/Alpaca BLOBs are raw and are ingested uncalibrated, but frames downloaded from the Seestar (Library > Download, `galileo.commands.download`) are already calibrated by the telescope, so `registerFitsImage`/`submitFileToDB` gained a `precalibrated` argument that the Seestar download paths set and those frames are ingested with `fitsFileCalibrated=1`. Sessions built from them still show the per-frame state rather than a "Precalibrated" source label (that label remains iTelescope-only). Covered by `TC-LIB-130`.

- **Wiki reorganised for the user manual; links here updated.** The wiki's Getting Started Guide was split into `01.-Installation` (what you need, installing and starting Galileo, plus installing INDI and an ASCOM Alpaca bridge, which were separate articles) and `02.-Getting-Started` (window tour through first exposure). The Options article was removed and each settings page is now described in the article for the feature it configures (horizon in Star Atlas, autofocus defaults in Focus, solver settings in Plate Solving, Library folders and tabs in the Library, Connect Link and notifications in NodeConnect, outreach in WebConnect, plugin management in the new Plugins Documentation appendix). Equipment became `03.-Setting-up-Equipment`, the screen articles gained "Using ..." titles, the plugin articles became appendices (`A.-Plugin-Developers-Guide`, `B.-Plugins-Documentation` with `B1`/`B2`), and new articles cover WebConnect and MobileConnect. `README.md`, `docs/UAT.md` and `docs/UAT-generic.md` linked to the old page names and now point at the new ones. Documentation only, no code change.

### Fixed

- **The sky survey background now falls back to more backup sites when CDS is unreachable.** The Mellinger photo-mosaic behind the star atlas only tried CDS's two hosts (`alasky` and `alaskybis.cds.unistra.fr`), which share one DNS domain and one institution, so a CDS or DNS outage left the atlas with no sky image. It now also tries CDS's older `alasky.u-strasbg.fr` name and the independent IAS Orsay mirror (`healpix.ias.u-psud.fr/CDS_P_Mellinger_color`), remembering whichever answers first. The added hosts could not be reached from the development machine (its DNS was failing), so they are untested live. No visible controls changed, so inline help, wiki and design docs are unchanged.

- **The mount jog pad and the Imaging nudge pad now use arrows (↑ ↓ ← → and ↖ ↗ ↙ ↘) instead of N/S/E/W letters, and the Mount page's Rate box is wide enough to read.** The Rate drop-down sat beside its label squeezed to about one character; it now sits below the jog pad at a usable width. Hovering a button still names the direction. No change to what the buttons do. The wiki's Imaging table was updated.


- **Test suite and lint pass again on CI.** Closing a test's main window opened the modal "Support Us" quit dialog and hung the run until the timeout (tests now stub it); two ruff findings (`RUF012` mutable class attributes in `telescope_sftp.py`, `B905` in `scripts/download_stats.py`) are fixed; `test_head`/`test_link_gateway` now match the Gateway's reworded "take control of this Pier" refusal; and the sky/visibility tests no longer fail when astropy's bundled Earth-orientation (IERS) data is older than 30 days. No user-visible change, so no help, wiki or design-doc update.


## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.07alpha | 2026-11-12 | [Changelog](docs/changelog/0.9.07alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.07alpha) |
| 0.9.06alpha | 2026-11-09 | [Changelog](docs/changelog/0.9.06alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.06alpha) |
| 0.9.05alpha | 2026-11-05 | [Changelog](docs/changelog/0.9.05alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.05alpha) |
| 0.9.04alpha | 2026-11-03 | [Changelog](docs/changelog/0.9.04alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.04alpha) |
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
