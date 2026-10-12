# Code Review — Galileo (green-field, automated)

Date: 2026-10-12 · Branch: `main` · Python 3.11 venv · 245 modules under `galileo/` (~60 k LOC) plus `tests/`

Tools run (project configuration from `pyproject.toml`, no rules added or removed):

| Tool | Version | Command | Raw result |
|---|---|---|---|
| ruff | 0.16.10 | `ruff check .` | **1 222 findings** (1 066 in `galileo/`, 156 in `tests/`) |
| mypy | 2.4.0 | `mypy .` | **643 errors in 115 files** (299 files checked) |
| bandit | 1.9.4 | `bandit -r galileo` | 5 High, 14 Medium, 37 Low (all High are one file; see §3) |
| pip-audit | 2.10.1 | `pip-audit` (against the project `.venv`, 138 packages) | **No known vulnerabilities** (§3a) |
| vulture | latest | `vulture galileo --min-confidence 80 / 60` | 14 findings at ≥80 %, 538 at ≥60 % (§5a) |
| radon | latest | `radon cc / mi / raw galileo` | Average complexity **A (3.5)**, but 21 blocks rated E/F; 13 modules with MI grade C (§5b) |

pip-audit, vulture and radon were installed into the venv for this review (they are not in the `dev` extra yet — see §7). The test suite was not executed.

Method note: raw tool output is mostly style noise. Items below are triaged into **verified real defects** (I read the code), **probable defects** (tool-flagged, not yet confirmed), and **hygiene** (bulk, mechanical). "Verified" means I inspected the cited lines; nothing has been changed in code.

---

## 0. Remediation status (2026-10-12)

Everything that could be corrected without a product decision has been corrected. Totals, before → after, same tools/config:

| Tool | Before | After |
|---|---|---|
| ruff | 1 222 | **450** (about 100 of the rest are in files that had uncommitted work in progress and were deliberately not touched — see below; 233 are `TRY401` style notes created by the `logger.exception` sweep) |
| mypy | 643 errors | **452** (a stub-less-library override block was added to `pyproject.toml`) |
| bandit | 5 High / 14 Med / 37 Low | 1 High / 14 Med / 29 Low (remaining High = the `import ftplib` itself) |
| radon | 11 E-rated + 10 F-rated functions | 11 E-rated, **0 F-rated** (average still A, 3.5) |
| pip-audit | 0 | 0 |

**Done (code):** §1.1–1.7, §2.1–2.3, 2.5 (typed port constructor), 2.10, 2.11 (`filter_offsets_dialog`), the vulture ≥80 % unused imports, 20 bare `raise Exception` → specific exception types, 51 `B904` chained raises, 443 safe auto-fixes (whitespace, `UP`, `C4`, `SIM`, `FURB`, `PIE`, `RUF`), unused variables / loop variables (side effects kept), `ClassVar` annotations, ambiguous names and un-escaped `pytest.raises` patterns in tests, `E402` for GUI tests (per-file ignore), a `urlopen` scheme guard in `variable_star_photometry`, `# nosec` rationale on the intentional FTP / default-username lines, `bandit` / `pip-audit` / `vulture` / `radon` added to the `dev` extra, mypy `ignore_missing_imports` for stub-less scientific libraries, and removal of the dead `except: raise`.

**Corrections to the original findings** (found while fixing):
- §3 MD5: product code already passes `usedforsecurity=False`; only a test uses plain `md5`. No change needed.
- §3 KML parsing (`safety.py`): already carries a `noqa: S314` for a fixed NOAA endpoint; left as is (it parses only a trusted HTTPS feed).
- §4 `httpx`: it is an *optional* import with a `urllib` fallback, not a missing dependency; `sep` is a declared dependency and is installed — mypy merely lacks stubs for it.
- §2.10 was a false positive and is now annotated.

