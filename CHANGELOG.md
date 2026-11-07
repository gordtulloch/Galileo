# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Added

- **MobileConnect plugin design note** (`docs/plugins/mobileconnect/SDD.md` 5.2): records how the first draft in `Galileo-Plugins/mobileconnect` differs from the design, because Connect Link's route table matches exact paths and its stream has no connection hook. Documentation only; nothing in Galileo itself changed.

- **Polar alignment: "Slew from Zenith" option.** Checked (default, as before) the run slews to the zenith, solves to confirm the mount, then moves to the measuring position. Unchecked, it solves where the mount already points (syncing the mount to the solution if it is off), then turns in RA from there for the second and third positions, skipping only the zenith slew (this takes one extra check frame before the three measuring frames, and nothing moves the mount first, so it must already point at a clear field away from the pole and meridian). Added as `PolarAlignSettings.slew_from_zenith`, a checkbox on the Solve > Polar Alignment tab, inline help and the wiki.

- **WebConnect: the page marks itself stale and disables operations when its live stream drops (`WCON-780`).** Done in the plugin (`Galileo-Plugins/webconnect`); the checklist now records it. Emergency operations stay attemptable. Documentation only in this repository.

- **Catalog image pack now includes the large click-to-enlarge images, and the enlarged view reads from the local cache.** Clicking a thumbnail on Planning > Targets or What's Up Tonight fetched a 640 px image live from the CDS survey service, so it failed whenever that service was down. `scripts/build_thumbnail_pack.py` (via `build_pack(sizes=...)`) now downloads each object at both 150 px and 640 px (`--no-large` for tiles only; expect a much bigger ZIP), and Options > Planning > Download Catalog Images unpacks both into the thumbnail cache. `_show_full_image` now checks the cache first and only contacts the survey service when the image is missing, saying so (and pointing at Download Catalog Images) if that fails. Existing packs still install; they just lack the large images until rebuilt and re-uploaded.

### Changed

- **The Library now defaults to `~/REPOSITORY` and `~/REPOSITORY.incoming`.** Previously the repository and incoming (source) folders were empty until set under Options > Library, so Auto-Save to Library did nothing on a fresh install. When either is unset, `galileo.library.config.load_config` now fills in `REPOSITORY` / `REPOSITORY.incoming` in the user's home folder and creates them; a folder you have chosen is never overridden. Applies to database-backed settings only, not `--config` files. Updated Options > Library help and the wiki.

- **Connect plugins checklist: stale Connect Link lines corrected, NodeConnect confirmed built.** Two lines still said Options > Outreach was not built (it was, 2026-11-02); they now say only a guest surface and a wiki article remain. NodeConnect's transfer, UI and packaging were checked and are already complete (79 tests pass, the ZIP builds); the remaining items are the Raspberry Pi 5 measurement, a real two-machine run and the release, which waits for your say-so. Documentation only; no behaviour changed.

- **The startup registration ping now reports the real app version.** `galileo/registration.py` sent a fixed `"GA02.0"` handshake that never changed between releases; it is now `"GA" + galileo.__version__` (e.g. `GA0.9.05alpha`), so bumping the version in `galileo/__init__.py` updates the ping with nothing extra to remember. The server at `www.gordtulloch.com:5050` must accept this format (it is the same one-line, no-response TCP handshake). No UI/help/wiki change.

### Fixed

- **Code-quality CI.** Five `ruff` findings had failed the `static-analysis` job on every push, so the steps after it weren't running, and one of those would have failed too: `map_standard` in `galileo/adapters/indi/switch_map.py` was over the complexity limit. The findings are fixed, and that function is split into one method per part of the panel. An internal refactor with no visible effect.

- **Connect Link discovery on a Mac.** If mDNS can't bind every network interface ("address in use", seen on a Mac), Galileo now advertises on the default one rather than not at all, so apps and other nodes can still find it without typing its address. Computers where binding all of them works behave as before.

- **macOS: FITS files opened in GIMP instead of Tenmon.** A viewer set in Options > Library that was a `.app` bundle (a folder) could not be executed, so Galileo silently fell back to the system default for `.fits`, which was GIMP. New `galileo/ui/library/viewer.py` (used by Library > Images and Sessions) launches `.app` viewers with `open -a`, and with no viewer configured prefers an installed Tenmon over the system default. Windows/Linux behaviour is unchanged. Help updated.

- **What's Up Tonight's day/night band was centred on dawn instead of mid-night.** The band started at the *system clock's* local noon, so whenever the computer's timezone differed from the observatory's longitude (a Pi left on UTC, a laptop travelling) the dark period slid toward one end. It now runs from the site's own solar noon to the next, computed from the Observatory's longitude, so solar midnight is always mid-band; the hour labels are placed by time (even clock hours) since the window no longer starts on the hour. Hour labels are still in the system clock's time. No help/wiki change (behaviour now matches what they describe).

- **Star Atlas showed no stars on a fresh Linux install (catalogs listed, sky empty).** The star catalog (Yale Bright Star Catalogue, ~9,100 stars) was only ever downloaded from VizieR on first run; if that server was unreachable or slow the atlas fell back to ~60 named stars and never cached anything. A copy of the catalog now ships with the app (`galileo/planning/data/bright_star_catalog.json`, included in the PyInstaller/AppImage builds) and is used when there is no cache, so stars appear offline on every OS. VizieR is only a last resort. No UI/help/wiki change.

## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.05alpha | 2026-11-05 | [Changelog](docs/changelog/0.9.05alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.05alpha) |
| 0.9.04alpha | 2026-11-03 | [Changelog](docs/changelog/0.9.04alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.04alpha) |
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
