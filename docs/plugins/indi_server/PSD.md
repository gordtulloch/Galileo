# INDI Server Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — INDI Server Plugin (bundle, run and manage a local `indiserver` on Linux and macOS) |
| **Document** | PSD (Project Scope Document), v0.9, draft |
| **Status** | Draft — all scope questions answered; awaiting sign-off |
| **Date** | 2026-11-23 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS, SDD, RTM — **not yet written**; per the docs-chain rule they follow once this scope is agreed |

**Revision history.** v0.1 (2026-11-23) scoped a supervisor that detected an existing INDI install, with bundled binaries as a later phase. v0.2 applies the reviewer's decisions: **nothing need be preinstalled** (bundled INDI is in v1), server lifetime is a configuration option, a running server is detected and adopted on start-up, the page lives on Equipment > Control Panel, macOS detection is Homebrew only, and the reconnect gap stays out of scope. v0.3 settles Q3a: on an **adopted** server the plugin may **add and remove drivers** (through the server's FIFO, where it can find one), though it still never stops, restarts or reconfigures the adopted server itself. v0.4 brings the **build scripts** into scope: one script per platform, run by hand on a machine of that platform (no CI), that builds INDI, packages it and populates the project website so the plugin can fetch it. v0.5 settles where the binaries live: **on the project website's own server**, not on GitHub, since space there costs nothing. v0.6 settles the upload route: the web server is an Ubuntu server with full command-line access, so the publish step uses **rsync over SSH (or sftp)**. v0.7 settles the Linux x86-64 build machine: a **local server** (not the web server). v0.8 settles Q10–Q13 and Q17: an existing INDI install is used when found, the driver set starts small, an unsupported platform gets discovery-only mode, macOS is Apple silicon only, and bundles live under `/var/www/galileo/indi/`. v0.9 settles Q15 and Q16: the builds use machines in the local development lab, and the bundles **track the latest stable INDI release** rather than a pinned one.

---

## 1. Purpose of This Document

This document defines the scope of the **INDI Server plugin** (working name `indi_server`, requirement prefix `ISRV`): a first-party Galileo plugin that lets a Linux or macOS user run an `indiserver` **on the same computer as Galileo** with nothing installed beforehand. The plugin brings its own INDI server and drivers, and lets the user choose which drivers to load, then starts, stops and watches the server — without a terminal or another application.

It follows the same PSD → SRS → SDD → RTM structure as [the core chain](../../PSD.md) and the sibling plugin chains. It intentionally stays above implementation detail; the remaining open scope decisions are collected in Section 10.

## 2. Background and Motivation

Galileo reaches every INDI device through its own native protocol client ([`galileo.adapters.indi_client`](../../../galileo/adapters/indi_client.py)) talking TCP to an `indiserver`. Core requirement `EXT-020` makes the server the *only* route to INDI drivers, and `EXT-030` allows it to be local or networked. Core has no feature for **providing or starting** that server. Today a user who plugs a camera into the laptop running Galileo must install INDI, work out the driver names, and start `indiserver` by hand; Galileo's Equipment > Control Panel page and the per-category device pickers then connect to `localhost:7624`.

That is a fair deal for the Raspberry Pi / StellarMate / Astroberry user, whose server is already running on the telescope. It is a poor one for the single-machine user — a laptop at the telescope, or a Linux or Mac mini in an observatory — who is the person this plugin serves, and who is least likely to have INDI available (macOS has no system package manager; Homebrew is optional).

**Why a plugin and not core.** The feature is useful only on two operating systems, carries a large external code base (INDI) with platform-specific binaries, and has its own release cadence. Core `PLUG-060` already requires that an enabled plugin be indistinguishable from a built-in capability and that a disabled one be fully inert; this is a natural fit, and it keeps INDI process management out of the hexagonal domain core. Core's INDI adapters need **no change**: they already default to `localhost:7624`.

### 2.1 Design observations