**Not touched because they had uncommitted changes when this pass ran** (to avoid colliding with work in progress): `galileo/adapters/alpaca.py`, `galileo/adapters/indi.py`, `galileo/app.py`, `galileo/dome.py`, `galileo/notify_settings.py`, `galileo/plugins/__init__.py`, `galileo/plugins/marketplace.py`, `galileo/selftest.py`, `galileo/ui/app_window/_plugins_page.py`, `tests/test_commands.py`, `tests/test_plug.py`, `tests/test_xisf.py`, and `galileo/library/migrations/` (migrations must stay replayable). That includes §2.7 and §2.8 (`alpaca.py`), the `F811` shadowing in `test_commands.py` (40 findings), `ASYNC109` / `E731` / `RUF012` in the adapters, and the unused imports in `_plugins_page.py`. Re-run the fixes on them once that work is committed.

**Verification:** full suite (excluding the help-audit test) — 1 054 passed, 4 failed. None is caused by this pass: `test_tc_img_170` (`mosaic_overlap_pct` option from work in progress), `test_options_has_a_settings_placeholder_for_each_primary_section` and `test_star_atlas_page_shows_the_sky_at_the_observatory_site` (both reproduce on a clean checkout of `HEAD`), and `test_tc_nfr_perf_010` (3.7 s vs a 3 s budget while the machine was loaded). The help-audit test `test_tc_help_060` also fails on `HEAD` (undocumented `mosaic-pane-overlap` and VSTarget controls). After the later refactors, 325 tests across the library, command, sequencer, scheduler, architecture and extension domains were re-run and pass. The final full-suite run (excluding the help audit) gave 1 063 passed / 6 failed: two (`test_tc_foc_090` ×2) were caused by this pass (`zip(strict=True)` on autofocus positions vs readings) and are fixed and re-run green; the other four are the pre-existing ones listed above.

**Decisions taken and carried out (the answers to the questions raised by the first remediation pass):**
- **Datetimes → UTC-aware (`DTZ*`, all fixed in non-test code).** Values written to the database and FITS headers (`DATE`, `DATE-OBS`, `CALDATE`, calibration/validation dates) are now UTC; because Peewee `DateTimeField` columns are naive, those are stored as *naive UTC* (`datetime.now(UTC).replace(tzinfo=None)`). Event timestamps (`utcnow()`) are now `now(UTC)` and so carry a `+00:00` suffix. Labels, log lines, folder/file stamps and the "Started at" lines use the aware *local* time (`.now().astimezone()`), so what users see is unchanged. Calendar-only parsing (`strptime`, `date.today()`) is annotated `noqa` with the reason. `LoopUntilTimeCondition` now treats a zone-less `time_utc` as UTC instead of comparing against `utcnow()`. Existing rows in the library DB written by the AstroFiler-era code are naive *local* time, so comparisons against them (e.g. master retention cut-off) are off by the UTC offset until those rows age out. `DTZ` is ignored in `tests/`.
- **`TRY400` → `logger.exception` (219 sites) and `B905` → `zip(strict=True)` (21 sites; the 11 that legitimately differ in length keep `strict=False` — pairwise/`[1:]`, truncated lists, the NOAA arrays and the autofocus positions/HFR pairs, where a cancelled run has fewer readings than positions: making those strict broke `test_tc_foc_090`, which is how the hazard was found).** The `logger.exception` sweep raised `TRY401` (the exception text is now also repeated in the message); those are left as style notes. Console output of the `galileo.commands` tools now includes tracebacks for caught errors.
- **iTelescope FTPS certificate verification, with a settings opt-out.** The FTPS client verifies the certificate and host name by default (`ssl.create_default_context()`); a new *Verify the server's certificate* tick box (Options > Library > Smart Telescopes, stored in the DB settings as `itelescope_verify_tls`, with inline help and a wiki sentence) turns it off.
- **Refactored all ten F-rated functions** (complexity 43–54 → 12–27): `_register_fits_image_internal`, `sync_with_google_cloud_repo`, `_create_master_sigma_clip`, `dwarfFixHeader`, `checkout_single_session`, `checkout_multiple_sessions`, `MergeWidget.execute_merge`, `SessionsWidget.calibrate_session`, `SessionsWidget.show_context_menu` and `MappingsWidget.apply_single_mapping`. Each was split into named helpers with the same steps, order and messages. Where there was no test, a characterisation test was written first and shown to pass on the old code (checkout ×5, merge ×3, session calibration ×2, context menu ×1); `dwarfFixHeader` was additionally checked against the old implementation on 594 header/folder combinations. The `E`-rated functions (11) are untouched.
- **Unused public helpers removed (7):** `create_migration`, `backup_database`, `get_incoming_path`, `check_symlink_support`, `check_windows_developer_mode`, `reset_file_format_processor`, `reset_file_hash_calculator`. The other five from §5a stay because tests and the SDD use them.
- **CI added:** `.github/workflows/quality.yml` — ruff (blocking, changed files only), pip-audit (blocking), bandit and mypy (informational).

