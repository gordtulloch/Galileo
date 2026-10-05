# Galileo Code Review

Reviewed 2026-10-04 on `main` (Python 3.11.9, project `.venv`). This review runs the lint/type/security/test/dependency
toolchain against the repository as it stands and reports what each tool found, plus a spot-check of the flagged code.
It replaces the previous review; its findings (migration 013 cross-reference, shell injection, current_object reset, LOG-050,
install failure, AutoAddPolicy, weak hashes, `core.devices` typing, `app_window` split) are all confirmed fixed in the
code and are not repeated. It does not re-derive architecture from `docs/`.

## How to reproduce

```bash
pip install -e ".[test,dev]"
pip install bandit pytest-cov pip-audit
ruff check . --statistics
mypy . --ignore-missing-imports
bandit -r galileo
pytest -m "not soak and not hardware and not integration" --cov=galileo --cov-report=term
pip-audit
```

## Summary

| Tool | Result |
|---|---|
| ruff | **1,138 findings**, but 326 are `W293` (whitespace) and 221 `TRY400` (`logger.error` vs `exception`); stylistic. Real-defect rules: 3 `F821`, 1 `RUF006`, 5 `ASYNC210/230/251` (see below) |
| mypy | **473 errors in 72 of 245 files** (previous review: 404 in 48 — the count has grown). Top: `library/core/master_manager.py` (50), `ui/app_window/_threads.py` (41), `ui/library/sessions/checkout_workflow.py` (24). Mostly `union-attr` (104), `attr-defined` (92), `assignment` (77) |
| bandit | **49 findings** (7 High, 10 Medium, 32 Low). High are all FTP (accepted, see F7) and the SFTP policy (F4) |
| pytest | **785 passed, 14 failed, 1 skipped, 6 deselected** (637 s). Coverage **57 %** (34,917 statements) |
| pip-audit | No known vulnerabilities. Caveat: pip-audit warned it audited the interpreter's environment rather than the venv's packages; re-run with `PIPAPI_PYTHON_LOCATION` set to confirm |

## High

### F1. ~~Per-Pier slew guard test fails — probable global-state leak~~ — Fixed (diagnosis corrected)
`test_slew_guard_is_scoped_per_pier` failed even when run alone, so it was not an order-dependent leak in
`galileo/core/slew_guard.py` as first suspected. The `window` fixture built the app before the test patched the Planning
options path, so the page read the developer's real `planning.json` (`block_obstructed_slews: true`); the checkbox started
checked, the test's `setChecked(True)` emitted nothing, and `_select_observatory` then read the empty patched path and
disabled the guard. Fixed in `tests/test_star_atlas.py` by isolating the options path in the `window` fixture. No product
code changed. (`_guards` is still module-level with no reset hook; harmless today, worth adding if more per-Pier tests appear.)

### F2. Four marketplace tests fail and one reveals a real contract mismatch (`tests/test_plug.py`, `PLUG-100`)
The client reports "Plugin index is not a JSON array", `MarketplaceClient.__init__` rejects `base_url`, and the cache test
sees 2 HTTP calls where 1 is expected. Either the tests are stale against the implementation or the second-call cache is
genuinely not working (an extra network call per refresh). Decide which; the cache assertion is the one that could be a user-visible bug.