Three behaviours distinguish a desktop-friendly server manager from a service-style one, and shape the scope:

- **The plugin owns the process, as a child of Galileo.** An interactive desktop application, and macOS in particular, is not served by writing systemd or launchd units. The plugin spawns and supervises the server itself and can also *adopt* a server something else started (G3).
- **Drivers can be added and removed while the server runs.** `indiserver -f <fifo>` accepts `start <driver>` / `stop <driver>` lines, so choosing a new camera does not restart the server or drop the other devices. A fixed driver list that needs a restart on every change is the alternative this plugin avoids.
- **A crashed server is restarted, within limits.** A service with no restart policy stays down after a fault; an unbounded one can loop forever. The plugin restarts with a bounded back-off and then stops and tells the user.

## 3. Vision Statement

> A Galileo user on Linux or macOS with a camera and mount plugged into their own computer installs one plugin, opens Equipment > Control Panel, ticks the devices they own, and presses Start. Galileo has the INDI server and drivers it needs, runs the server, shows that it is healthy, and the user's normal camera, mount and focuser pickers see the devices on `localhost` — with no terminal, nothing to install first, and the same experience on both operating systems.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver the feature as a first-party plugin, distributed as a downloadable ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled and disabled (`PLUG-060`) and not bundled in the Galileo installer |
| G2 | **Work with nothing preinstalled.** The plugin provides a prebuilt `indiserver` and a set of drivers for each supported platform (Section 9), delivered through the plugin's private dependency mechanism (`PLUG-200`), so a clean machine needs no INDI install, package manager or compiler |
| G3 | **Detect and adopt on start-up.** When Galileo starts (and on demand), check whether a server already answers on the configured port. If so, adopt it and say so — Galileo does not start a second one — and, where the server has a control FIFO the plugin can find and write to, manage its drivers like a server the plugin started (G4); if not, start one when the user has chosen auto-start or presses Start |
| G4 | Let the user choose drivers from a list built from INDI's own driver description files, **add and remove drivers while the server runs** (via `indiserver`'s FIFO) — on a server the plugin started or one it adopted — and remember the choice in Galileo's database |
| G5 | **Supervise** the server it started: show state and log output, restart it after an unexpected exit with bounded back-off, and stop it cleanly when the plugin is disabled or removed |
| G6 | Make first run safe and checkable: offer the INDI simulator drivers so a user can confirm the whole chain before plugging in hardware, and on Linux detect missing device-access group membership and show the exact command to fix it |
| G7 | Make the server's lifetime a **configuration option** (Options page, stored in the database): **stop with Galileo** or **leave running** (detached) so a crash of Galileo does not interrupt a mount or exposure in progress. The next start-up adopts a server left running (G3) |
| G8 | Behave identically on Linux and macOS (including Raspberry Pi 5-class ARM Linux and Apple silicon) from the user's point of view; platform differences are limited to where binaries live, signing, and permission advice |
| G9 | Use only Galileo's existing extension points and require **no change to core's INDI adapters** |
| G11 | Provide **build scripts, one per platform, run on a machine of that platform**, that compile the latest stable INDI release (Q16), package the result as the platform's bundle, record exactly what went into it, and **populate the project website** with the bundle and the index entry the plugin uses to find it |
| G10 | Prefer an INDI install the user already has when one is found (a complete, user-managed driver set), and fall back to the bundled one; the user can override the choice. On macOS the only system source detected is **Homebrew** |

## 5. Scope

### 5.1 In scope (v1)

