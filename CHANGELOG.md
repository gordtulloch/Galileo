# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml` (the registration ping follows `__version__` automatically), write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Added

- **Plugins can now add plate solvers (`PLUG-220`).** A plugin calls `ctx.register_solver_backend(backend)` with a `galileo.platesolve.SolverBackend` (a `key`, a `label`, `is_available()`, `missing_message()` and an async `solve(fits_path, hint, params)`). The solver then appears in the **Options > Solve > Solver** list and as an extra button under the Solve screen's **Solver Mode**, and `PlateSolver` runs it like the built-in ones, including the "plugin disabled" and "setup missing" messages. A plugin cannot take the name of ASTAP, astrometry.net, nova or tetra3 or of another plugin's solver; a disabled plugin's solver is hidden, an unloaded plugin's is dropped, and an exception inside a plugin's solver becomes a failed solve instead of an error. Nothing about the built-in solvers changed, and no database migration is needed (the saved choice was already free text). First user: the new **Skyshot Solver** plugin (`../Galileo-Plugins/skyshot_solver`, requirements `SKY-010`…`SKY-070` in `docs/plugins/skyshot_solver/`), which adds the Skyshot blind solver and downloads its star index from its own page under Options. The plugin can also download a prebuilt Skyshot program for Windows, Linux (Intel/AMD and ARM, including Raspberry Pi 5) and macOS on Apple silicon, built by a GitHub Actions workflow in the plugins repo from one pinned upstream commit and trusted only through checksums pinned in the plugin (`SKY-080`…`SKY-100`); until that workflow has been run and published, Skyshot has to be built from source. So far it has been checked against a real Skyshot build on Windows with Skyshot's own synthetic demo, not yet on real sky or on the other platforms. Installing it is via Options > Plugins from its zip.
- **Skyshot credited in `THIRD_PARTY_NOTICES.md`.** New section for Skyshot Solver (Copyright 2026 Adam Jesionkiewicz, Apache-2.0): it is not bundled, the plugin downloads unmodified builds that keep Skyshot's LICENSE, NOTICE and third-party notices, and it runs as a separate program, so there is no combining with Galileo's GPL-3.0 code. It also records that the plugin's index installer follows upstream's installer rules without copying its code, and that **Skyshot's star indexes are not under Apache-2.0**: upstream describes them as intended for non-commercial use, derived from the ASTAP D80 catalogue (ESA Gaia DR3), so the plugin never redistributes them, warns before downloading, keeps their `LICENSE-DATA.txt`, and refuses an index without one. Anyone using Galileo commercially should check those data terms with Skyshot's author before relying on the index.

### Fixed

- **A phone could not connect when the Master picked the wrong network adapter (`LINK-010`).** With a VPN or virtual adapters installed, "Automatic" chose an address that was not on the LAN (for example 172.18.x.x instead of the Wi-Fi 192.168.x.x), so the Connect Link listened and advertised somewhere the phone could not reach. The `bind_host` setting existed but had no control. **Options > Connect Link** now has a **Listen on** list of this computer's addresses (plus Automatic, or type one); `0.0.0.0` is still refused. The Automatic choice itself is unchanged. **Checked:** imports only; **not run:** the page or a phone connection. Inline help updated; no migration.
- **Moving blocks on the Sessions screen could crash the app or freeze the window on macOS (`SES`).** On macOS Qt delivers the drop *inside* the native drag session, before `QDrag.exec()` has returned, so the deferred "refresh" (a zero-delay timer) could still run mid-drag and rebuild every session card, destroying the widget the drag came from. Everything a drop triggers (re-render, the "Can't add block" warning, drag-out-to-delete) now waits until the drag has actually ended, for drags from both the palette and a block list. Not a PySide6 defect as such: it was a lifetime race that other platforms' drag loops happened not to expose. **Checked:** imports and the existing Sessions tests; **not run:** the drag itself on a Mac. No visible controls changed, so no help or wiki change.

## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.08alpha | 2026-11-18 | [Changelog](docs/changelog/0.9.08alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.08alpha) |
| 0.9.07alpha | 2026-11-12 | [Changelog](docs/changelog/0.9.07alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.07alpha) |
| 0.9.06alpha | 2026-11-09 | [Changelog](docs/changelog/0.9.06alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.06alpha) |
| 0.9.05alpha | 2026-11-05 | [Changelog](docs/changelog/0.9.05alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.05alpha) |
| 0.9.04alpha | 2026-11-03 | [Changelog](docs/changelog/0.9.04alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.04alpha) |
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