### F3. ~~Star Atlas UI tests fail against the current UI~~ — Fixed (tests were stale)
All three were tests lagging the product, not product bugs: `contextMenuRequested` gained a third argument (the clicked sky
position) and the test emitted two; Options gained a Plugins page after the per-section pages; and the Science menu test assumed
only core items, but an installed plugin (VSTarget's "VS Analysis") appends its own — which also made it depend on whichever
plugins the machine happened to have. The tests now emit the three-argument signal, expect Options = the primary sections plus
Plugins, and check that core items come first in a menu rather than that the menu is exactly them. `tests/test_star_atlas.py`: 60 passed.

## Medium

### F4. ~~SFTP failures are swallowed at debug level and unknown host keys are accepted silently~~ — Fixed
SFTP ownership first: the VSTarget plugin never had its own SFTP code — `vstarget.analysis.SftpImageRetriever` was a
re-export of the Library adapter, plus an unused `paramiko` dependency and a mock-only test. Only the Library's is
required, so the plugin's was removed (module, dependency, test, README entries) and `VST-AN-010` retired in the plugin's
SRS/SDD/PSD/RTM. `galileo.library.adapters.sftp` is now the single implementation (`EXT-120`, `EXT-080` stay core).
It was still defective: failures logged at `debug` (an unreachable host looked like "no new files"), the SSH client leaked
on any exception, one bad file abandoned the rest, and the comment claiming unknown keys were "logged" was untrue —
paramiko's `WarningPolicy` goes through `warnings`, not `logging`. Now: failures log at WARNING with traceback, the client
and SFTP channel are closed in `finally`, a failed file is skipped, a small policy logs the unknown key's fingerprint, and a new
`strict_host_keys=True` option rejects unknown keys for non-LAN use. Bandit B507 no longer fires. Three new `TC-EXT-120`
tests cover this against a fake `paramiko`. The Library feature itself was then wired up (new requirement `LIB-170`): an **SFTP** source in Library > Download and in
`galileo-download -t SFTP -H <host>`, with its account, key file, remote folder, port and host-key policy under Options >
Library > Smart Telescopes and the password in the OS keychain. The adapter gained a reusable `SftpSession` (recursive
listing, cancellable fetch, delete); that work also caught and fixed a leak where a failed connect inside a `with` skipped
cleanup. Tests: `TC-LIB-170` (three, against a fake `paramiko`). The pre-existing smart-telescope sources are unchanged;
TODO.md's note about merging the two adapter sets behind `RemoteSourceAdapter` still stands.

### F5. ~~Blocking I/O inside `async` functions~~ — Fixed
Every blocking call now runs via `asyncio.to_thread`: the `httpx`-missing `urllib` fallbacks in `adapters/alpaca.py` (three
sites), `safety.py` `get_forecast_advisory` (the safety poll no longer stalls up to 10 s on a slow forecast service),
`planning/sky_atlas.py` `geocode_location`, the SMB download in `library/adapters/smb.py`, the SFTP `mkdir`, the ASTAP
executable check and stale-sidecar cleanup in `platesolve.py`, and the `mkdir` plus full-frame FITS write in
`ui/imaging.py` `capture_and_preview` (the heaviest of these — it blocked the loop for the whole write). `ruff --select
ASYNC210,ASYNC230,ASYNC240,ASYNC251` is clean; the two `ASYNC109` hits are a `timeout` parameter name, not a defect.

### F6. ~~Fire-and-forget task with no reference (`core/devices.py`)~~ — Fixed
`DeviceController.set_property` now schedules the write with `create_task`, holds it in a module-level set until it finishes,
and logs any failure (with traceback) from a done-callback. With no running loop it runs the write to completion with
`asyncio.run` and logs failures, instead of the old `get_event_loop()`/`run_until_complete` branch whose
`except RuntimeError: pass` dropped the coroutine un-awaited and unreported. Two new `TC-EQP-020` tests cover the held
reference and the logged failure.

### F7. ~~FTP and unsafe XML parsing~~ — Fixed (FTP accepted, as before)
- **XISF header parsing:** `library/file_formats/xisfFile/xisf_converter.py` parsed the header of an *imported* file with the
  standard-library XML parser, which expands entity declarations (billion-laughs, external entities). It now uses
  `defusedxml`, which refuses them; `defusedxml>=0.7` is added to `pyproject.toml` and `requirements.txt` (it was installed
  transitively but never declared). Bandit B314/B405 clear. The file had no tests at all; two now cover a normal header and an
  entity-bomb header (`TC-LIB-010`).
- **User-supplied URLs:** I checked every `urlopen`. All but one build their URL from a constant or from internal values
  (Open-Meteo, OpenNGC, AAVSO, the Alpaca host:port the user types into an `http://` URL), so there is no scheme to abuse. The
  exception is the notification webhook (`notify.WebhookChannel`), whose URL the user configures: `urlopen` also accepts
  `file://` and `ftp://`, so a non-HTTP(S) webhook is now refused and logged. Test: `TC-EXT-070`. The remaining B310 reports
  on the fixed-URL sites are false positives and are left alone rather than wrapped in a helper that would add nothing.
- **FTP** (`telescope.py`, `adapters/ftp.py`): unchanged — iTelescope's and DWARF's servers speak FTP/FTPS and nothing else.
  iTelescope already uses FTPS (TLS); the DWARF path is plain FTP on its own access-point network, which is inherent to the device.

### F8. Undefined names in annotations (`ui/app_window/_current_object.py:63,76,91`, `_misc_device_pages.py:47`)
`SkyAtlas`, `DeepSkyObject`, `ObservatoryScheduler` are not imported under `TYPE_CHECKING`. Harmless at runtime (`from
__future__ import annotations`) but they break mypy resolution and `typing.get_type_hints`. Add them to the `TYPE_CHECKING` block.

### F9. ~~Mypy debt is growing and includes likely real errors~~ — Fixed for the two startup errors; rest remains
Both `app.py` errors were type-annotation problems, not runtime bugs. (1) `app.py:55`, "Invalid self argument `AppWindow`":
the `AppWindowState` protocol in `ui/app_window/_state.py` declared `_camera_backends` and `_imaging_service` as settable
attributes, but the mixin defines them as read-only properties, so `AppWindow` did not satisfy the protocol it is the `self`
of for every mixin method. They are now declared as read-only properties. (2) `app.py:40`, `setWindowIcon`: `QApplication.instance()`
is typed `QCoreApplication`; it is now cast to the `QApplication` that code creates. Total mypy errors 473 → 470. The 104
`union-attr` errors in `master_manager.py` and `_threads.py` (unchecked `Optional`) are the likeliest source of runtime
`AttributeError: 'NoneType'` and are still open; none were verified as live bugs.

## Low

- **F10. ~~Test failures that are unimplemented features, not regressions~~ — Fixed:** `LOG-060` (`RecentLogPane`, P2) and
  `NOTIF-020`/`030`/`040` (`EmailChannel`, `set_owning_observatory`, P3) do not exist in `galileo/`, so their four tests are now
  `xfail(strict=True, raises=AttributeError)` with the requirement and the missing piece in the reason. The red list now means
  regressions only; `strict=True` makes the suite fail loudly (XPASS) the day one is implemented, prompting removal of the marker.
  (`SimbadClient`/`EXT-110` was listed here in error: Simbad lookup is implemented as `_search_simbad_sync`; the test now
  exercises it against a stubbed `astroquery` — fixed.)
- **F11. Performance test is flaky/slow on this machine:** `TC-NFR-PERF-010` rendered in 4.41 s against a 3 s limit.
  Confirm whether this is hardware (dev box under load while coverage was on) or a real regression; run without `--cov`.
- **F12. Naive datetimes:** 41 `datetime.now()`, 13 `utcnow()` (deprecated in 3.12), 7 `date.today()`. Astronomy
  code mixing local and UTC times is a classic source of off-by-hours scheduling errors; use timezone-aware UTC.
- **F13. Error-handling idiom:** 221 `logger.error` inside `except` (drops the traceback), 51 `raise` without `from`, 18
  `raise Exception(...)` (TRY002). Mechanical to fix.
- **F14. Non-strict `zip` (26), unused variables (32), unused imports (25), `E712` `== True` (41).** Cheap clean-up.
- **F15. Tests:** `tests/test_lib.py:478` uses `hashlib.md5` without `usedforsecurity=False`; `test_nfr.py` hardcodes `/tmp`.

## Coverage gaps (57 % overall at review time)

**Closed:** the XISF converter (0 % → 90 %, `tests/test_xisf.py`, 43 tests) and the `galileo.commands` batch utilities (16 % → 58 %
for the package, `tests/test_commands.py`, 47 tests plus 3 documented `xfail`s). Writing them found six defects, listed below.

**Defects the new tests found**
1. **Colour XISF images could not be converted at all.** `XISFGeometry.channel_size()` multiplied *every* dimension, so it returned
   the whole image's pixel count and the per-channel reshape failed for any multi-channel file. It is now `width × height`. Fixed.
2. **The Library's XISF ingest handler was broken for every file.** `XisfFileHandler` called `XISFConverter()` with no path and
   `convert_to_fits(src, dst)` with two arguments, then treated the returned path as a boolean — so each `.xisf` import ended in
   `XISF_CONVERSION_ERROR`. Fixed (and covered end to end through `FileFormatProcessor`).
3. **Multi-channel FITS header cards were wrong:** `NAXIS` counted the channel axis twice and an extra `NAXISn` was invented.
   The creation-time/software cards were also never read from namespaced headers (nor from the standard `XISF:CreationTime` /
   `XISF:CreatorApplication` properties real PixInsight files use). Fixed.
4. **`load_repo --repo` and `sync_repo --repo` were silently ignored.** The override was set on the `fitsProcessing` facade, but each
   file is filed by a fresh `RepositoryManager()` built from `library.ini`, so everything still went to the configured repository.
   The facade's folders now forward to the components that do the work, and the file processor passes its folder to the manager.
   Fixed.
5. **`galileo-register-existing` cannot work.** It calls `fitsProcessing.registerExistingFiles`, which exists neither in Galileo nor
   in AstroFiler, so outside `--dry-run` it always fails. Not fixed — it is a missing feature (what "register existing masters and
   calibrated lights" should do is a design decision). Pinned by a strict `xfail`.
6. **"Only duplicates" runs report success.** `load_repo` and `sync_repo` are written for a `(files, duplicate_count)` return, but
   `registerFitsImages` returns a plain list, so the "No new files … N duplicates skipped" branch and its exit code 1 are
   unreachable. Not fixed (the catalog is correct — duplicates are not re-added; only the exit code is wrong). Pinned by two strict `xfail`s.

**Still essentially untested:** `library/core/variable_star_photometry.py` (0 %), `ui/library/auto_calibration_dialog.py` (0 %),
`library/services/telescope.py` (6 %, the SMB/FTP/FTPS paths — the SFTP source has tests), `library/services/cloud.py` (10 %),
`library/core/utils.py` (19 %), and the long-running bodies of `commands/auto_calibration.py` / `cloud_sync.py` that call into
those services (the commands' own argument handling, routing and exit codes are covered; the sync bodies are not).

## Suggested order

1. F1 (confirm and fix slew-guard state leak) and F2 (marketplace cache).
2. F5 (`safety.py` blocking call) and F6 (dropped task).
3. F9 (the two `app.py` errors), F4 (SFTP error visibility), F7 (`defusedxml`).
4. F3/F10: bring stale tests in line or `xfail` them so the suite is green and informative.
5. ~~Tests for the `commands/*` batch utilities and the XISF converter~~ — done (see Coverage gaps); remaining: defects 5 and 6 there.
6. Mechanical ruff/mypy clean-up (F8, F12–F14).