| # | Item |
|---|---|
| S1 | **Bundled INDI**: prebuilt `indiserver` and a curated driver set for each supported platform, delivered via `PLUG-200` (G2) |
| S2 | **Discovery** of an existing INDI install — on `PATH` and standard Linux locations, and Homebrew on macOS — and a version report; the bundled copy is used when none is found or the user chooses it (G10) |
| S3 | **Detect/adopt/start**: probe the port on start-up, adopt a running server, otherwise spawn `indiserver` as a child process with a configured port, a FIFO control channel and captured output (G3–G5) |
| S4 | **Driver management** from INDI's driver description XML, live add/remove, persisted selection (G4); on an adopted server, the control FIFO is located from the server process's own command line and used if the plugin may write to it (A6) |
| S5 | **Supervision** with bounded restart and clean shutdown (G5, G7) |
| S6 | **A panel on Equipment > Control Panel** (state, Start/Stop, driver list, log) and an **Options page** (port, auto-start, lifetime, binary source and location override) |
| S7 | **First-run helpers**: simulator drivers, Linux group-membership check (G6) |
| S8 | **Per-platform build and publish scripts** (G11), kept with the plugin in the Galileo Plugins repository and run by the owner by hand on each platform (Linux x86-64, Linux aarch64, macOS arm64). Each script: (a) checks its prerequisites and resolves the latest stable INDI release once (or takes a version given on the command line, so every platform in one plugin release is built from the same version, R19), fetches that source and its library dependencies; (b) builds `indiserver` and the curated drivers (Q11); (c) collects the shared libraries they need and, on macOS, signs every executable (R11); (d) packages a platform-tagged wheel; (e) runs a smoke test — start the built server with the simulator drivers and see it answer on a local port; (f) writes a build record (INDI version and source hash, host OS, compiler, library versions, file hashes); and (g) on an explicit publish step, uploads the wheel and its build record **to the website's Ubuntu server by rsync over SSH (or sftp)**, checks the SHA-256 of the uploaded file on the server, and only then adds or replaces that platform's entry (file name, size, SHA-256, URL) in the bundle index (C5). Building and publishing are separate steps, and nothing publishes without the owner running the publish step |

### 5.2 Non-goals (explicitly out of scope for v1)

| # | Non-goal |
|---|---|
| N1 | **Windows.** INDI is not buildable there (core SDD §2.3) and the plugin is for Linux and macOS. The plugin declares itself unsupported on Windows and does nothing |
| N2 | **Compiling INDI on the user's machine, or running the user's package manager.** The plugin ships prebuilt binaries (S1); it never builds, and it tells a user who wants a driver it does not bundle what to install and where to point the plugin |
| N3 | **Installing udev rules, firmware loaders or kernel drivers, or escalating privileges.** The plugin never runs `sudo`; it shows the command and the user runs it |
| N4 | **Managing a remote server.** A server on another host (StellarMate, Astroberry) is already reachable through the normal INDI pickers. Adopting a server (G3) covers a server on `localhost` only |
| N5 | **Replacing KStars/Ekos as an INDI control surface**, or the Control Panel's property browser. This plugin adds a server-management panel beside it; driver *property* browsing stays where it is |
| N6 | **Reconnecting devices after a server restart.** The plugin restarts the server and says so; the user reconnects their devices (accepted). Automatic reconnect would be a separate core item |
| N7 | **System service integration** (systemd units, launchd agents, start-at-boot independent of Galileo). The "leave running" lifetime (G7) is the only way a server outlives Galileo |
| N8 | **Running more than one server**, or several ports, per Galileo instance in v1 |
| N9 | **Bundling every INDI driver.** Only a curated subset is shipped (Section 10, Q11). Drivers whose vendor licence forbids redistribution, or that have no build for a platform, are not bundled |
| N10 | **Configuration files.** All settings live in Galileo's database through the plugin settings store (`PLUG-150`); the plugin writes no config files. The only files it creates are the runtime FIFO and log under Galileo's own platform directories |
| N12 | **Automated or hosted builds (CI) in v1.** The scripts are run by hand on each platform. They are written so a CI job could call them later, but no workflow is created or dispatched (C2) |
| N13 | **The plugin downloading binaries at run time from the website's index.** v1 delivers binaries at install time through `PLUG-200` (G2). A run-time downloader is a possible fallback if R10 shows `PLUG-200` cannot carry them, and would be a scope change |
| N11 | **Stopping, restarting or reconfiguring an adopted server itself.** On a server it adopted, the plugin may add and remove drivers (G3/G4) and nothing else: it never stops the server process, restarts it, changes its port, or removes a driver that the user has not asked it to. A server with no usable control FIFO is reported and used, with driver management shown as unavailable and the reason |

