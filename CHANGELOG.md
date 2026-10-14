# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project does not yet follow Semantic Versioning releases (see `README.md` status) — entries accumulate under `[Unreleased]` until the first tagged release.

**Older entries are archived in [`docs/changelog/`](docs/changelog/)**, one file per rotation (e.g. [`2026-09.md`](docs/changelog/2026-09.md)), so this file stays short enough to read in full. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end. When this file grows past roughly 40 KB, move everything under `[Unreleased]` to the top of the current month's archive file (creating `docs/changelog/YYYY-MM.md` if needed) and leave `[Unreleased]` empty again.

## [Unreleased]

### Fixed

- **Removing a session from the Schedule grid now returns it to the Unscheduled tray** (its start time is cleared) instead of deleting the job. Right-clicking an entry in the Unscheduled tray now offers **Delete** (with confirmation) in place of Remove from Schedule, so deleting is the explicit, separate action. Pier operations, which have no tray to return to, are still deleted. Inline help updated.

- **A session scheduled on Planning > Sessions now appears in the Schedule page's Unscheduled list.** The Schedule page only refreshed on Pier changes, so a job added while it was hidden stayed invisible until something else forced a reload; it now reloads each time the page is shown. No help/wiki change (no control changed).

- **Start-up splash shows device connection attempts.** While the Equipment screens auto-connect, the splash now names each device being connected (name, host:port) and then records a ✓ Connected or red ✗ Failed line, instead of sitting on "Loading Equipment screen". Applies to the mount and all other device pages that connect through the shared adapter path; the camera sensor-info probe is not reported. Internal UI change; no help/wiki/design-doc impact.

- **Splash progress bar no longer covers the logo.** The start-up progress bar, operation list and percentage now sit in a strip added beneath the licence notice rather than over the Galileo artwork. Internal UI change; no help/wiki/design-doc impact.
- **Crash ("QWidgetItem has no attribute 'isVisible'") when connecting to PHD2.** The help tooltip timer scanned `QApplication.topLevelWidgets()` and hit a stale non-widget wrapper while a window was being torn down; it now skips anything that isn't a real `QWidget`. The root cause of the stale wrapper (likely the PHD2 connect dialog closing) was not identified from the crash report alone.

### Added

- **User Acceptance Test script, [`docs/UAT.md`](docs/UAT.md).** An ordered, end-to-end manual test that follows a night imaging M13: install and launch, Observatory/Pier, Options, equipment (an INDI server running the simulator drivers), Star Atlas and planning, framing, slew, test exposures, solve, focus, guiding, building and running a session, safety, scheduling, History, calibration frames, Library processing and shutdown. Each step has an expected result and a pass/fail column, blocker steps are marked, and there is a sign-off table. Documentation only; no code, help or wiki change.
- **Target name is a search box in Sessions > Target Parameters.** Typing in Name now searches the sky-atlas catalog (name and designations) and lists matches; picking one fills in the name, RA and Dec. Manual entry still works. Help entry for Name updated.
- **Add Session from Template on the Sessions screen.** A new button beside Add Session offers the saved templates and creates a new session holding all of the chosen template's blocks (including its placeholder Target), so a stored procedure no longer needs an existing session to load into. New `SessionsScreen.add_session_from_template`; help entry added to `planning.sessions.md`.
- **Progress bar on the Targets screen search.** Searching now opens a small dialog with a progress bar that moves through the phases — catalog search, altitude charts, building each result tile, fetching thumbnails — instead of leaving the UI apparently frozen with only a status-bar message. No new controls, so no inline-help change.
- **Image block Filter is preloaded from the filter wheel.** In Sessions > Image Parameters, Filter is now an editable drop-down listing the active filter wheel's filters (blank keeps the current filter), as the Filter Change, Focus and FOR Filter blocks already did; with no wheel connected it stays typeable. Tests updated for the combo. The control keeps its label, so no help-file change.
- **"Searching N objects" notice on Planning > What's Up Tonight.** Ranking runs for a noticeable time, so a small dialog now names how many catalog objects (after the catalog/magnitude filters and candidate cap) are being ranked, and closes when ranking finishes. No new controls, so no inline-help change.
- **Start-up progress on the splash screen.** The slow initial load now shows a progress bar and the list of operations being run (diagnostics, crash reporting, database/migrations, UI code, plugin discovery, main window, top bar, each screen, Options, theme, watchdog) — the running one in white, the last few finished ones ticked and dimmed — so users can see how far start-up is. New `galileo.ui.startup_progress` (`report()` is a no-op unless `app.main` installs a reporter, so tests and `--selftest` are unaffected). No new controls, so no inline-help entries.

### Changed

- **Sessions "Target" block renamed "Slew To".** The palette entry, block-list text, and dialog title (now "Slew To Parameters") say what the block does. Internal class and saved-template format are unchanged, so existing sessions and templates load as before. Help heading renamed to match.
- **About Galileo dialog asks for Patreon support.** The dialog now explains that the project costs real money to run (web site, developer licenses, test equipment) and links to https://www.patreon.com/starseekersca. Text-only change; no new controls, so no inline-help entries.

- **Altitude graphs on Targets and What's Up Tonight show just the night.** The per-object rise/transit/set graph now spans sunset to sunrise instead of a fixed 24 h from UTC noon (which put labels at odd times like 17:30), labels whole local hours in smaller text, is twice as wide, and shades the background by the Sun's altitude so dusk and dawn fade in and out. Charts now also carry `sun_altitudes`; if it is missing the old full-range plot is used. No new controls, so no help/wiki change.

- **What's Up Tonight ranking notice reworded.** The dialog shown while ranking now reads "Analyzing N objects that meet criteria…" instead of "Searching N objects…", since the objects have already been filtered by then. Text only; no help/wiki impact.
- **Changelog rotated.** `[Unreleased]` had grown to 162 KB against the ~40 KB threshold, so its contents moved verbatim to the top of `docs/changelog/2026-10.md` under "[Unreleased] as of 2026-10-13" (archive title range extended to 2026-10-13). Documentation housekeeping only; no code or behaviour change.