**Still open:**
- The files listed above that had uncommitted work in progress (re-run the same fixes once that work is committed).
- Style leftovers ruff cannot auto-fix: `E702` ×14 (`_mount_page.py`), `SIM102` ×9, `G003` ×13, `TRY401` ×233, `RUF007` ×2, `SIM115`/`ASYNC251` in tests; `E712` (`== True` is required by Peewee expressions).
- The Qt `Optional` `union-attr` backlog (~120 mypy errors) and the `ui/library/pages.py` / `metadata.py` / `solve.py` typing notes.
- The 11 E-rated functions, and the near-zero maintainability-index files (split `adapters/indi.py`, `library/services/telescope.py`, the large UI pages).
- Pre-existing test failures unrelated to this review (see Verification).

---

## 1. Verified defects — fix first

### 1.1 `DatabaseError(...)` called with keyword arguments it does not accept — HIGH — ✅ FIXED
- `galileo/library/core/file_processing.py:437, 543, 552` (mypy `call-arg`); 38 occurrences of `file_path=` / `error_code=` in that file.
- `galileo/exceptions.py:96` defines `class DatabaseError(LibraryError): """…"""` with no `__init__`; the chain bottoms out at plain `Exception`, which rejects keyword arguments.
- Failure: any `IntegrityError` or unexpected error while registering a FITS file reaches `raise DatabaseError(msg, file_path=…, error_code="DB_INTEGRITY_ERROR")` and instead raises `TypeError: DatabaseError() takes no keyword arguments`, **masking the real database error** and bypassing the `except (ValidationError, FileProcessingError, DatabaseError)` handling callers rely on. This is an AstroFiler port artefact (AstroFiler's exceptions carried those fields).
- **Resolved:** `LibraryError` now carries `error_code`/`details` (moved up from `AstroFilerError`) and `DatabaseError` also takes `file_path`; regression test `TC-LIB-010` added. mypy `call-arg` errors for `DatabaseError` are gone.
- Original suggestion: give `GalileoError`/`LibraryError` an `__init__(self, message, *, file_path=None, error_code=None, **context)` (keeps current call sites working), or drop the kwargs at the call sites. Add a test that triggers the integrity path.

### 1.2 Undefined names in annotations (missing `TYPE_CHECKING` imports) — MEDIUM — ✅ FIXED
- `galileo/ui/app_window/_current_object.py:63, 76, 91` (`SkyAtlas`, `DeepSkyObject`), `galileo/ui/app_window/_misc_device_pages.py:48` (`ObservatoryScheduler`). ruff `F821`, mypy `name-defined`.
- Harmless at runtime only because of `from __future__ import annotations`; breaks `typing.get_type_hints()`, IDE navigation, and any future runtime use. Add the imports under `if TYPE_CHECKING:` (the first file already imports `TYPE_CHECKING`).

### 1.3 Duplicate dict key — LOW — ✅ FIXED
- `galileo/ui/icons.py:567-568`: `"plugins": _plugins` appears twice (ruff `F601`). Delete one.

### 1.4 `registrar.register_frame` return type is wrong — LOW/MEDIUM — ✅ FIXED
- `galileo/library/registrar.py:51, 78` — mypy `return-value`: `file_id` is `str | Literal[True]` but the signature promises `str | None`. `registerFitsImage` returns `True` in some paths; callers that use the value as a catalog id (e.g. `fitsFile.fitsFileId == file_id`, line 50) would get `True`. Decide the contract of `registerFitsImage` (id or bool) and normalise.

### 1.5 `_calculate_md5_hash` used as a truth value — LOW — ✅ FIXED
- `galileo/ui/library/cloud_sync_dialog.py:377, 558, 587, 607` — `… and _calculate_md5_hash:` (and `is not None` at 393) is always true after a successful import, so the "hash function unavailable" fallback is dead and, if the import fails, `NameError`/`ImportError` would surface at import time (E402 at lines 10, 20 hints the import order was hacked). Replace with a guarded import (`try/except ImportError → _calculate_md5_hash = None`) or drop the dead branches.

### 1.6 `except … : raise` that does nothing — LOW — ✅ FIXED
- `galileo/library/core/file_processing.py:622` (TRY203): handler only re-raises. Delete the `try/except`.

### 1.7 Method called with surplus arguments — ✅ FIXED (the `AppWindowState` protocol stubs for `_prompt_new_observatory` / `_prompt_new_name` were out of date; updated)
- `galileo/ui/app_window/_observatory_pier.py:288, 430` — mypy: "Too many arguments" for `_prompt_new_observatory` / `_prompt_new_name`. Signatures at lines 51/73 *do* accept the arguments, so this is likely a mixin/`self: AppWindowState` typing artefact (the Protocol `AppWindowState` declares different signatures than the mixin methods). Verify the protocol stubs match; if they do not, a call through the protocol is mis-typed.

---

## 2. Probable defects (tool-flagged, need a human look)

| # | Location | Tool | Why it matters |
|---|---|---|---|
| 2.1 ✅ FIXED | `galileo/commands/photometry.py:120` (and the same call in `library/core/__init__.py:247`) | mypy `call-arg` | `convertXisfToFits(..., outputFile=…)` — keyword is not in the callee's signature → `TypeError` on that code path. |
| 2.2 ✅ FIXED | `galileo/ui/star_atlas.py:350` | mypy `override` | `find()` shadows `QWidget.find(int) -> QWidget \| None` with an incompatible signature and return type; any Qt-internal caller expecting the base contract would misbehave. **Fixed:** renamed to `find_object`. |
| 2.3 ✅ FIXED | `galileo/ui/sessions.py:1135` | mypy `method-assign` | Assigning to a method on an instance (`self.screen = …` collides with `QWidget.screen()`). Shadows Qt's `screen()` accessor; **Fixed:** renamed to `sessions_screen`. |
| 2.4 | `galileo/library/core/master_manager.py:1310-1339` | mypy `index` | Indexed assignment on an `object`-typed value (53 mypy errors in this file overall — the worst in the repo). Types are not modelled; likely fine at runtime but untestable by tooling. |
| 2.5 ✅ FIXED | `galileo/ui/app_window/_weather_page.py:329` | mypy `call-arg` | `get_adapter_class(cat)(host=…, port=…)` — `DeviceBackend` declares no `host/port`; concrete adapters probably do. Give the port a typed `__init__` or a factory function so this is checkable. |
| 2.6 | `galileo/library/core/light_calibration.py:353`, `session_processing.py:544`, `variable_star_photometry.py:280`, `enhanced_quality.py:273`, `utils.py:88,110`, `fits_handler.py:44` | ruff `F841` | Computed-and-discarded locals — several suggest logic that was started and never wired up (e.g. `required_folders`, `save_modified`, `newFitsSession`). Review each for a missing use. |
| 2.7 | `galileo/adapters/alpaca.py:90` | ruff `F841` | `results` assigned and unused in the discovery path — possible lost discovery result. |
| 2.8 | `galileo/adapters/alpaca.py:146` | mypy `return-value` | Returns `str \| int` where `str` is promised. |
| 2.9 | `galileo/metadata.py:98`, `galileo/ui/solve.py:419` | mypy `index` | Possible `None`/`int\|str` keys used to index typed dicts → `KeyError`/`None` key. |
| 2.10 ✅ FIXED | `galileo/ui/library/sessions/checkout_workflow.py:76, 82` | mypy `call-arg` | **False positive**: `bias_files`/`dark_files` start as `[]` then become Peewee queries; `.count()` is valid on the query. Fix by annotating, not code. |
| 2.11 ✅ FIXED | `galileo/ui/filter_offsets_dialog.py:167,170`; `ui/library/pages.py:70-75` | mypy | Possibly-`None` widgets returned/stored as non-optional (`QCheckBox \| None`, dict of `None`s) — will crash on first use if the lookup misses. |

---

## 3. Security (bandit + ruff `S`)

| Severity | Finding | Location | Assessment |
|---|---|---|---|
| High (bandit B321/B402) | `ftplib` / plain FTP / FTPS | `galileo/library/services/telescope.py:380, 422, 958, 1006` | Cleartext FTP is **inherent to the target devices** (DWARF, Seestar, StellarMate use unauthenticated FTP). Acceptable, but should be an *explicit, documented* decision: restrict to LAN addresses, never reuse the FTP credentials elsewhere, and use `FTP_TLS` where the device supports it. FTPS path should verify certs (`ssl.create_default_context()`), not unverified contexts. |
| Medium B314 | `xml.etree` parsing | `galileo/safety.py:607` (KML) | Untrusted-XML risk (entity expansion). Use `defusedxml` or reject DTDs if the KML can come from a network/user file. |
| Medium B310 / ruff S310 (13) | `urllib.request.urlopen` with non-literal URLs | `adapters/alpaca.py:215,346,389,392`, `library/core/variable_star_photometry.py:41,42`, others | Validate scheme is `http`/`https` before opening (or move to the already-used `httpx`). No `file://` hardening today. |
| Low B105/B107 (6) | "hardcoded password" | `library/services/telescope.py:45-77`, `library/adapters/ftp.py:21` | **False positives** — they are default *usernames* (`guest`, `stellarmate`) and a `password=''`-style default. Keep, but add `# nosec`/noqa with a reason so they stop alarming. |
| Low S603/S606/S607 (16) | `subprocess` / `os.startfile` with partial paths | `ui/library/images_widget.py:435`, `sessions_widget.py:461`, others | Arguments appear list-form (no `shell=True`). Resolve executables to absolute paths where practical; `startfile` on user-selected paths is acceptable but should reject non-existent/UNC paths. |
| Low S110/S112 | `try/except/pass` | `crashreport.py:123,165`, `timezones.py:29`, `planning/minor_bodies.py:378` | Silent swallow. Acceptable inside a crash reporter; elsewhere log at `debug`. |
| Low S324 | MD5 | `tests/test_lib.py:657` only | Test-only. In product code MD5 is used for file de-dup/cloud sync identity (not security) — pass `usedforsecurity=False`. |
| — | `shell=True`, `eval/exec`, `pickle`, `yaml.load`, SQL string-building | none reported | Good. (Peewee queries are parameterised; not manually audited line-by-line.) |

### 3a. Dependency audit (pip-audit)

`pip-audit` against the project venv (138 installed packages, PyPI/OSV advisory data as of today) reported **No known vulnerabilities found**. Caveats: it audits what is *installed*, not the version ranges in `pyproject.toml`, so it says nothing about older versions a user could resolve; and `galileo` itself (editable install) is not on PyPI and is skipped. pip-audit also warned it was run from inside the venv; I pointed `PIPAPI_PYTHON_LOCATION` at the venv interpreter and got the same result. Recommendation: run it in CI against a fresh install of the lowest-pinned versions as well, and add it to the `dev` extra.

---

## 4. Type safety (mypy)

643 errors, ~95 % in non-test code. By category (galileo/ only): `union-attr` 123, `attr-defined` 108, `assignment` 88, `import-untyped` 67, `call-arg` 50, `arg-type` 46, `misc` 36, `operator` 22, `has-type` 14, rest < 10 each.

Observations:
- **The project is not mypy-clean and CI evidently does not gate on it.** Most volume is Qt `Optional` returns (`QWidget | None`, `layout()`, `statusBar()`, `parent()`) triggering `union-attr` — real-but-low-risk; handle with a small helper or `assert`/early return rather than 120 ad-hoc fixes.
- `import-untyped` (67 + `import-not-found` 5): `astropy`, `httpx` and `sep` have no stubs/are not installed in this environment. `sep` and `httpx` "not found" in the venv means **the environment used here cannot run SEP star detection or the Alpaca adapter** — confirm they are declared in `pyproject.toml` dependencies. Add `[[tool.mypy.overrides]] ignore_missing_imports` for the untyped scientific stack, keep it strict for first-party code.
- Hot-spot files (errors): `library/core/master_manager.py` 53, `ui/app_window/_threads.py` 48, `ui/app_window/_imaging_page.py` 26, `library/core/enhanced_quality.py` 25, `ui/library/sessions/checkout_workflow.py` 24, `ui/help.py` 23, `ui/schedule.py` 20, `ui/app_window/_core.py` 20.
- `mypy` also reports 47 `annotation-unchecked` notes: bodies of unannotated functions (mostly tests) are skipped, i.e. coverage is thinner than the headline count suggests. Consider `check_untyped_defs = true` for `galileo/` after the backlog is cleared.
- `app.py:72` `Invalid self argument "AppWindow"` and the `self: AppWindowState` mixin pattern generate most `attr-defined`/`call-arg` noise: the `AppWindowState` Protocol and the mixin classes drift apart. A single typed Protocol (or a base class) that the mixins share would remove a large share of the errors **and** guards against 1.7.

---

## 5. Lint findings by theme (ruff)

Ranked by value; counts are repo-wide.

### Correctness-relevant
- **Naive datetimes — `DTZ005` ×43, `DTZ003` ×13 (`utcnow`), `DTZ011` ×7, `DTZ001` ×7, `DTZ007` ×7, `DTZ006` ×1 (~78).** The project config itself says this is "a real correctness risk for an app that schedules observations by UTC". Mostly in `galileo/commands/*` and `library/core/*`. `datetime.utcnow()` is deprecated in 3.12 and returns a naive value; replace with `datetime.now(timezone.utc)` and store UTC consistently (AstroFiler-era library code stores local naive time — decide and document the DB convention before bulk-changing).
- **Lost exception context — `B904` ×51** (`raise X` inside `except` without `from`). Mostly `commands/` and `library/`. Add `from e` / `from None`. Same family as 1.1: wrong/masked tracebacks.
- **Logging misuse — `TRY400` ×219** (`logger.error` where `logger.exception` keeps the traceback), `TRY401` ×36 (exception object repeated in `.exception` message), `G003` ×13 (string concat in log call), `G201` ×4. Mostly mechanical; `TRY400` is the single biggest quality gain for field diagnostics.
- **`zip()` without `strict=` — `B905` ×32.** Silent truncation on length mismatch; add `strict=True` where lengths must match (numerical code: WCS, photometry, calibration).
- **`E712` ×41** (`== True/False`): in Peewee `where()` clauses this is *required* (`.is_null()`/`== True` build SQL) — verify before auto-fixing; use `fitsFile.col.is_null(False)` / `.__eq__` or `# noqa: E712` with a note rather than blindly rewriting.
- **`F811` ×40** — 36+ in `tests/test_commands.py` (module imported as `library` and shadowed by fixture/param of the same name): tests may be exercising the fixture, not the module. Rename the fixture.
- **`B007` ×6, `F841` ×32, `RUF059` ×22, `F401` ×24** — dead variables/imports (cf. 2.6). 20 findings auto-fixable with `ruff --fix`.
- **`ASYNC109` ×7 (`timeout` parameter on async functions: `adapters/alpaca.py:321`, `adapters/indi.py:376`), `ASYNC251` ×2 (`time.sleep` in async tests).** Prefer `asyncio.timeout()`; the two test hits block the loop.
- **`B027`** `DeviceBackend.set_property` (`core/devices.py:83`) is an empty method on an ABC without `@abstractmethod`/documented no-op — subclasses silently inherit a do-nothing setter. Make it abstract or raise `NotImplementedError`.
- `E741` ×7 ambiguous names (`l`, `I`), `E731` ×1 lambda assignment, `F601` (1.3).

### Style / hygiene (bulk, mechanical)
- **`W293` ×326 + `W291` ×14** whitespace on blank/trailing lines — concentrated in a handful of ported AstroFiler files. One `ruff format`-style pass (or `ruff check --select W --fix`) removes them. Note: the project does not appear to use `ruff format`; adopt it (or `black`) in CI so ported code converges.
- `SIM*` (SIM105 ×19, SIM102 ×14, SIM108 ×6, SIM103 ×4, …), `RUF015` ×23, `FURB171` ×10, `C408` ×10, `C403` ×9, `C416` ×4, `UP030/UP042/UP035/UP034/UP017/UP037/UP012` (~20), `E702` ×14 (semicolon statements), `E402` ×12 (7 in `tests/`, 3 in `library/` — likely `sys.path` hacks), `TRY002` ×18 (raise bare `Exception` — use `GalileoError` subclasses), `RUF012` ×11 (mutable class attributes needing `ClassVar`), `RUF013` ×3 (implicit `Optional`), `RUF043` ×7 (unescaped regex in `pytest.raises(match=…)`), `UP042` ×7 (`class X(str, Enum)` → `StrEnum`).

---

## 5a. Dead code (vulture)

Run on `galileo/` only (tests excluded, so test-only helpers show as unused). Vulture is name-based; Qt slots/overrides, entry-point plugins, Peewee model fields and `migrations/` are invoked dynamically, so the 60 % tier is mostly noise (234 methods, 82 attributes, 81 variables, 68 classes, 56 functions, 12 properties, 5 imports). Worth acting on:

**≥ 80 % confidence (14) — review each:**
- Unused imports: `library/core/enhanced_quality.py:40-41` (`curve_fit`, `ndimage`), `library/migrations/003_add_mapping_table.py:27` (`pw_pext` — leave: migrations must stay replayable), `library/services/telescope.py:32` (`NotConnectedError`, `NotReadyError`).
- Unused variables: `commands/stack.py:241` (`mode_unstacked`), `equipment/profiles.py:232` (`profile_manager`), `ui/library/mappings_dialog.py:118` (`is_default`), `ui/skymap.py:30` (`datetime_utc`, `magnitude_limit` — unused parameters, check they are not meant to be honoured), `library/exceptions.py:95,117` (`exc_val`, `exc_tb` in `__exit__` — required by protocol, ignore).
- `mappings_dialog.is_default` and `skymap` parameters may be **unfinished features** rather than dead code (same pattern as ruff F841 in §2.6).

**60 % tier, candidates for removal or a test/usage check** (public helpers with no caller inside `galileo/`):
`crashreport.install_loop_handler` / `uninstall_crash_handlers`, `library/config.get_incoming_path`, `library/core/duplicates.files_with_hash` / `verify_integrity`, `library/core/master_manager.check_symlink_support` / `check_windows_developer_mode`, `library/database.create_migration` / `get_migration_status` / `backup_database`, and the `reset_*` singletons. Several of these are plausibly intended for the planned UI/CLI (`backup_database`, `get_migration_status`) — decide keep-or-delete rather than leaving them untested. Add a `vulture` whitelist file for Qt/Peewee false positives if it is adopted in CI. Full list: `vulture galileo --min-confidence 60`.

## 5b. Complexity and maintainability (radon)

- **Cyclomatic complexity:** average **A (3.54)** over all blocks — the codebase as a whole is simple. The debt is concentrated in a tail: 147 blocks at C, 31 at D, **11 at E and 10 at F** (F = CC > 40; effectively untestable).
- **F-rated (refactor first):**

| CC | Function | File |
|---|---|---|
| 54 | `sync_with_google_cloud_repo` | `library/services/cloud.py:323` |
| 53 | `MasterFrameManager._create_master_sigma_clip` | `library/core/master_manager.py:550` |
| 53 | `checkout_single_session` / `checkout_multiple_sessions` | `ui/library/sessions/checkout_workflow.py:42, 270` |
| 51 | `dwarfFixHeader` | `library/core/utils.py:73` |
| 50 | `MergeWidget.execute_merge` | `ui/library/merge_widget.py:161` |
| 49 | `SessionsWidget.calibrate_session` | `ui/library/sessions_widget.py:490` |
| 47 | `FileProcessor._register_fits_image_internal` | `library/core/file_processing.py:589` |
| 45 | `MappingsWidget.apply_single_mapping` | `ui/library/mappings_dialog.py:322` |
| 43 | `SessionsWidget.show_context_menu` | `ui/library/sessions_widget.py:208` |

- **E-rated (CC 31-40)** include `FileProcessor.registerMasters` (40), `GuiderPage.refresh_view` (38), `calibrate_light_frame` (37), `TelescopeDownloadWorker.run` (37), `SessionsWidget._build_resources_status` (37), `create_sessions.main` (35), and 5 more.
- Note the overlap: **every F-rated function and most E-rated ones live in the ported AstroFiler tree (`library/`, `ui/library/`, `commands/`)** — the same code that holds most ruff/mypy findings and the §1.1 bug. `file_processing.py` alone has the bugged `DatabaseError` calls, a no-op `except: raise`, and a CC-47 function.
- **Maintainability index:** 13 modules grade **C** (hard to maintain); six score ~0: `adapters/indi.py`, `library/services/telescope.py`, `ui/guider.py`, `ui/schedule.py`, `ui/star_atlas.py`, `ui/library/sessions_widget.py`; also low: `ui/solve.py` (0.09), `sequencer/session_exec.py` (1.44), `adapters/alpaca.py` (4.4), `platesolve.py` (5.2), `library/core/master_manager.py` (5.0), `ui/sessions.py` (5.0). These are very large single files — split by responsibility (e.g. one INDI adapter module per device category, matching the existing one-class-per-category structure).
- **Size/commenting:** 52.7 k SLOC; comments 9 % of source lines (14 % including docstrings) — healthy.

## 6. Structural observations (not tool output, from what the tools surfaced)

1. **Two code styles coexist.** Ported AstroFiler code (`galileo/library/core/*`, `commands/*`) uses camelCase locals, root-logger calls (the config comment cites 232 `LOG` hits that were presumably fixed or ignored), bare `Exception`, whitespace-only lines, and naive datetimes; native Galileo code is far cleaner. Nearly all of the 1 066 ruff findings and ~⅓ of mypy errors sit in the ported tree. A staged clean-up of `library/core` and `commands` would remove most of the debt.
2. **Mixin + `self: AppWindowState` pattern in `ui/app_window/`** produces most of the typing noise and the F821/1.7 class of issue. Worth consolidating (see §4).
3. **Exception hierarchy is anaemic** (`galileo/exceptions.py` is classes-with-docstrings only) while ported code assumes AstroFiler's richer errors (1.1). Settle the API in one place.
4. **No visible CI gate** for ruff/mypy/bandit (tool config exists, results are far from clean). Suggest: ruff and bandit as blocking on `galileo/` for *new* findings (baseline file), mypy non-blocking until the union-attr backlog is cleared.
5. Per the saved project memory, `galileo/planning`, the sequencer and the scheduler are slated for rework; findings in those paths (e.g. `planning/minor_bodies.py:378`, `sequencer/basic.py:159`) are listed here but low priority.

---

## 7. Suggested order of work

1. §1.1 (`DatabaseError` kwargs) — add test, fix hierarchy.
2. §1.2–1.6 and §2.1 — small, local, high-confidence fixes.
3. `ruff check --fix` for the 20 auto-fixable items, then a whitespace pass (W291/W293) as its own commit.
4. `B904`, `TRY400`, `B905`, `F841`/`F401` sweeps (mechanical, reviewable).
5. Datetime policy decision, then DTZ sweep.
6. Security: KML parsing (`defusedxml`), URL scheme validation, document the FTP decision, `usedforsecurity=False` on MD5.
7. Typing: fix the `AppWindowState` Protocol drift, add mypy overrides for untyped third-party libs, then burn down `union-attr`.
8. Dead code (§5a): delete confirmed-unused imports/variables; decide keep-or-delete for the unused public helpers.
9. Break up the F-rated functions (§5b), starting with those already touched by earlier fixes (`file_processing.py`, `checkout_workflow.py`), with tests first.
10. Add `pip-audit`, `vulture`, `radon` to the `dev` extra (not yet in `pyproject.toml`) and wire all six tools into CI.

## Appendix — reproduce

```
ruff check . --statistics
ruff check . --output-format concise
mypy .
bandit -r galileo -f json -o bandit.json
pip-audit
vulture galileo --min-confidence 80
radon cc galileo -a -nc -s ; radon mi galileo -s -n C ; radon raw galileo -s
```
Raw outputs were written to the session scratchpad and are not committed.