## 6. Dependencies on Galileo Core

| Core capability | Requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Loaded and isolated like any plugin; a plugin fault must not stop core |
| Enable/disable, inert when disabled | `PLUG-060` | A disabled plugin starts nothing; disabling it stops a server it started (unless "leave running", G7) |
| Removal | `PLUG-120` | Removal stops the server it started first |
| Panel placement | `PLUG-070` | A panel on the **Control Panel** (`aux`) Equipment page, declared with `panel_level = "equipment:aux"` |
| Options page | `PLUG-170` | Settings page labelled by the plugin |
| Plugin settings store | `PLUG-150` | Port, auto-start, lifetime, binary source, selected drivers, overrides — all in the database |
| Plugin dependencies | `PLUG-200` | **Carries the bundled binaries** as platform-specific packages installed privately into the plugin's folder and removed with it. See Section 9 for the constraints this places on the packaging |
| INDI server transport | `EXT-020`/`EXT-030`, SDD §2.3 | The plugin neither speaks INDI nor holds a connection (apart from a liveness probe of the port); it ensures a server is listening on `localhost:7624` |
| Platform paths | `NFR-PORT-010`, `galileo.platform` | FIFO and log locations come from the existing path resolver |
| Event bus | `ARCH` / `galileo.bus` | The plugin publishes server up/down/adopted events so other modules need not poll (event names settled in the SRS) |
| Dead-connection handling in the client | `IndiClient.alive`, `acquire_client` | **Verified in code:** a dead client is dropped and replaced the next time a device connects; nothing reconnects a connected session automatically. Accepted: after a restart the user reconnects (N6) |
| Local-server address for the INDI pickers | *none needed* | Core's adapters default to `localhost:7624`, which is sufficient. The port option should stay at 7624 unless the user has a reason to change it, and the panel shows the address to use if they do |

This plugin is expected to require **no new core requirement**.

## 7. Functional Requirement Domains (Scope-Level)

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `ISRV-BIN` | Bundled binaries | Platform matrix, packaging, installation through `PLUG-200`, version reporting, signing, behaviour on an unsupported platform | MVP |
| `ISRV-BLD` | Build and publication | The per-platform build scripts: prerequisites, pinned source, library collection, signing, wheel packaging, smoke test, build record, publish step and website index entry | MVP |
| `ISRV-DISC` | Discovery | Locating an existing `indiserver` and drivers (PATH, standard Linux locations, Homebrew on macOS); source precedence and override; clear "not found" state | MVP |
| `ISRV-PROC` | Process control | Detect-and-adopt on start-up, port conflict handling, FIFO channel, clean stop, lifetime option, orphan handling | MVP |
| `ISRV-DRV` | Drivers | Driver catalogue from INDI's XML, live add/remove, persisted selection, simulators | MVP |
| `ISRV-SUP` | Supervision | State machine, bounded restart with back-off, log capture, failure notices, events on the bus | MVP |
| `ISRV-UI` | User interface | Control Panel panel, Options page, in-app help, wiki article | MVP |
| `ISRV-PERM` | Permissions and first run | Linux group-membership check and advised command; no privilege escalation | P2 |
| `ISRV-NFR` | Cross-cutting | Inert when disabled or on Windows, no config files, no UI-thread blocking, no change to core adapters | MVP |

## 8. Stakeholders and Primary Personas

