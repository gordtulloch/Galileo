# Skyshot Solver Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — Skyshot Solver Plugin |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-11-19 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose

This document scopes the **Skyshot Solver plugin**: a first-party, optional Galileo plugin that adds [Skyshot](https://github.com/ashtree74/skyshot-solver), a fast *blind* plate solver, beside ASTAP, astrometry.net and tetra3, and lets the user download Skyshot's star-pattern indexes from the plugin's own Options page.

## 2. Background and Motivation

Galileo's built-in solvers are fast when told roughly where the telescope points. Skyshot solves with no position, scale or rotation hint, so it also recovers from a badly wrong mount position. It is a young project (an unreleased "development snapshot" at engine 0.1.0), which is why it is a plugin: it can be installed, updated, disabled or dropped without touching core, and its instability cannot affect the built-in solvers. Core's only change is a general solver extension point (`PLUG-220`) that any future solver plugin can use.

## 3. Goals

| # | Goal |
|---|---|
| G1 | Offer Skyshot as a selectable solver under Options > Solve and on the Solve screen once the plugin is installed and enabled (`SKY-010`). |
| G2 | Report the position of the image centre as every other solver does (`SKY-020`). |
| G3 | Download and install Skyshot's star indexes from Options > Skyshot, verified against the publisher's checksums, never overwriting an installed index (`SKY-030`–`SKY-050`). |
| G4 | Keep all configuration in Galileo's database (`SKY-070`). |
| G5 | Download a prebuilt Skyshot program for the user's platform, trusted only through checksums pinned inside the plugin, built by CI from a pinned upstream commit with Skyshot's licences and notices kept (`SKY-080`–`SKY-100`). |

## 4. Non-Goals

- **The plugin does not contain the Skyshot program.** Upstream publishes no binaries, so Galileo's own CI builds unmodified Skyshot from one pinned upstream commit for Windows x64, Linux x64, Linux ARM64 (Raspberry Pi 5) and macOS Apple silicon (`SKY-100`), and the plugin downloads the one for the user's computer (`SKY-080`). A computer with no published build (for example an Intel Mac) builds Skyshot itself (`cargo build --release --locked`) and points the plugin at it.
- **No code signing or notarization.** The builds are unsigned, as upstream's are; the plugin downloads them itself, so no browser quarantine flag is involved, and it says they are unsigned.
- **No use of a position hint.** Skyshot is blind; Options > Solve's search radius and field-of-view hint do not apply to it.
- **No index building.** Only the publisher's prebuilt indexes are downloaded.
- **No dependency on Skyshot's JSON report.** Its layout is not yet documented upstream, so a solution is read from the WCS file Skyshot writes; the JSON is consulted only for a failure reason.

## 5. Dependencies on Galileo Core

| Core capability | Core requirement | Use |
|---|---|---|
| Plugin loading, enable/disable, removal | `PLUG-010`–`PLUG-060`, `PLUG-120` | Standard |
| Plugin Options page | `PLUG-170` | Options > Skyshot |
| Plugin settings in the database | `PLUG-150` | All configuration |
| Solver backend registration | `PLUG-220` | `SkyshotBackend` |
| Plate-solve result semantics | `PLT-010`–`PLT-060` | `SolveResult` in J2000, image-centre referenced |

## 6. Functional Requirement Domains

| ID Prefix | Domain | Priority |
|---|---|---|
| `SKY` | Skyshot solver backend, index download, Options page | P2 |

## 7. Risks

| Risk | Impact | Notes |
|---|---|---|
| Upstream is pre-release; the CLI, WCS output or index format may change | High | The plugin pins the data release (`2026.10.17.2`) and engine (`0.1.0`) it was written against and refuses data for other engines. Solutions come from the WCS file, not the undocumented JSON. |
| Only verified against Skyshot's synthetic demo, on Windows | Medium | A FITS frame rendered from the demo star list solves to the demo's known position and scale with a real Windows build (opt-in test, `SKYSHOT_REAL_DIR`). Not yet run on real sky (needs the 0.84 GB index and a real frame), nor on Linux, Linux ARM or macOS. Upstream itself has real-sky qualification only for macOS ARM64. |
| Redistributing a third party's binaries | Medium | Apache-2.0 allows it provided LICENSE, NOTICE and third-party notices travel with the program, which upstream's packager bundles and the plugin keeps. Upstream's release notes treat publishing prebuilt binaries as a decision still to be made by its author, so tell the author before the first release. |
| Star-index data has terms separate from the Apache-2.0 code | Medium | Upstream describes the indexes as non-commercial-intended, derived from ASTAP D80 / Gaia DR3, with no redistribution grant claimed, and records the Gaia and D80 terms as not fully confirmed. The plugin never redistributes them, tells the user before downloading, and keeps their licence files (`SKY-110`). Galileo is not itself non-commercial, so a user who needs the index for commercial work must settle those terms with its author. |\n| The downloaded program is executable code | Medium | The archive's SHA-256 is pinned in the plugin (a tampered release page cannot change it); only GitHub release URLs are accepted; the archive is unpacked only if it is plain files under one folder; the program must start before it is kept. |
| The release manifest is fetched from GitHub and archive hashes come from it | Medium | HTTPS only; archives are checked against the manifest's SHA-256 and `bundle.json` against `manifest_sha256`. A hash proves integrity, not origin, as upstream itself notes. |
| Large downloads (0.84 GB Full, 4.1 GB Deep) | Low | Size and disk space are confirmed before download; downloads are resumable and cancellable. |

## 8. References

- Skyshot: https://github.com/ashtree74/skyshot-solver (Apache-2.0); data downloads https://skyshot.app/downloads/
- Build workflow: `Galileo-Plugins/.github/workflows/skyshot-engine.yml`
- [Galileo Core PSD](../../PSD.md)
