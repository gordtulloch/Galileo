# Galileo Code Review

**Date:** 2026-09-25
**Commit reviewed:** `d96ede8` (main)
**Tools:** ruff 0.16.8, mypy 2.3.1, bandit 1.9.4, pytest 9.1.1 + pytest-cov, pip-audit

This review runs the full lint/type/security/test/dependency toolchain against the repository as
it stands and reports what each tool actually found. It does not re-derive architecture from
`docs/` — see `docs/SDD.md` for that — it only reports defects and gaps.

## How to reproduce

```bash
pip install -e ".[test,dev]"      # was failing — see Finding 5 (fixed)
pip install bandit pytest-cov pip-audit
ruff check .
mypy . --ignore-missing-imports
bandit -r galileo
pytest -m "not soak and not hardware and not integration" --cov=galileo --cov-report=term-missing
pip-audit
```

## Summary

| Tool | Result |
|---|---|
| ruff | Originally **2,127 findings** under no config (ruff's out-of-the-box defaults). A project-tuned `[tool.ruff]` config was added (Finding 14) and `--fix` run against it: **4,007 of 5,422 auto-fixed**, **1,415 remained** needing manual judgment. Findings 10 (232 `LOG015`) and 12 (all `E722`/`S110`/`S112`) fixed by hand since: **1,114 remain** |
| mypy | Originally **665 errors** in 49 of 225 checked files; heavily concentrated in `galileo/ui/app_window.py` (238) and `galileo/library/core/master_manager.py` (76). Finding 8 fixed all 34 in `galileo/core/devices.py`: **623 remain** in 48 files |
| bandit | Originally **88 findings** (27 High, 10 Medium, 51 Low); Findings 2, 6, and 7 fixed the 3 real shell-injection sites, the disabled SSH host-key check, and all 15 weak-hash findings: **80 remain** (7 High, 10 Medium, 63 Low — the Low increase is the argument-list `subprocess.run` calls that replaced the `shell=True`/`os.system` sites, themselves lower-severity "partial path"/no-`shell=True` notes, not new injection risk) |
| pytest | **697 passed, 13 failed** (304s) under the CLAUDE.md-documented fast filter — Findings 1, 3, and 4 fixed since, now **706 passed, 7 failed, 1 skipped, 6 deselected** (the 7 remaining are the pre-existing "unimplemented feature" gaps listed below, not regressions) |
| coverage | **57%** overall (`--cov=galileo`); domain-core modules (`sequencer`, `core.devices`, `safety`, `meridianflip`) mostly 70–100%, but several `galileo.library.services`/`galileo.ui.library` modules are under 20% |
| pip-audit | **0 vulnerabilities** in the project's actual runtime dependencies; only the ambient `pip` tool itself is flagged (pre-existing venv tooling, not a project dependency) |

---

## Critical findings

### 1. ~~A cross-migration `migrator.orm[...]` reference breaks upgrades from any database that already has migration 013 applied~~ — Fixed

**Status: fixed.** `galileo/library/migrations/017_add_autofocus_and_solver_settings.py` now
creates both tables via `migrator.sql(...)` (matching migration 015's established pattern for
this exact problem) instead of `migrator.create_model` + `migrator.orm["piers"]`, so it no longer
depends on migration 013 having run in the same batch. Verified: the generated schema is
byte-for-byte identical to what `create_model` produced before (dumped via `sqlite_master`), the
four previously-failing RTM tests now pass (`test_tc_lib_010_existing_database_upgrades_in_place[013]`,
`test_tc_lib_010_galileo_tables_created_before_migrations_are_kept`,
`test_tc_img_110_existing_device_configs_table_gains_the_bayer_column`,
`test_tc_prof_100_existing_optical_tubes_table_gains_the_name_column`), and the full fast test
suite went from 697 passed/13 failed to 701 passed/9 failed (the remaining 9 are the separate,
already-documented issues below — Findings 3 and 4, and the "unimplemented feature" gaps).

Original finding, for reference:

`galileo/library/migrations/017_add_autofocus_and_solver_settings.py:16,31` does:

```python
pier = pw.ForeignKeyField(column_name="pier_id", field="id", model=migrator.orm["piers"], ...)
```

`migrator.orm` (`peewee_migrate.migrator.ORM`) is an **in-memory registry populated only by
`create_model` calls that actually execute during the current migration run** — it is not built
from the live database schema. It starts empty for every `run_migrations()` call
(`.venv/Lib/site-packages/peewee_migrate/migrator.py:34`,`64`). `"piers"` is registered by
migration `013_create_galileo_tables.py`. As long as 013 and 017 run in the *same* batch — e.g. a
brand-new database — this works. But once 013 has already been applied and recorded in
`migratehistory` (the normal case for any existing installation being upgraded to a release that
adds 017+), 013 is skipped on the next run, `migrator.orm["piers"]` is never populated, and 017
raises `KeyError: 'piers'`, which `galileo/library/database.py:85` wraps and re-raises as
`DatabaseError: Failed to run migrations: 'piers'` — **the database fails to open at all**.

This is not a test artifact: four RTM tests reproduce it directly by upgrading a database with
only some migrations applied, exactly the scenario CLAUDE.md's persistence-unification and
"AstroFiler databases open unchanged" guarantees are meant to cover:

- `tests/test_lib.py::test_tc_lib_010_existing_database_upgrades_in_place[013]`
- `tests/test_lib.py::test_tc_lib_010_galileo_tables_created_before_migrations_are_kept`
- `tests/test_img.py::test_tc_img_110_existing_device_configs_table_gains_the_bayer_column`
- `tests/test_optics_page.py::test_tc_prof_100_existing_optical_tubes_table_gains_the_name_column`

A brand-new install is unaffected (verified directly — `init_db()` on an empty path succeeds,
since 013 and 017 run together), which is why this hasn't shown up as an obvious smoke-test
failure. But any user who already has a Galileo database from before migration 017 shipped, and
any AstroFiler user whose database only ever reached migration 012, will hit this on upgrade.

**Fix:** don't reference `migrator.orm["piers"]` for a table created by an earlier, independently-
recorded migration. Either look the FK model up against the live `database` (peewee's normal
`Model` classes, not the migrator's transient registry) or declare the FK as a plain
`pw.IntegerField(column_name="pier_id")` plus an `add_index`, which is what migrations 013 itself
does correctly for tables it creates *within its own function* (013's own `migrator.orm[...]`
uses are safe because they reference models created earlier in the very same `migrate()` call, not
across migration boundaries — 017 is the only migration in the tree that reaches back into a
different migration's registration).

### 2. ~~Three shell-injection sites via unescaped filenames in `os.system(f'... "{path}"')`~~ — Fixed

**Status: fixed.** All three sites now build the argument list explicitly and never pass through a
shell: `images_widget.py` and `sessions_widget.py` use `subprocess.run(["open"|"xdg-open", path], check=False)`
in place of `os.system(f'...')`, and `checkout_files.py`'s `mklink` call uses
`subprocess.run(["cmd", "/c", "mklink", dest_path, src_path], ...)` (no `shell=True`) in place of
the interpolated `mklink "{dest}" "{src}"` string. A quote or shell metacharacter in a filename can
no longer break out of the command. Verified: `bandit` no longer reports `B602`/`B605`
(shell-injection) on any of the three files — the only remaining bandit hits there are unrelated,
already-tracked findings (Finding 7's MD5 hash, Finding 12's `try/except/continue`, and low-severity
`B603`/`B607` "partial path" notes that are expected for invoking `open`/`xdg-open` by name).

Original finding, for reference:

Confirmed real, not bandit noise — the same vulnerable pattern is duplicated in three places, all
reachable from "open this file in the OS's default viewer":

- `galileo/ui/library/images_widget.py:543,545`
- `galileo/ui/library/sessions_widget.py:467,469`
- `galileo/ui/library/sessions/checkout_files.py:132-137` (Windows `mklink` via `subprocess.run(f'mklink "{dest}" "{src}"', shell=True, ...)`)

```python
os.system(f'open "{filename}"')       # macOS
os.system(f'xdg-open "{filename}"')   # Linux
```

`filename`/`dest_path`/`src_path` come from the FITS library catalog — paths that can originate
from imported files, cloud sync, or smart-telescope SMB/FTP shares, i.e. not fully trusted input.
A filename containing a double quote followed by shell metacharacters (`foo"; rm -rf ~ #.fits`,
or backticks/`$()`) breaks out of the quoting and executes arbitrary shell commands the moment a
user opens that file from the Images/Sessions screen. The Windows branch (`os.startfile`) is safe
because it doesn't go through a shell; only the POSIX `os.system` calls and the Windows `mklink`
`shell=True` call are affected.

**Fix:** use `subprocess.run(["open", filename])` / `subprocess.run(["xdg-open", filename])`
(list form, no `shell=True`) instead of `os.system(f'...')`. For `mklink`, either request Windows
symlink privilege and call `os.symlink()` (works cross-platform since Python 3.8, including
Windows with Developer Mode or elevation) or invoke `subprocess.run(["cmd", "/c", "mklink", dest, src])` without a shell.

### 3. ~~`galileo.current_object`'s process-wide singleton has no per-test/per-session reset, causing order-dependent failures~~ — Fixed

**Status: fixed.** Added an autouse `_reset_current_object_store` fixture in `tests/conftest.py`
that clears `galileo.current_object._default_store` before and after every test. Verified:
`test_tc_plt_070_capture_and_solve_fills_the_screen` now passes as part of the full suite (was
previously only passing in isolation).

Production stale-state risk reassessed: every call site that reads/writes the store
(`app_window.py:396,412,4529`, `solve.py:579`) passes `self._current_pier`, which is always a Pier
loaded from the database via `_load_observatories()` before it can be selected in the UI — so in
practice it always has a DB id by the time `current_object` code runs, and the name-fallback
collision case (two same-named, still-unsaved Piers) isn't reachable through the app's own UI
flow today. Leaving `pier_key()`'s name fallback as-is; flagging it here for awareness if a future
code path ever calls into `current_object` with an unsaved Pier.

Original finding, for reference:

`galileo/current_object.py:86-94` keeps the "current object per Pier" store in a module-level
`_default_store` singleton keyed by `pier_key()` (the Pier's DB id, or its name when it has none).
Nothing clears this between test runs, and `tests/test_solve_page.py::test_tc_plt_070_capture_and_solve_fills_the_screen`
fails only when run as part of the full suite, not in isolation (verified: passes alone, fails in
the full run) — a leftover "current object" from an earlier test with a colliding Pier id bleeds
into this test's `SolveWorkflow.target`, producing a wildly wrong `d_ra_arcsec`
(`275428.29` vs the expected `~33.8`).

Beyond the test flakiness this exposes, the same mechanism is a real risk in the running app: Pier
ids are SQLite autoincrement integers, and `pier_key()` falls back to the Pier's *name* when it has
no id, so two different Piers can share a key (e.g. a deleted-and-recreated Pier reusing an id, or
two same-named Piers across Observatories before either is saved). When that happens, Capture &
Solve would silently slew or report error offsets against the wrong Pier's last-selected object.

**Fix:** add an autouse test fixture that resets `galileo.current_object._default_store` between
tests (mirroring how `tests/conftest.py` already resets the event bus and catalog cache), and
consider whether `CurrentObjects` should be constructed per `Pier` foreign-key identity rather than
falling back to name.

### 4. ~~`LOG-050`'s "reset each run" log requirement is not actually implemented~~ — Fixed

**Status: fixed.** `galileo/diagnostics.py`'s `DiagnosticsService.__init__` already opened the file
with `mode="w"`, but only when *no* `FileHandler` for that day's file existed yet on the root
logger — when one already did (a second `DiagnosticsService` pointed at the same datestamped file,
e.g. simulating a restart within one process, as the RTM test does), it silently reused that
existing handler instead, which meant no truncation happened and the first run's messages stayed.
Fixed by always removing and closing any existing handler(s) for that file and opening a fresh
`mode="w"` handler, so every `DiagnosticsService` construction truncates regardless of what ran
before it in-process. Verified: `test_tc_log_050_log_file_resets_each_run_rather_than_appending`
now passes.

Original finding, for reference:

`tests/test_log.py::test_tc_log_050_log_file_resets_each_run_rather_than_appending` fails:
a second `DiagnosticsService` pointed at the same datestamped log file still contains the first
run's messages. The log file is opened in append mode rather than truncated at start-up, so
`LOG-050` (SRS) is not met — restarting the app does not give a clean per-run log as documented.

---

## High-severity findings

### 5. ~~`pip install -e ".[test,dev]"` fails outright — the documented install command in CLAUDE.md doesn't work~~ — Fixed

**Status: fixed.** Added `[tool.setuptools.packages.find]` with `include = ["galileo*"]` to
`pyproject.toml`, so setuptools no longer tries to guess which of `html/`, `logs/`, `assets/`,
`plugins/`, and `galileo/` is "the" package. Verified in a clean, disposable venv:
`pip install --no-deps -e .` now succeeds and `import galileo` resolves to
`galileo/__init__.py` in the repo, confirming the editable install actually wires up the real
package rather than silently doing nothing.

Original finding, for reference:

```
error: Multiple top-level packages discovered in a flat-layout: ['html', 'logs', 'assets', 'galileo', 'plugins']
```

setuptools' automatic package discovery sees `html/`, `logs/`, `assets/`, and `plugins/` sitting
next to `galileo/` at the repo root and refuses to build, because none of them declares itself as
a package and setuptools can't tell which of the five is "the" package. `pyproject.toml` has no
`[tool.setuptools.packages.find]` (or equivalent `include`/`exclude`) to disambiguate. This means
the exact command CLAUDE.md tells contributors to run does not work today; anyone following it hits
a build error before writing a line of code. (This review worked around it by installing the
dependency list directly and relying on `galileo/` being importable from the repo root — which is
why `pytest` still runs fine — but `pip install -e .` itself is broken.)

**Fix:**
```toml
[tool.setuptools.packages.find]
include = ["galileo*"]
```

### 6. ~~Paramiko SFTP client trusts any unknown host key (`AutoAddPolicy`)~~ — Fixed

**Status: fixed.** `galileo/library/adapters/sftp.py` now calls `client.load_system_host_keys()`
and sets `paramiko.WarningPolicy()` instead of `AutoAddPolicy()` — the "at minimum" option this
finding itself named, since this code path runs headless (no UI thread available to prompt for
trust-on-first-use) and a strict `RejectPolicy` would break every LAN telescope/server this
adapter is meant to reach on first connect. An unknown host key is still accepted, but now through
paramiko's own warning-log path rather than silently, so key rotation or an unfamiliar host is at
least visible instead of leaving zero trace. Verified: `test_tc_ext_120_sftp_remote_telescope_retrieval`
still passes.

Original finding, for reference:

`galileo/library/adapters/sftp.py:40`:
```python
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```
Any host key is accepted and silently cached on first connect — no warning on key rotation, no
pinning, no verification against a known-hosts file. For a LAN-only "smart telescope" use case the
practical MITM risk is low, but this is a genuine, easy-to-fix gap (`RejectPolicy` + an explicit
known-hosts/trust-on-first-use flow, or at minimum `WarningPolicy` plus logging) rather than
something to leave as `AutoAddPolicy` indefinitely.

### 7. ~~Weak hashes (MD5/SHA1) used without `usedforsecurity=False`~~ — Fixed

**Status: fixed.** All 15 call sites (13 MD5 + 2 SHA1) across `light_calibration.py`,
`telescope.py`, `file_hash_calculator.py`, `masters.py`, `cloud.py`, `sessions_widget.py`, and
`sessions.py` now pass `usedforsecurity=False`, documenting that each use is file-content
deduplication/verification or deterministic UI color assignment, never a security boundary.
Verified: `bandit -r galileo` no longer reports any `B324` findings, and the library/sessions test
files covering these code paths (`test_lib.py`, `test_ses.py`, `test_ext.py`) still pass in full.

Original finding, for reference:

13 MD5 + 2 SHA1 call sites (bandit B324), e.g. `galileo/ui/library/sessions_widget.py:768` and
`galileo/ui/sessions.py:487`. In both sampled cases the hash is used for file-content
deduplication or deterministic UI color assignment — not a security boundary — so this is mostly a
false-positive-by-intent from bandit's perspective, but it's a one-line fix per site
(`hashlib.md5(data, usedforsecurity=False)`) that removes the noise and documents intent for the
next reader. Worth sweeping in one pass rather than leaving 15 instances for bandit to keep
flagging.

### 8. ~~`galileo.core.devices` — the project's own "port interface" boundary — doesn't type-check against its declared members~~ — Fixed

**Status: fixed.** Added ten `Protocol` classes (`_CameraBackend`, `_MountBackend`,
`_FilterWheelBackend`, `_FocuserBackend`, `_RotatorBackend`, `_FlatPanelBackend`,
`_WeatherBackend`, `_DomeBackend`, `_SafetyMonitorBackend`, `_SwitchBackend`) declaring exactly
the category-specific members each `*Controller` calls on its `self._backend` — not mixed into
`DeviceBackend`'s own class hierarchy (an ABC and a `Protocol` can't share a base-class list), just
standalone structural types. Each `*Controller` method now narrows `self._backend` to the matching
Protocol via `typing.cast(...)` immediately before the category-specific call — `cast()` is a
type-checker-only no-op at runtime, so this is a pure typing change with zero behavior difference;
any real adapter (INDI, Alpaca, a plugin) that implements the category's methods already satisfies
the Protocol structurally, no explicit registration needed. Separately, `DeviceBackend` gained a
`device_type: str` annotation-only class attribute (matching the existing `backend: str =
"unknown"` declaration) since every concrete adapter already sets it in `__init__` and
`DevicePool.register`'s `backend.device_type` lookup was the one error not tied to a specific
category. Verified: `mypy galileo/core/devices.py` goes from 34 errors to **0**, the project-wide
mypy error count drops from 665 to **623**, `ruff check` on the file shows no new findings (the 7
remaining are pre-existing, unrelated `DTZ003` `datetime.utcnow()` notes), and
`test_arch.py`/`test_eqp.py`/`test_foc.py`/`test_mflip.py` (77 tests covering this exact
abstraction layer) all still pass.

Original finding, for reference:

`galileo/core/devices.py` is SDD's device-category port-interface module (`ARCH-*`). mypy reports
34 errors in it, nearly all of the same shape:

```
galileo\core\devices.py:245: error: "DeviceBackend" has no attribute "start_exposure"  [attr-defined]
galileo\core\devices.py:291: error: "DeviceBackend" has no attribute "park"  [attr-defined]
galileo\core\devices.py:523: error: "DeviceBackend" has no attribute "set_switch"  [attr-defined]
... (34 total, one per category-specific backend method)
```

`DevicePool`/dispatch code is typed against the generic `DeviceBackend` base class but calls
methods that only exist on the category-specific subclasses (camera, mount, focuser, dome, ...).
Since this is exactly the module the architecture doc calls out as the port-interface boundary
that plugins and adapters are supposed to satisfy structurally, having mypy unable to verify calls
against it undercuts the one mechanical check that boundary could get for free. Either give
`DeviceBackend` a `Protocol`/`overload`-based per-category interface, or type these call sites
against the specific subclass rather than the base.

---

## Medium-severity findings

### 9. `galileo/ui/app_window.py` is a 7,857-line god-file responsible for 238 of the 665 mypy errors

No single behavioral bug is being claimed here, but the file's size is itself a maintainability
risk independent of what mypy reports in it: it mixes window chrome, per-device-category dialog
logic, Pier/Observatory CRUD, and multiple unrelated dialogs in one module. A large fraction of its
mypy errors are real (`Name "SkyAtlas" is not defined`, `Argument 1 to "list_piers" has
incompatible type "None"; expected "ObservatoryRecord"`, `Item "None" of "SignalInstance | None"
has no attribute "connect"`) rather than PySide6 stub noise (see Finding 11) — but at this size,
signal-to-noise for anyone reviewing new mypy output from this file is poor. Splitting device-
category dialogs and Pier/Observatory management out of `app_window.py` into their own modules
(mirroring how `galileo.ui.library`, `galileo.ui.sessions`, etc. already are separate) would both
shrink the blast radius of the `Name not defined` / `Argument ... incompatible type "None"` bugs
already in there and make mypy's signal usable again.

### 10. ~~`galileo.commands.auto_calibration` / `galileo.library.core.auto_calibration` log through the root logger, not a module logger~~ — Fixed

**Status: fixed.** Every one of the 232 `logging.<level>(...)` root-logger call sites now goes
through a module-level `logger = logging.getLogger(__name__)` instead — the four concentrated
files (`galileo/commands/auto_calibration.py`, `galileo/library/core/auto_calibration.py`,
`galileo/commands/cloud_sync.py`, `galileo/commands/register_existing.py`) plus 5 more scattered
single-site occurrences (`galileo/commands/load_repo.py`, `galileo/library/services/telescope.py`,
3 in `galileo/ui/library/duplicates_widget.py`) that a full-repo sweep turned up beyond the four
the review sampled. Each command-line script's own `setup_logging()` (which configures the root
logger's handlers/level via `logging.basicConfig`) is untouched — only the plain log-level calls
(`logging.info`/`.warning`/`.error`/`.debug`/`.exception`/`.critical`) were retargeted at a module
logger, so these modules can now be filtered/leveled/routed independently and their output carries
the module name like every other logger in the codebase. Verified: `ruff check --select LOG015`
now reports zero findings repo-wide, and the test files covering these modules
(`test_lib.py`, `test_ext.py`, `test_vst_an.py`) still pass in full.

Original finding, for reference:

232 `logging.<level>(...)` module-level (root-logger) calls (ruff `LOG015`), concentrated almost
entirely in four files:

| File | Count |
|---|---|
| `galileo/commands/auto_calibration.py` | 106 |
| `galileo/library/core/auto_calibration.py` | 76 |
| `galileo/commands/cloud_sync.py` | 25 |
| `galileo/commands/register_existing.py` | 20 |

Calling `logging.warning(...)`/`logging.info(...)` directly (rather than
`logger = logging.getLogger(__name__)`) means these modules can't be filtered, leveled, or routed
independently of the root logger, and their output won't carry the module name other loggers in
the codebase get. Not urgent, but a mechanical fix (`logging.getLogger(__name__)` + a sed-style
replace) that removes 232 of the 2,127 ruff findings in one pass.

### 11. mypy noise from PySide6's enum re-scoping dwarfs real findings

A large share of the "attr-defined" category (`Qt.AlignCenter`, `QDialogButtonBox.Ok`,
`QDialog.Accepted`, etc. — well over 100 occurrences across `app_window.py`, `focus.py`, `solve.py`,
`guider.py`, `star_atlas.py`) is PySide6 stub/runtime mismatch: newer PySide6 stubs only expose
these under their nested enum class (`Qt.AlignmentFlag.AlignCenter`) even though the flat,
un-nested form the code uses still works at runtime in current PySide6. This is not a bug in the
code, but it means mypy's signal on `galileo.ui.*` is currently mostly noise, which is exactly what
let real errors (Finding 9's `Name not defined`, `arg-type` mismatches) go unnoticed. Either add a
`mypy` per-module override that silences `attr-defined` for known-safe Qt enum access, or bite the
bullet and switch to the nested enum spellings project-wide — either way, something should be done
so the real 30–40% of `galileo/ui/*`'s mypy output isn't buried under Qt stub noise.

### 12. ~~`try/except: pass` and bare `except:` (33 sites) silently swallow errors~~ — Fixed

**Status: fixed.** Every silent site is fixed, in two passes:

- The 19 bare `except:` sites (ruff `E722` — concentrated in `light_calibration.py`,
  `telescope.py`, `enhanced_quality.py`, `cloud_sync_dialog.py`) are narrowed to
  `except Exception:`, so a `KeyboardInterrupt`/`SystemExit` can no longer be swallowed by one of
  these blocks — a real behavior improvement, not just style.
- All 33 `try/except/pass` (`S110`) and `try/except/continue` (`S112`) sites that logged nothing
  now call `logger.debug(..., exc_info=True)` (or, for `galileo/platesolve.py:288`'s failed
  temp-FITS write — whose failure would surface confusingly downstream as a solve failure —
  `logger.warning`) with a message specific to what was being attempted, mirroring the message
  style already used by sibling `except` blocks in the same functions (e.g. `alpaca.py`'s
  "Could not read X from %s" pattern). Deliberately-defensive sites (optional ASCOM properties,
  best-effort hash/metadata reads) keep their original silent-*behavior* — they still don't raise
  or change control flow — they just no longer log nothing. A handful of target files had no
  module-level `logger` yet (`photometry.py`); one was added rather than reusing `logging.<level>`
  directly, consistent with Finding 10's fix.

Verified: `ruff check --select E722,S110,S112` now reports zero findings repo-wide, all touched
files parse cleanly, and the full fast test suite still passes with no new failures.

Original finding, for reference:

Ruff/bandit: 26 `try/except/pass` (bandit B110), 7 `try/except/continue` (B112), plus 20 bare
`except:` (ruff E722) — e.g. `galileo/ui/theme.py:249` swallows any exception loading the saved
theme with no log line at all. Several of these are deliberately defensive (best-effort catalog
downloads, optional-feature probing) and are fine as-is, but a silent `except: pass` with zero
logging makes a real failure indistinguishable from "feature not present" when someone's
debugging a report. Worth an audit pass to add at least a `logger.debug(..., exc_info=True)` to
the ones that currently log nothing.

### 13. FTP (plaintext) used for smart-telescope sync — Reviewed, accepted as unavoidable

**Status: reviewed, not changed.** Confirmed against `galileo/library/services/telescope.py`'s
`supported_telescopes` table: the DWARF 3 entry is hard-configured with `'protocol': 'ftp'` (no
FTPS option), while iTelescope (a real internet-reachable, not LAN-only, target) already uses
`'protocol': 'ftps'` — so this codebase already applies TLS everywhere it's available, and plain
FTP is specifically the DWARF 3 hardware's own constraint, not an oversight. Switching it would
mean dropping support for that device, which is a product decision, not a code fix; left as-is,
matching the original finding's own "flagging for awareness rather than as a required fix"
framing.

Original finding, for reference:

`galileo/library/services/telescope.py:363,941` and `galileo/library/adapters/ftp.py` use
`ftplib.FTP()` — unencrypted control and data channels. This is very likely dictated by the
hardware (several consumer smart telescopes only expose plain FTP, not FTPS/SFTP, on their local
AP), which the LAN-only device-discovery model (`zeroconf`, `.local` mDNS) in this project already
assumes — so this may not be fixable without dropping support for those devices. Flagging for
awareness rather than as a required fix: if any of the FTP targets are ever reachable over
something other than a trusted LAN, credentials and file contents cross in the clear.

### 14. ~~No ruff configuration exists in the repository~~ — Fixed

**Status: fixed.** `pyproject.toml` now has an explicit `[tool.ruff]`/`[tool.ruff.lint]` config
with a curated `select` list (tied to the categories this review actually found real instances of:
`B`, `SIM`, `C4`, `RUF`, `DTZ`, `LOG`, `G`, `ASYNC`, `TRY`, `PIE`, `FURB`, `S`, plus the `E`/`F`/`W`/`UP`
baseline), a short `ignore` list for rules that fight this codebase's established style rather than
finding real defects (`G004` — f-strings in logging is the existing convention; `RUF001-003` —
this app deliberately prints `″`/`°`/em dashes in user-facing strings; `TRY300`/`TRY301`/`TRY003` —
pure control-flow restructuring with no behavior change), and a `tests/**/*.py` override for
`S101`/`S105-107` (assert and fake fixture credentials are normal pytest idiom, not findings). Ran
`ruff check . --fix` (safe fixes only, no `--unsafe-fixes`) against that config: **4,007 of 5,422
findings auto-fixed** across 151 files (mostly whitespace, `Optional[X]`/`List[X]`→`X | None`/`list[X]`
modernization, unused imports, redundant f-strings), verified with a full test-suite run before/after
(701 passed/9 failed both times — the 9 are the pre-existing, already-documented failures, nothing
newly broken). One fix *was* wrong and got corrected by hand: F401 stripped
`from galileo.core.monitor import ConnectionMonitor` from `galileo/core/devices.py`, which is a
deliberate re-export (marked by a comment, not `__all__`) that ruff's unused-import check can't
see — restored using the `import X as X` explicit-re-export convention so it won't be stripped
again. 1,415 findings remain and need manual judgment (bare `except:`, `try/except/pass`, the 232
`LOG015` root-logger calls, etc.) — none of those are auto-fixable by design.

Original finding, for reference:

There is no `pyproject.toml [tool.ruff]` section, `ruff.toml`, or `.ruff.toml` anywhere in the
tree, despite `ruff` being a declared dev dependency and `ruff check .` being the documented lint
command. `ruff check .` is therefore running under whatever ruff 0.16's shipped defaults happen to
be — which, in this version, select far more than the classic `E`/`F` set (`UP`, `DTZ`, `S`, `SIM`,
`TRY`, `RUF`, `PIE`, `C4`, `PLR`, `FURB`, `ASYNC`, `G`, `TC` all fired). That's how the 2,127-finding
count in this review arose; a different ruff version or a machine with a different ruff default
could report a very different number for the same code, and CI (if any exists) has nothing pinning
which rules actually gate a merge. Add an explicit `[tool.ruff]`/`[tool.ruff.lint]` `select`
(or `extend-select`) list so the lint surface is a deliberate, versioned decision rather than
whatever ruff ships next.

---

## Test suite detail

Run: `pytest -m "not soak and not hardware and not integration" --cov=galileo` — **697 passed, 13
failed, 1 skipped, 6 deselected** in 304.78s.

### Failures already covered above
- ~~`test_tc_lib_010_existing_database_upgrades_in_place[013]`, `test_tc_lib_010_galileo_tables_created_before_migrations_are_kept`, `test_tc_img_110_existing_device_configs_table_gains_the_bayer_column`, `test_tc_prof_100_existing_optical_tubes_table_gains_the_name_column`~~ → Finding 1 (migration bug) — **fixed**, all four now pass
- ~~`test_tc_log_050_log_file_resets_each_run_rather_than_appending`~~ → Finding 4 — **fixed**
- ~~`test_tc_plt_070_capture_and_solve_fills_the_screen`~~ → Finding 3 (test-order dependency) — **fixed**

### Failures that are unimplemented features, not regressions
These all fail with `AttributeError`/`hasattr()` on a class or method that simply doesn't exist
yet, each backing an MVP/P2/P3-tagged RTM requirement. Listed here for visibility since CLAUDE.md
asks that `README.md`'s Status section reflect what's actually implemented — these six suggest the
Status section (or these tests' priority) may need reconciling with reality:

| Test | Missing |
|---|---|
| `test_tc_ext_110_simbad_coordinate_lookup` | `galileo.planning.sky_atlas.SimbadClient` |
| `test_tc_log_060_recent_log_pane_on_equipment_screens` | `galileo.diagnostics.RecentLogPane` |
| `test_tc_notif_020_external_delivery_via_email_and_sms` | `galileo.notify.EmailChannel` |
| `test_tc_notif_030_per_event_per_channel_enable_disable` | (same, `EmailChannel`) |
| `test_tc_notif_040_reads_contact_details_from_owning_observatory` | `Observatory.set_contact_details` |
| `test_tc_obs_090_observatory_carries_operator_contact_details` | `Observatory.contact_details` |
| `test_tc_vst_ext_010_aavso_target_tool_and_vsp_apis` | `galileo.plugins.vstarget.planning.AavsoVspClient` |

### Coverage gaps worth flagging

Overall line coverage is 57%. Domain-core modules generally test well
(`galileo.core.devices` 93%, `galileo.sequencer.basic` 92%, `galileo.safety` 83%,
`galileo.meridianflip` 100%), consistent with the ports-and-adapters design making them easy to
exercise with mocks. The weak spots cluster in two places:

- **Cloud/network service adapters**: `galileo/library/services/telescope.py` 6%,
  `galileo/library/services/cloud.py` 10%, `galileo/library/services/gcs.py` 10%,
  `galileo/library/adapters/{ftp,sftp,smb}.py` 22–27%. These are exactly the modules Finding 13's
  FTP usage and Finding 6's paramiko host-key issue live in — the parts of the codebase with the
  least test coverage are also the parts touching external network protocols, which is the
  opposite of where you'd want coverage concentrated.
- **Several Library UI dialogs are at or near 0%**: `auto_calibration_dialog.py` (0%),
  `checkout_files.py`/`checkout_workflow.py`/`masters_resolver.py` (0%), `download_dialog.py` (10%),
  `cloud_sync_dialog.py` (14%), `merge_widget.py` (23%). `checkout_files.py` is where Finding 2's
  `mklink shell=True` injection lives — again, an untested file turned out to have a real bug.

---

## Dependency audit (pip-audit)

Clean: **0 known vulnerabilities** in any of the project's declared runtime dependencies (numpy,
astropy, PySide6, peewee, requests, paramiko, keyring, scipy, matplotlib, reproject, lz4, pysmb,
google-cloud-storage, qasync, zeroconf, sep, Pillow, astroalign, photutils, astroquery, pandas,
peewee-migrate), installed fresh from the versions `pyproject.toml` currently pins. The only
flagged package is `pip` itself (10 CVEs against pip 25.3, fixed in 26.0–26.2) — that's the ambient
package manager in the virtualenv this review built, not a project dependency, and isn't something
`pyproject.toml` controls.

Note: because Finding 5 (`pip install -e .` failing) meant the project couldn't actually be
installed, the first `pip-audit` run only saw the review's own dev tools and reported nothing
useful. The dependency list was installed directly from `pyproject.toml`'s `dependencies` array to
get a real audit — worth being aware of if this is ever re-run without fixing Finding 5 first, since
a naive `pip-audit` in an environment where the install failed silently audits the wrong thing.

---

## Suggested priority order

1. ~~Fix the migration-017 FK bug (Finding 1)~~ — **done.**
2. ~~Fix the three shell-injection sites (Finding 2)~~ — **done.**
   (~~Add a ruff config and run `--fix`, Finding 14~~ — **done** — separate from, and much lower
   stakes than, the shell-injection fix.)
3. ~~Fix `pip install -e .` (Finding 5)~~ — **done.**
4. ~~Add the `current_object` test-isolation fixture (Finding 3)~~ — **done.**
5. ~~Fix the log-reset bug (Finding 4)~~ — **done.**
6. Everything else is cleanup/hardening. (~~Paramiko `AutoAddPolicy` (Finding 6)~~, ~~weak-hash
   `usedforsecurity=False` sweep (Finding 7)~~, ~~root-logger → module-logger sweep (Finding
   10)~~, ~~silent `except`/bare-`except` sweep (Finding 12)~~, and ~~`DeviceBackend` Protocol
   typing (Finding 8)~~ — **done**, out of order relative to the rest of this bucket since all
   five were bounded and low-risk. ~~FTP plaintext (Finding 13)~~ — **reviewed, accepted as
   unavoidable** given the DWARF 3 hardware constraint. **Findings 9** (splitting the
   7,857-line `app_window.py`) **and 11** (PySide6 enum mypy noise across ~100+ sites) remain
   open by deliberate choice — both are larger, riskier structural changes than the rest of this
   list, and were left for a dedicated future session rather than folded into this pass.)