| Persona | Description | Primary interests |
|---|---|---|
| Single-machine imager | A laptop or mini-PC at the telescope on Linux or macOS, camera/mount/focuser on USB, nothing else installed | One plugin and one panel that gets the devices visible to Galileo; a first-run test with simulators |
| Observatory operator | A Linux or Mac mini running Galileo unattended | Server restarts after a fault; a server that survives a Galileo crash mid-exposure (G7) |
| Raspberry Pi 5 user | Runs Galileo on a Pi with the cameras attached locally | The same, on ARM Linux |
| Existing INDI user | Already runs KStars, a service, or a Homebrew INDI | That Galileo recognises and uses their server or install instead of fighting it (G3, G10) |

## 9. Assumptions, Constraints and Phasing

- **A1** — A Linux or macOS machine with no INDI can run the plugin from its bundled binaries alone (G2).
- **A2** — `indiserver` accepts `-p <port>`, `-f <fifo>` and `-v`, and its FIFO accepts `start <driver>` and `stop <driver>` lines. *Recalled from INDI documentation and not yet checked against the version Galileo will ship; to be confirmed in the SRS against a real build (Risk R1).*
- **A3** — INDI installs driver description XML files (`drivers.xml` and per-driver files) next to the drivers; the plugin builds its catalogue from them. Their location differs by platform and packaging (Risk R2).
- **A4** — USB and serial access on Linux depends on the user's groups and on udev rules; macOS has no equivalent step for most devices.
- **A5** — `PLUG-200` installs a plugin's requirements with `pip install --target` under Galileo's own interpreter, so a platform-specific wheel can be selected automatically, and requirements may carry PEP 508 environment markers. *Recalled from the plugin framework and pip behaviour; the exact way a marker, a direct-URL requirement and a non-default index behave is to be verified in the SDD before the distribution route is fixed (Risk R10).*
- **A6** — A server's control FIFO can be found from the running `indiserver` process's command line (its `-f <path>` argument), read through the operating system's process listing, with no extra package. A FIFO is usable only if the user running Galileo may write to it and the server was started with `-f` at all. *Recalled, not yet checked on either platform; the way to read a process's arguments differs between Linux and macOS and is to be settled in the SDD (Risk R15).*
- **C1** — Plugin code is Python ≥ 3.11; it spawns the server with `subprocess` and never links INDI into the Galileo process.
- **C2** — **No GitHub build or workflow is dispatched for this plugin without the owner agreeing to that run.** The binary builds (S8) are run by hand on the owner's machines, so no CI provider is needed. **Publishing is outward-facing:** uploading a bundle to a release or to the website, and editing the website's index, happen only when the owner runs the publish step; an assistant working on these scripts builds and tests locally and does not publish.
- **C5** — **The bundles are hosted on the project website's server, with an index beside them.** Today the site repository (`Galileo.web`) is static and holds no binaries: its downloads page links to GitHub release assets through a JSON index written by `scripts/update_downloads.py`. The bundle index copies that index's shape (platform, file, size, SHA-256, URL), but the files it points to are stored on the site's own server, where space is free. **The binaries are never committed to the `Galileo.web` git repository**; they are uploaded to the server directly (rsync over SSH or sftp). Bundles are stored under `/var/www/galileo/indi/<indi-version>/` on the server, and the bundle index is a small generated file at `/var/www/galileo/indi/index.json`, **beside the bundles** and is replaced atomically by the publish step; it is not hand-edited and not committed to git. Credentials are the owner's SSH keys and agent and are never stored in the scripts or any repository.
- **C3** — The plugin ships as its own package in the Galileo Plugins repository (working name `indi_server`) with its own `plugin.toml`, `pyproject.toml` and `build_zip.py`, matching the sibling plugins; the zip is built on request and installed by the user through Options > Plugins.
- **C4** — The bundled binaries must install with the plugin on a supported platform and **must not stop the plugin installing on an unsupported one**: the requirement is marker-guarded so the plugin still installs and works in discovery-only mode where no wheel exists (Section 10, Q12).

**Platform matrix (proposed).**

