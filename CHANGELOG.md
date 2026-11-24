# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Fixed

- **Star Atlas Milky Way background (Mellinger survey) was never populated.** CDS's hosts (`alasky.cds.unistra.fr`, `alasky.u-strasbg.fr`) now answer 404 to every Mellinger tile, and the tile fetcher took the first 404 to mean "this tile doesn't exist" without asking the remaining mirrors, so the independent IAS Orsay mirror (which still serves the survey) was never reached and the sky stayed blank. A 404 now moves on to the next mirror, the tile is reported missing only if every mirror says so, and the mirror that answers is tried first from then on. The dead CDS mirrors are also removed from the list, leaving IAS Orsay as the only (and so primary) source. Internal fetch behaviour only; no new controls, so no help or wiki change. Test `TC-SKYMAP-100` added.

### Added

- Draft Project Scope Document for a planned **INDI Server plugin** (`docs/plugins/indi_server/PSD.md`): a first-party plugin that would let Linux and macOS users run and supervise a local `indiserver` with nothing preinstalled (bundled INDI, detect-and-adopt a running server on start-up and add or remove its drivers, choose drivers live through the server's FIFO, restart on failure, a lifetime option) from a panel on Equipment > Control Panel. Scope includes per-platform build scripts, run by hand on each platform, that build INDI and publish the bundles, stored on the project website's own server, to the website by rsync over SSH, with the Linux x86-64 build run on a local server and macOS limited to Apple silicon. The bundles track the latest stable INDI release. All scope questions in the PSD are now answered, pending sign-off. Documentation only: no code, SRS/SDD/RTM, help or wiki changes yet; those follow once the remaining scope questions in the PSD are agreed.

## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.09alpha | 2026-11-23 | [Changelog](docs/changelog/0.9.09alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.09alpha) |
| 0.9.08alpha | 2026-11-18 | [Changelog](docs/changelog/0.9.08alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.08alpha) |
| 0.9.07alpha | 2026-11-12 | [Changelog](docs/changelog/0.9.07alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.07alpha) |
| 0.9.06alpha | 2026-11-09 | [Changelog](docs/changelog/0.9.06alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.06alpha) |
| 0.9.05alpha | 2026-11-05 | [Changelog](docs/changelog/0.9.05alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.05alpha) |
| 0.9.04alpha | 2026-11-03 | [Changelog](docs/changelog/0.9.04alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.04alpha) |
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
