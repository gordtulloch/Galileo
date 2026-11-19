# Skyshot Solver Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — Skyshot Solver Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-11-19 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |

---

## 1. Scope

One package, `skyshot_solver` (source in [Galileo-Plugins](https://github.com/gordtulloch/Galileo-Plugins)), attached to core only through `PluginContext.register_solver_backend` (`PLUG-220`), `PluginBase.build_options_page` (`PLUG-170`) and plugin settings (`PLUG-150`).

## 2. Modules

| Module | Responsibility |
|---|---|
| `__init__` | `SkyshotSolverPlugin`: registers `SkyshotBackend`; builds the Options page. |
| `backend` | `SkyshotBackend(SolverBackend)`: finds the program (configured path, downloaded program, `PATH`, `~/.cargo/bin`), runs `skyshot solve <fits> --index <dir> --wcs <tmp> --deadline-ms <n> [--mode <m>]`, reads the WCS (`result_from_wcs`), and maps exit codes (0 solved, 1 unsolved, 2 error). `inspect_index` runs `skyshot inspect`. |
| `data` | Release manifest parsing and validation, resumable verified download, safe flat-tar unpack, atomic per-slot install. No Qt. |
| `engine` | The prebuilt program: platform to build target (`current_target`), the pinned build (`build_for`), verified download (`download_engine`, using `data.download_file`), safe `.zip`/`.tar.gz` unpack (`unpack_engine`), start-up check (`verify_runs`). No Qt. |
| `engine_builds` | **Generated** by the CI workflow: upstream commit, release URL and the SHA-256 of each archive. Empty until a build is published. |
| `credits` | The credit and licence wording (author, Apache-2.0, non-endorsement, separate index-data terms, catalogue sources) used by the Options page, both download dialogs and the help, so they cannot disagree (`SKY-110`). |
| `settings` | Typed, clamped view over the plugin's database settings. |
| `ui` | `SettingsPage`: status, paths, mode, limit, download/cancel/check; network work runs on worker threads that report through Qt signals. |

## 3. Design decisions

- **Result from the WCS, not the JSON (`SKY-010`, `SKY-020`).** Skyshot's WCS output is a documented FITS header; its JSON `solution` fields are not documented. The image-centre position is computed with `astropy.wcs`, using the frame's own `NAXIS` (or `ZNAXIS` for tile-compressed files).
- **Blind solver, hint ignored.** `SolverBackend.solve` receives the hint and parameters; this backend deliberately ignores them (stated in the help).
- **Data install follows upstream's rules without importing upstream code (`SKY-040`).** Upstream's `install_data.py` verifies bundles with its own modules; the plugin re-implements the parts that matter for safety (archive checksum, flat-layout check, `bundle.json` checksum) and leaves bundle verification to the program (*Check index* runs `skyshot inspect`).
- **Pinned release (`SKY-030`).** `RELEASE_ID` and `ENGINE_VERSION` are constants; newer data needs a plugin update. Slots (`index`, `index-deep`, …) come from the manifest's presets. Indexes live under `<data folder>/<release id>/<slot>`; an installed slot is skipped, so *Full* and later *Deep* share one folder, as Skyshot expects (`--index` plus a sibling `index-deep`).
- **Pinned hashes live in the plugin (`SKY-080`).** `engine_builds.BUILDS` is committed with the plugin, so trust comes from the plugin zip a user installed, not from the release page. Publishing is therefore two steps: run the workflow with *publish* ticked, then commit the `engine_builds.py` it attaches to the release and release a new plugin version. A plugin version with an empty list simply greys the button out.
- **Build provenance (`SKY-100`).** `.github/workflows/skyshot-engine.yml` checks out a full-SHA upstream commit, installs upstream's Rust 1.95.0 toolchain (with `rust-docs`, which the packager needs for Rust's licences), runs `cargo test`, builds, runs the synthetic demo, packages with upstream's `tools/package_cli.py`, then unpacks and smoke-solves the result with `tools/check_candidate.py`. Build jobs have a read-only token; only the release job can write, and it runs none of upstream's code. Targets: `x86_64-pc-windows-msvc`, `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu` (Raspberry Pi 5-class) and `aarch64-apple-darwin`.
- **Lookup order (`SKY-090`).** `backend.find_executable(configured, data_root)`: a path the user set wins and is never silently replaced; else the downloaded program; else `PATH`; else `~/.cargo/bin`.
- **Licensing (`SKY-110`).** The program is Apache-2.0 (Copyright 2026 Adam Jesionkiewicz). It is not linked into Galileo (a separate process), the plugin ships none of its code, and the CI builds are unmodified and keep upstream's LICENSE, NOTICE and `third_party/`, so Apache-2.0 section 4's redistribution conditions are met by the archive itself, and the plugin's GPL-3.0-or-later code is not combined with it. `data.py` is an independent reimplementation of upstream's installer rules and says so in its docstring (Galileo's convention for derived logic, as for xisfits). The **index data is not under Apache-2.0**: upstream records it as non-commercial-intended, derived from ASTAP D80 / Gaia DR3, with no redistribution grant claimed. The plugin therefore never mirrors it (the user downloads from the publisher's host), tells the user before downloading, keeps `LICENSE-DATA.txt` and `PROVENANCE.json` with it, and refuses an archive without a licence file. The Gaia credit text is the standard "ESA/Gaia/DPAC" form with a link to the release's own credit page, because upstream itself records the Gaia terms as not yet confirmed.
- **Configuration (`SKY-070`).** Keys under `plugin.SkyshotSolverPlugin`: `executable`, `data_root`, `index_path`, `mode`, `deadline_s`.

Satisfies: `SKY-010`–`SKY-110`.