| Platform | Architecture | Notes |
|---|---|---|
| Linux (glibc) | x86-64 | Built in an environment with an old glibc baseline (R16) so it runs on current distributions |
| Linux (glibc) | aarch64 | Raspberry Pi 5-class; Raspberry Pi OS Bookworm and later; built on a Pi 5 or a comparable ARM machine |
| macOS | arm64 | Apple silicon. Binaries must be at least ad-hoc signed or the system will not run them |

**Scope delivery.** All of S1–S8 are v1 scope. The build order inside it is for the SDD to set, but the supervisor logic (S2–S7) can be developed and tested against a fake server before the build scripts (S1, S8) exist, so the two proceed in parallel. The scripts can be written and syntax-checked on any machine, but each can only be **run and verified** on its own platform (R3).

## 10. Open Questions for Review

**Decided in review of v0.1** (applied above): nothing preinstalled (Q1); lifetime is a configuration option and a running server is detected on start-up (Q2); a running server is adopted, and the plugin may add and remove drivers on it (Q3, Q3a); the panel lives on Equipment > Control Panel (Q4); macOS detection is Homebrew only (Q5); `localhost:7624` is sufficient (Q6); "restart the server, user reconnects" is acceptable (Q7); detached running is allowed, accepting the orphan risk (Q8); name and prefix accepted (Q9). **Decided in review of v0.7:** an existing INDI install (PATH, standard Linux locations, Homebrew) is used when found, and the bundled one is the fallback, with an Options override (Q10, G10); the first driver set is the INDI simulators plus a short list of widely used cameras, mounts, focusers and filter wheels, each passing a redistribution-licence check, growing on request (Q11); a platform with no bundled build installs in discovery-only mode with the panel saying why (Q12, C4); macOS is **Apple silicon only** (Q13); bundles are stored at `/var/www/galileo/indi/<indi-version>/` and the index at `/var/www/galileo/indi/index.json` (Q17, C5). **Decided in review of v0.8:** build machines for Linux aarch64 and macOS arm64 are available in the local development lab, alongside the local server for Linux x86-64 (Q15); the bundles track the **latest stable INDI release** (Q16, R19). **Decided later:** the published binaries are stored on the project website's own server, not on GitHub (Q14), uploaded by rsync over SSH or sftp (Q17); Linux x86-64 is built on a local server (Q15).

**Still open:** none. Every scope question has been answered; the document awaits sign-off before the SRS is written. (Details to settle later, in the SRS and SDD, are marked as assumptions A2, A3, A5 and A6 and risks R1, R10 and R15.)

## 11. Risks

