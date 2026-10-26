# Galileo

![Galileo logo](assets/images/logo.png)

![License: GPL v3](https://img.shields.io/badge/License-GPL--3.0-blue.svg)
![Status: Alpha](https://img.shields.io/badge/status-0.9.0%20alpha%20%E2%80%94%20pre--release-orange.svg)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

A cross-platform Python-based astrophotography imaging application for Windows, macOS, and Linux — built on [INDI](https://indilib.org/) and [ASCOM Alpaca](https://ascom-standards.org/AlpacaDeveloper/) Supports a mix of INDI and Alpaca devices on multiple piers per observatory, multiple optical tubes and cameras per mount.  

## Installation

**Prebuilt installers (recommended)** — one self-contained download per platform, no Python or Git needed. Get the file for your system from the [Releases page](https://github.com/gordtulloch/Galileo/releases):

| System | File |
|---|---|
| Windows 10/11 x64 | `Galileo-Setup-<version>-win-x64.exe` |
| macOS, Apple Silicon | `Galileo-<version>-macos-arm64.dmg` |
| macOS, Intel | `Galileo-<version>-macos-x86_64.dmg` |
| Linux x86_64 | `Galileo-<version>-linux-x86_64.AppImage` |
| Raspberry Pi 5 / 64-bit ARM Linux | `Galileo-<version>-linux-aarch64.AppImage` |

**Install from source** — a one-file bootstrap script that clones the repo, builds a virtual environment and auto-updates on every launch: [`Install-Galileo-Windows.bat`](Install-Galileo-Windows.bat), [`Install-Galileo-MacOS.sh`](Install-Galileo-MacOS.sh) or [`Install-Galileo-Linux.sh`](Install-Galileo-Linux.sh). Details in [`install/README.md`](install/README.md).

**Developers**: `pip install -e ".[test,dev]"` (Python 3.11+), then `galileo`. The installers are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) from [`packaging/`](packaging/) when a `v*` tag is pushed.

Step-by-step instructions, first-run security prompts (macOS Gatekeeper, Windows SmartScreen) and uninstalling are in the wiki's [Getting Started Guide](https://github.com/gordtulloch/Galileo/wiki/01.-Getting-Started-Guide#install-galileo).

## Why Galileo

Two things motivate this project:

1. **Non-Windows imaging software has a UI/UX gap.** Existing cross-platform options (KStars/EKOS chief among them) have interfaces that have aged over a decade or more of incremental growth. Galileo aims to bring a modern, guided imaging workflow to any platform from Windows to Linux to Mac to Raspberry Pi, using INDI and ASCOM Alpaca so it isn't tied to any one platform's device-driver ecosystem.
2. **Consolidating prior work into one cohesive application.** Galileo's author has built several separate astronomy tools over time — an image manager, a variable-star planner, observatory-automation scripts, an all-sky cloud-detection classifier. Bringing that scattered work together into a single application, rather than maintaining it as several disconnected tools, is a primary goal of this project, not an afterthought.

## Status

**Alpha — current pre-release: [v0.9.02alpha](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.02alpha).** Galileo is a runnable PySide6 desktop application, but some screens are still placeholders. Installers are published as GitHub pre-releases. Please try it and report problems, but **do not use it for production imaging yet**.

### What works today

| Area | What you can do |
|---|---|
| **Equipment** | Connect cameras, mounts, filter wheels, focusers, rotators, switches, flat panels, weather, domes and safety monitors over INDI or Alpaca. |
| **Observatories & Piers** | Several Piers per Observatory, each running its own capture, focus, solve and sessions at the same time, under shared weather and safety monitoring. |
| **Imaging** | Live preview with histogram and statistics, single and multi-frame capture, live stacking, mosaics, and Flats and Darks assistants. Frames are saved as FITS and filed into the Library. |
| **Guiding** | Control and monitor PHD2. |
| **Focus** | Autofocus with a live V-curve, and manual focus. |
| **Solve** | Plate solving (ASTAP, astrometry.net, tetra3), slew-and-centre, and polar alignment. |
| **Star Atlas** | Planetarium with deep-sky catalogs, planets, comets, asteroids, satellites, constellations, horizon obstructions and live telescope position. |
| **Planning** | What's Up Tonight recommendations, target search, block-based Sessions, and a multi-night Schedule with Autoschedule and weather-gated execution. |
| **Framing Assistant** | Field-of-view, rotation and mosaic planning on a survey image. |
| **Library** | Built-in AstroFiler: image catalog, calibration and master frames, deduplication, cloud backup and command-line tools. |
| **Dashboard** | Per-Pier activity timeline. |
| **Plugins** | Install from a ZIP or the marketplace: VSTarget (variable stars), Kasa Switch, Generic Relay, AllSkyCam. |
| **Safety & diagnostics** | Dome slaving, crash/hang watchdog, crash reporting and logging. |
| **Options** | Settings for every area above, stored in the shared database. |

Every control has built-in help, and the [wiki](https://github.com/gordtulloch/Galileo/wiki) walks through the workflow.

### Not implemented yet

- In-place plugin updates (remove and reinstall instead)

### Project health

- **Design docs**: Project Scope Document, Software Requirements Specification (282 requirements), Software Design Description, and a Requirements Traceability Matrix.
- **Tests**: one file per SRS domain under `tests/`, run in CI with `pytest -m "not soak and not hardware and not integration and not perf"`. As of 2026-10-10 a local fast run had one known failure (`test_tc_help_060`, caused by the VSTarget plugin in the developer's venv).


## Support

Need help or want to chat with other users? Join the [Galileo Discord](https://discord.gg/cnTuRwejd). Bugs and feature requests go to [GitHub Issues](https://github.com/gordtulloch/Galileo/issues).

## Getting Started

Please see the Wiki for the Getting Started Guide.

## Documentation

| Document | Contents |
|---|---|
| [`docs/PSD.md`](docs/PSD.md) — Project Scope Document | Goals, non-goals, functional/non-functional requirement domains, constraints, risks |
| [`docs/SRS.md`](docs/SRS.md) — Software Requirements Specification | Numbered, testable requirements decomposed from the PSD |
| [`docs/SDD.md`](docs/SDD.md) — Software Design Description | Architecture, module-by-module design, and the design decisions (ADRs) behind it |
| [`docs/RTM.md`](docs/RTM.md) — Requirements Traceability Matrix | Every SRS requirement mapped to its SDD component and a reserved test-case ID; generated from the SRS/SDD text, 100% coverage |

## Planned Capabilities

- A multi-night **autoscheduler** with altitude, Moon, twilight and horizon constraints and weather-gated execution
- Further safety-monitor tiers (software-computed monitors such as an ML cloud classifier connect as ordinary INDI/Alpaca Safety Monitor devices)

See the [PSD](docs/PSD.md) for the full requirement list and what is out of scope for v1.


## Built On

Galileo consolidates and builds on several of the author's existing projects:

- [AstroFiler](https://github.com/gordtulloch/astrofiler-gui) — image cataloging and calibration processing (merged in full)
- [VSTarget](https://github.com/gordtulloch/VSTarget) — AAVSO variable-star planning and photometry (merged in full)
- [Obsy](https://github.com/gordtulloch/obsy) — target-visibility and sky-survey-thumbnail logic (retired as an app, its GPL-3.0 code ported directly into the Sky Atlas/Framing Assistant)
- [AstroLlama](https://github.com/gordtulloch/AstroLlama) and [MCP](https://github.com/gordtulloch/MCP) — selectively harvested for specific device-abstraction and safety-sensor functionality

See the PSD's Background section for the full picture of what's merged, harvested, or kept as reference only, and why.

## Tech Stack

Python 3 with [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python), chosen for native rendering performance on all platforms including ARM SBCs and direct reuse of the existing Python astronomy ecosystem (`astropy`, `peewee`, `zeroconf`). See [SDD Section 2.1](docs/SDD.md) for the full rationale.

**On the GIL:** people considering Python for a desktop imaging app reasonably ask about the Global Interpreter Lock. It matters here, and Galileo handles it based on measurements rather than assumptions. Pure-`numpy` work (stretching, debayering, histograms, FFTs) releases the GIL, so running it in a background thread keeps the UI responsive. SEP star detection and astroalign registration don't release it: profiled on a 26 MP frame, they froze the event loop for 1.7–2.9 s even from a background thread. That work goes to a `ProcessPoolExecutor` (`galileo.core.compute`), which cuts the stall to under 80 ms. See [SDD §2.1/§2.3](docs/SDD.md) for the details.

**On moving to Python 3.14:** The latest version of Python has a lot of performance improvements including free-threading which eliminates the GIL bit at a general 10-15% performance reduction so the author has decided to hold off on moving from 3.11 for the time being, particularly to ensure that libraries are properly implemented for the new features (otherwise the whole program reverts to GIL). 
## Reference Test Environment

Galileo's design is validated against the author's own physical multi-Pier Observatory: a roll-off-roof shed ([indi-rolloffino](https://github.com/wotalota/indi-rolloffino)), an INDI weather station ([indi-argentweather](https://github.com/gordtulloch/indi-argentweather)) and rain monitor ([indi-hydreon](https://github.com/gordtulloch/indi-hydreon)), and three independent Piers — a Seestar S30 and a Seestar S30 Pro (both connected via ASCOM Alpaca) and a 62 mm refractor on an OnStep mount (connected via INDI). See [PSD Section 6.8](docs/PSD.md) for details.

## License

Copyright (C) 2025-2026 Gord Tulloch. Licensed under [GPL-3.0-or-later](LICENSE). Every source file carries an `SPDX-License-Identifier` and copyright header.

## Contributing

Contributions are welcome. All contributors must agree to the Contributor License Agreement (CLA) in [CONTRIBUTING.md](CONTRIBUTING.md), which also covers the development setup, test conventions and changelog requirements.

## Author

[Gord Tulloch](https://github.com/gordtulloch)

## Screenshots

### Equipment

![Cameras](assets/screenshots/Cameras.png)

![Mount](assets/screenshots/mount.png)

![Filter wheel](assets/screenshots/filterwheel.png)

![Focuser](assets/screenshots/focuser.png)

![Rotator](assets/screenshots/rotater.png)

![Optics](assets/screenshots/optics.png)

### Imaging

![Imaging](assets/screenshots/imaging.png)

![Imaging (portrait layout)](assets/screenshots/imaging%20portrait.png)

![Guiding](assets/screenshots/guiding.png)

![Focus](assets/screenshots/focus.png)

![Plate solving](assets/screenshots/solve.png)

### Planning and Library

![Horizon](assets/screenshots/Horizon.png)

![Library options](assets/screenshots/LibraryOptions.png)
