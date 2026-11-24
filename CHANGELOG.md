# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Fixed

- **Star Atlas Milky Way background (Mellinger survey) was never populated.** CDS's hosts (`alasky.cds.unistra.fr`, `alasky.u-strasbg.fr`) now answer 404 to every Mellinger tile, and the tile fetcher took the first 404 to mean "this tile doesn't exist" without asking the remaining mirrors, so the independent IAS Orsay mirror (which still serves the survey) was never reached and the sky stayed blank. A 404 now moves on to the next mirror, the tile is reported missing only if every mirror says so, and the mirror that answers is tried first from then on. The dead CDS mirrors are also removed from the list, leaving IAS Orsay as the only (and so primary) source. Internal fetch behaviour only; no new controls, so no help or wiki change. Test `TC-SKYMAP-100` added.

- **Skyshot data download no longer fails with `SSL_CERTIFICATE_VERIFY_FAILED` ("unable to get issuer certificate").** Python on Windows checks HTTPS certificates against the OS trust store, which can lack an intermediate certificate GitHub's download hosts leave out of their chain, so retrying the same way never helped. After the first certificate failure the Skyshot plugin now retries with a verifying context built from the bundled certifi CA list (`galileo.net.certifi_ssl_context`, and an optional `context` argument on `urlopen_http`). Certificate checking stays on. Needs the Skyshot plugin reinstalled from its zip and Galileo restarted. Internal behaviour only; no new controls, so no help or wiki change.

### Changed

- The Solve screen now remembers the Solver Mode you last picked, per Pier. Before, a choice made on the screen was lost on restart and only Options > Solve was saved. The choice is stored as the Pier's solver backend, so everything else that solves with the saved solver (the phone via MobileConnect, session Plate Solve blocks, Imaging, Star Atlas) uses it as well. No schema change.
- **Plugin settings pages moved off the Options menu onto the Plugins screen.** Each plugin that has settings used to add its own item to the Options side menu, which was filling up. Those items are gone; instead the plugin's tile under Options > Plugins > Installed has a gear (⚙) button that opens its settings page. The pages themselves, and their help, are unchanged. Inline help for Plugins gains a "Settings" entry (the gear); SRS `PLUG-170` and SDD §4.20 describe the gear, and the wiki articles for NodeConnect, WebConnect, AllSkyCam, Skyshot, Plate Solving and the Plugin Developers Guide now say "the ⚙ on its tile in Options > Plugins" instead of "Options > <plugin>".
- **Exposure notices now show progress, and a finished set is announced.** When a series of more than one frame is running (Imaging captures, darks, mosaics), each start notice reads "Exposure 4 of 99 starting: 30 s Light" instead of just the exposure length, and an "Exposures complete" notice is posted when every frame in the set has been taken (not when the set was stopped early or failed). Single-frame exposures are unchanged. The progress counter lives in `galileo.notices` (`set_series_progress` / `clear_series_progress`) and is set by `ImagingService.capture_series` and the mosaic series. No new controls, so no inline-help or wiki change.
- **Skyshot plugin: no more asking for the program or index location (`SKY-120`).** The plugin's design documents (`docs/plugins/skyshot_solver/`) now record that both are downloaded to a fixed `skyshot` folder inside Galileo's data folder, with a `program` folder there for a hand-built Skyshot, instead of the user typing or browsing to paths. Plugin change only (Galileo-Plugins, `skyshot_solver` 0.1.1); no Galileo code changed, and nothing in Galileo's own screens, help or wiki articles (other than the Skyshot article) changes.
- **Skyshot plugin design record brought up to date (`SKY-100`).** `docs/plugins/skyshot_solver/RTM.md` now records that the `Build Skyshot engine` workflow has been run (run 45310212150, upstream commit `76f0181`): the Windows x64, Linux x64, Linux ARM64 and macOS Apple-silicon builds passed upstream's tests and packaged smoke solve and are published as release `skyshot-engine-v0.1.0-76f0181`, pinned in plugin 0.1.1, and that only the Windows build has so far been downloaded and run by the plugin. Documentation only; no Galileo code changed.

### Added

- **Plugin icons (`PLUG-210`).** A plugin's tile under Options > Plugins > Installed now shows an icon instead of a star. A plugin author adds `icon.svg` or `icon.png` at the root of the plugin ZIP; first-party plugins always show the Galileo icon. Marketplace tiles of first-party plugins without a server icon use it too. Plugins with no icon are unchanged. No new controls, so no inline-help change; the Plugin Developers Guide documents the file.
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