| # | Risk | Impact | Notes |
|---|---|---|---|
| R1 | `indiserver` option and FIFO behaviour, and driver XML layout, differ between INDI versions | Medium | Confirm on a real Linux and macOS build before the SRS; because the plugin ships the build it was tested with the behaviour of the bundled server is known, but an adopted or Homebrew server may differ — where the FIFO is unavailable, fall back to a fixed driver list and restart on change |
| R2 | An existing install keeps its driver XML and executables in different places per packaging (distribution packages, source builds, Homebrew) | Medium | Discovery is a search list plus a user override (Options); a missing XML degrades to "type the driver name". The bundled copy's layout is fixed and known |
| R3 | **No Linux or macOS machine in the development setup** (Galileo is developed on Windows) | High | Supervisor logic is tested against a fake `indiserver` process and the existing [`tests/indi_fake_server.py`](../../../tests/indi_fake_server.py); real-install checks are `hardware`/`integration`-marked and need a Linux and a Mac tester. **The build scripts cannot be run or verified here at all:** each is written and reviewed here and then proved by the owner on its own platform, so expect a fix-and-rerun cycle per platform |
| R4 | Orphaned servers: Galileo killed while a child or detached `indiserver` is running leaves the port held | Medium | Detect-and-adopt on the next start-up (G3); an explicit "stop the server I started earlier" action; a recorded PID is verified against the running process before it is trusted |
| R5 | A crash loop (bad driver, missing device) consumes CPU and floods the log | Low | Bounded restart count and back-off, then stop with a visible notice (G5); rate-limited log |
| R6 | USB permission failures look like "driver loads but no device" | Medium | Linux group check and advice (G6); the log pane shows the driver's own messages |
| R7 | Safety: stopping the server while an exposure or slew is in progress | Medium | Confirmation when core reports a connected, busy INDI device; wording and the check defined in the SRS. (Core safety already treats a lost server as a fault — see `galileo.safety`.) |
| R8 | The plugin is the only thing standing between Galileo and the server on the single-machine setup, so its faults are visible | Low | Fault isolation (`PLUG-040`): a plugin error leaves the server running and the panel reporting "unmanaged", never takes core down |
| R9 | **Redistribution licensing.** INDI itself is LGPL and an out-of-process server keeps that separate from Galileo's GPL-3.0, but vendor SDKs inside drivers have their own terms, and some have no macOS or ARM build | High | Each bundled driver passes a licence check (Q11); drivers that fail are not bundled and the plugin points the user to the vendor. Source offers and licence texts ship inside the wheels |
| R10 | **Distribution route is unproven.** Whether `PLUG-200` can install a binary wheel by direct URL with environment markers (A5), and whether the executable bit survives, has not been tested | High | A small proof — a trivial platform wheel installed through the real plugin installer on each target — comes before any other binary work. If the framework cannot do it, the fallbacks are a core change to `PLUG-200`, per-platform plugin zips, or a run-time download from the website's bundle index (N13, a scope change); each would be raised as a core requirement or a scope decision |
| R11 | **macOS signing.** An unsigned arm64 binary is killed by the system; a binary that is signed but not notarised may still prompt if it carries a quarantine flag | High | Ad-hoc sign every Mach-O in the build; files written by the plugin installer (not a browser) do not normally carry the quarantine flag; verify on a real Apple-silicon Mac before release |
| R19 | **Tracking the latest INDI release.** A new release can change driver behaviour, the FIFO, property names, or drop a driver; platforms built on different days can end up on different INDI versions; every new release means a new bundle and, because the plugin's `requires` entries carry the bundle's URL and hash (R10), a new plugin zip | Medium | The scripts resolve the version once and take it as an argument, so one plugin release uses one INDI version on every platform; the build record names it; the smoke test (S8) must pass before publishing; release notes for the plugin name the INDI version; a published bundle is never replaced, so an older plugin zip keeps working. Moving to a new release is a deliberate rebuild by the owner (C2), not automatic |
| R12 | **Build and maintenance burden.** Each INDI release (Q16) means a hand-run rebuild on up to three machines, with bundled shared libraries (cfitsio, libusb and others) collected for each; builds on different machines can drift apart | High | The INDI version and source hash are recorded for every build, library versions are recorded, scripted build, a recorded build record per bundle, and a smoke test that must pass before a bundle can be published (S8). Owner's time and machines are the cost (Q15); nothing runs without the owner (C2) |
| R16 | **Linux compatibility baseline.** A bundle built on a current distribution may need a newer glibc than a user's system has, and fail to start | High | Build the x86-64 bundle in a container with an old glibc baseline; build aarch64 on the oldest Raspberry Pi OS the plugin supports; the smoke test and the bundle's recorded baseline are checked before publishing |
| R17 | **Publishing is a one-way, public act.** A wrong bundle uploaded to the website or an index entry pointing at the wrong hash would break installs for every user of that platform | High | The publish step is separate from the build, shows what it will upload and change, requires the smoke test to have passed on that bundle, never overwrites a published file (each build has a new versioned path), and keeps the previous index entry so a bad publish can be reverted |
| R18 | **The website is now on the install path.** A plugin install on a supported platform needs the site up to download its bundle; if it is down, or the file is moved, the install fails and rolls back (`PLUG-200`) | Medium | Published files are kept at stable versioned paths and not removed while a released plugin zip refers to them; the plugin's install message names the URL it could not fetch; a user can install the bundle from a downloaded file or use an existing INDI install (discovery-only mode, Q12) |
| R13 | **Plugin size.** A bundled server and drivers with their libraries may be tens of megabytes per platform | Low | Strip binaries, bundle only the curated driver set (Q11), and install per platform so users download one build |
| R15 | **Driver management on an adopted server.** The server may have been started without a FIFO, with a FIFO owned by another user, or by a different INDI version that handles `start`/`stop` differently; removing a driver can drop a device another client (KStars, a script) is using | Medium | Driver management on an adopted server is offered only when a writable FIFO is found (A6) and otherwise shown as unavailable with the reason (N11). Adding or removing a driver on an adopted server shows what other clients are connected where the server reports it, and confirms before removing a driver whose device is connected or busy (R7). The plugin never stops the adopted server itself |
| R14 | Binaries from one platform being offered on another (wrong architecture, old glibc) | Medium | Markers guard each build (C4); the panel reports the detected platform and the version it found; an unsupported platform degrades to discovery-only (Q12) |

## 12. References

- [Galileo Core PSD](../../PSD.md); core SRS `EXT-020`, `EXT-030`, `ARCH-050`, `EQP-AUX-010`/`020`, `PLUG-010`–`PLUG-210`, `NFR-PORT-010`, `NFR-SEC-020`; core SDD §2.3 (INDI I/O) and §4 (INDI adapter, Aux server panel)
- [`galileo/adapters/indi_client.py`](../../../galileo/adapters/indi_client.py) — the native INDI client (`acquire_client`, `IndiClient.alive`)
- [`galileo/plugins/__init__.py`](../../../galileo/plugins/__init__.py) — `PluginBase`, `PluginContext`, `PluginSettings`, manifest and `requires` handling
- [WandererBox plugin PSD](../wandererbox/PSD.md) — structural template for a plugin PSD that depends on core capabilities
- [INDI library](https://github.com/indilib/indi) — `indiserver`, the driver description files and the licence terms (to be verified against the version in use, A2/A3/R9)

## 13. Glossary

Terms not already defined in [Galileo core PSD's Glossary](../../PSD.md#15-glossary) apply unchanged; the following are specific to this plugin:

| Term | Definition |
|---|---|
| `indiserver` | The INDI process that loads drivers and multiplexes their devices to clients over TCP (default port 7624) |
| Driver | An `indi_*` executable that `indiserver` runs to expose one or more devices |
| Driver description XML | The files INDI installs describing each driver's label, group, executable and version, used here to build the driver list |
| FIFO | A named pipe given to `indiserver` with `-f`; writing `start <driver>` or `stop <driver>` to it loads or unloads a driver at run time |
| Bundled INDI | The prebuilt `indiserver` and curated drivers the plugin installs for the current platform through `PLUG-200` |
| Adopt | Use a server that was already running when the plugin looked, without starting, stopping or reconfiguring the server itself. The plugin may add and remove drivers on it through its FIFO (N11) |
| Managed server | A server the plugin itself started and therefore supervises |
| Lifetime | The configuration option that decides whether a managed server stops with Galileo or keeps running |
| Build script | One of the per-platform scripts (S8) that builds, packages and smoke-tests the bundle for the platform it runs on, and separately publishes it |
| Bundle index | The JSON file on the project website listing, for each platform, the bundle's file, size, SHA-256 and download URL; the bundles it points to are stored on the same website's server (C5) |
| Build record | The file written beside each bundle recording the INDI version and source hash, the host OS, the compiler, library versions and file hashes |
| Discovery-only mode | The plugin's behaviour on a platform with no bundled build: it can find and manage an existing install but provides none |

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's PSD](../../PSD.md).*
