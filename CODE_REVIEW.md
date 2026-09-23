# Code review — Python quality checklist

Review of the whole `galileo/` package (≈50 k lines, 173 modules) and `tests/`, dated 2026-09-19, against generally accepted Python practice (PEP 8, PEP 257, PEP 484, PyPA packaging guidance, Ruff/flake8-bugbear/bandit rule sets).

**How this was produced.** Tool-assisted: `ruff` (default rules, then a broad rule set), `mypy` (default settings), targeted greps, and a read of the code around each suspect finding. It was not a line-by-line read of every file, so counts below are lower bounds on "things a careful reader would flag", and the *Bugs* and *Security* items were each confirmed in the source. Numbers are from `ruff 0.16.8` / `mypy 2.3.1` and will drift as fixes land; re-run to refresh.

**Headline numbers.** Ruff default rules: 2,123 findings (1,038 auto-fixable). Ruff broad rule set: several thousand, dominated by whitespace/line-length. Mypy default: 648 errors in 74 of 173 files. Neither tool has a config in `pyproject.toml`, so nothing is enforced today.

Work top to bottom: earlier sections are cheaper to fix and de-risk later ones. Tick items off in the same change that fixes them, and add the [`CHANGELOG.md`](CHANGELOG.md) entry as usual. Legend: `[x]` done, `[ ]` open, `[~]` deferred.

**Scope exclusion (decided 2026-09-20): the Planning area is out of scope for now** — `galileo/planning/`, `galileo/sequencer/`, `galileo/scheduler.py` and the Planning screens — because it needs significant rework, and cleaning up code that is about to be rewritten is wasted effort. Items or parts of items that fall in that area are marked *deferred (Planning)* and skipped. Three small fixes were already made there before the exclusion (F811 re-imports in `sequencer/basic.py` and `planning/sky_atlas.py`, the `sequencer/advanced.py` self-import, and the `sky_atlas.py` NaN check) and are left as they are.

---

## 1. Real defects (fix first)

- [x] **Unreachable code with an undefined name** (dead block removed; the rest of the file was then reviewed and fixed — see the CHANGELOG entry on FITS compression, which also covers in-place data-loss bugs found there) — [galileo/library/core/compress_files.py:816-840](galileo/library/core/compress_files.py#L816-L840). After `_verify_fits_internal_compression` ends in `return False`, a docstring ("Verify that a compressed file can be decompressed to match the original… `algorithm`") and a body using `algorithm` follow with no `def`. It looks like a method header was lost in the port. `_verify_compression` (line 443) already exists, so either this is a duplicate to delete or a missing method to restore. Ruff reports it as `F821` ×3.
- [x] **Duplicate function definitions where the first is silently dead** (`F811`) — done; `ruff --select F811` is clean:
  - [galileo/ui/library/mappings_dialog.py:96](galileo/ui/library/mappings_dialog.py#L96) and `:304` both define `get_current_values_for_card`.
  - [galileo/library/types.py:73-75](galileo/library/types.py#L73-L75) defines `ProgressCallback` twice.
  - Redundant re-imports: [sequencer/basic.py:126](galileo/sequencer/basic.py#L126) (`FileNamer`), [planning/sky_atlas.py:518](galileo/planning/sky_atlas.py#L518) (`HorizonProfile`), [plugins/vstarget/analysis/\_\_init\_\_.py:31,65](galileo/plugins/vstarget/analysis/__init__.py#L31), [library/services/telescope.py:1115-1117](galileo/library/services/telescope.py#L1115) (`hashlib`, `datetime`), and `configparser` ×3 in [cloud_sync_dialog.py](galileo/ui/library/cloud_sync_dialog.py).
- [x] **Dead exception handler** (done: it was actually a pasted copy of a whole method sitting inside the `except` block, not just a duplicate clause; removed and covered by a regression test) — [galileo/ui/library/sessions_widget.py:2624](galileo/ui/library/sessions_widget.py#L2624) has two `except Exception` clauses on one `try` (`B025`); the second can never run.
- [x] **Module imports itself** (done — replaced by a registry lookup; this also fixed templates losing every instruction parameter on save/load, see the CHANGELOG) — [galileo/sequencer/advanced.py:137](galileo/sequencer/advanced.py#L137) (`PLW0406`). Works by accident of import order; remove.
- [~] **Sequencer templates drop nested groups, conditions and triggers** *(deferred — Planning)* — [galileo/sequencer/advanced.py](galileo/sequencer/advanced.py) `save_template`/`load_template` persist only a group's flat `instructions`. `SEQ-ADV-060` says a *configured instruction group* can be saved and reused, so loops (`RepeatCountCondition`, …), triggers and sub-groups are lost. Needs `to_dict`/`from_dict` on `InstructionGroup`, conditions and triggers, a registry for the latter two, and round-trip tests.
- [x] **NaN check written as `value == value`** (done — now `math.isfinite`, which also rejects ±inf that the old check let through; covered by new tests) — [galileo/planning/sky_atlas.py:283](galileo/planning/sky_atlas.py#L283). Replace with `math.isnan` so intent is legible (and so a linter/reader doesn't "simplify" it away).
- [x] **Late-binding closures in loops** (`B023`, 9 sites — done; all bound explicitly, and the review of these callbacks also found the shifted-argument and `'LIGHT'` bugs described in the CHANGELOG) — [library/core/auto_calibration.py:315,316,419,516,520,588](galileo/library/core/auto_calibration.py#L315) and [library/core/\_\_init\_\_.py:253](galileo/library/core/__init__.py#L253). Progress callbacks capture `i`, `session`, `base_progress`, `fits_file`. Correct only if each callback runs before the next iteration; bind with default args or `functools.partial` so it isn't order-dependent.
- [x] **Loop variable shadows a parameter** (done — loop variable renamed) — [library/core/auto_calibration.py:405](galileo/library/core/auto_calibration.py#L405) redefines `session_id` (`PLR1704`).
- [ ] **Master-creation progress runs backwards at the end of each master** — [library/core/master_manager.py](galileo/library/core/master_manager.py) `create_master_from_session` reports "100% – Master frame created" and then continues at 80% ("Updating FITS header…"), so the overall bar dips (e.g. 43 → 38 → 43). The per-session band logic in `auto_calibration.py` is correct; fix the stage percentages in `master_manager.py`.
- [ ] **Mixed-case type literals in the file model** — [library/models/fits_file.py:66,83,84](galileo/library/models/fits_file.py#L66) compare `fitsFileType` with `'Light Frame'`, `'Dark Frame'` and `'Flat Field'`, but ingest stores upper case (`'LIGHT FRAME'`, …), so `is_light_frame()` is always False and `get_calibration_criteria()` never fills exposure time/filter. Nothing calls them today; fix or delete, and centralise the type strings as constants (the same mismatch caused the quality-assessment bug in the CHANGELOG).
- [x] **Names used in annotations but never imported** (`F821`) — done via `TYPE_CHECKING` import blocks; `ruff --select F821` and mypy `name-defined` are now zero. (Harmless at runtime because of string annotations / `from __future__ import annotations`, but it broke IDEs and mypy. `typing.get_type_hints` on those functions still can't resolve the names at run time, by design — the domain core must not import the ORM.)
  - [galileo/observatory.py:133-294](galileo/observatory.py#L133) — `ObservatoryRecord`, `PierRecord`, `DeviceConfigRecord`, `OpticalTubeRecord` are imported inside functions only. Add an `if TYPE_CHECKING:` import block.
  - [galileo/ui/app_window.py:5754](galileo/ui/app_window.py#L5754) — `QButtonGroup`.
  - [galileo/ui/icons.py:15-18](galileo/ui/icons.py#L15-L18) — `QPainter`, `QRectF`, `QIcon` hidden behind `# noqa: F821`.
- [ ] **`EventBus.unsubscribe` return value used** — [galileo/ui/focus.py:240](galileo/ui/focus.py#L240) (mypy `func-returns-value`); confirm the intent (it returns `None`).
- [ ] **Blocking I/O inside `async def`** (`ASYNC210/230/240/251`) — this violates the concurrency model in SDD §2.3 and freezes the qasync loop for up to the timeout:
  - `urllib.request.urlopen` in [adapters/alpaca.py:197,323,366](galileo/adapters/alpaca.py#L197), [planning/sky_atlas.py:557](galileo/planning/sky_atlas.py#L557) *(deferred — Planning)*, [safety.py:237](galileo/safety.py#L237).
  - Blocking `open`/`Path` calls in [library/adapters/smb.py:50](galileo/library/adapters/smb.py#L50), [library/adapters/sftp.py:32](galileo/library/adapters/sftp.py#L32), [platesolve.py:186](galileo/platesolve.py#L186), [ui/imaging.py:68](galileo/ui/imaging.py#L68).
  - `time.sleep` in an async test: [tests/test_plt.py:598](tests/test_plt.py#L598).
  - Fix: wrap in `asyncio.to_thread` (as [notify.py:54](galileo/notify.py#L54) already does) or use a real async client.
- [ ] **Confirm the full fast test run passes and how long it takes.** `pytest -m "not soak and not hardware and not integration"` did not finish inside a 280 s window in this review (see the note at the end); establish a green baseline and a time budget before refactoring.

## 2. Security

- [ ] **Command injection via `os.system` with interpolated paths** — [ui/library/images_widget.py:543,545](galileo/ui/library/images_widget.py#L543), [ui/library/sessions_widget.py:467,469](galileo/ui/library/sessions_widget.py#L467): `os.system(f'open "{filename}"')`. A file name containing `"` runs arbitrary shell. Use `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`, or `subprocess.run([...], check=False)` with a list.
- [ ] **`shell=True` with interpolated paths** — [ui/library/sessions/checkout_files.py:129-135](galileo/ui/library/sessions/checkout_files.py#L129-L135) runs `mklink` through the shell. Use `os.symlink` (or `subprocess.run(["cmd", "/c", "mklink", ...])`), and raise a specific exception type instead of `Exception`.
- [ ] **SSH host keys auto-accepted** — [library/adapters/sftp.py:40](galileo/library/adapters/sftp.py#L40) uses `paramiko.AutoAddPolicy()`, which makes SFTP transfers MITM-able. Load `known_hosts` and use `RejectPolicy` (or a trust-on-first-use prompt that persists the key).
- [ ] **Plain-text iTelescope password in `library.ini`** — already in `TODO.md`; move to the OS keychain (`keyring`) per `NFR-SEC`. Also confirm nothing logs the config section that holds it.
- [ ] **MD5/SHA-1 (`S324`, 14 sites)** — [library/core/light_calibration.py:559,572,585](galileo/library/core/light_calibration.py#L559), [library/core/services/file_hash_calculator.py:81,115](galileo/library/core/services/file_hash_calculator.py#L81). Fine for de-duplication/fingerprints; say so with `hashlib.md5(..., usedforsecurity=False)` so it also works on FIPS builds and the intent is explicit. `light_calibration.py` also reads whole files with `f.read()` to hash them; hash in chunks.
- [ ] **`urlopen` with a non-constant URL** — [notify.py:54](galileo/notify.py#L54), [adapters/alpaca.py](galileo/adapters/alpaca.py), [library/core/variable_star_photometry.py:42](galileo/library/core/variable_star_photometry.py#L42). Validate the scheme is `http(s)` (a `file://` or `ftp://` URL coming from user config would otherwise be honoured), or use `requests`, which is already a dependency.
- [ ] **`subprocess.run` without `check`** — [ui/library/sessions/checkout_files.py:132](galileo/ui/library/sessions/checkout_files.py#L132), [tests/test_lib.py:478](tests/test_lib.py#L478) (`PLW1510`): make the error handling explicit.
- [ ] Add `bandit` (or Ruff `S` rules) to CI so these don't return; then reconcile with [docs/SECURITY.md](docs/SECURITY.md).

## 3. Error handling

The codebase has 616 `except Exception` clauses (448 flagged `BLE001`), 21 bare `except:`, 29 `try/except/pass`, and 10 `try/except/continue`. Some are legitimate device-fault isolation (`ARCH-060`); most in the ported library code are not.

- [ ] Replace **all 21 bare `except:`** (`E722`) — they also swallow `KeyboardInterrupt`/`SystemExit`. Concentrated in [library/services/telescope.py](galileo/library/services/telescope.py) (≈14), [library/core/light_calibration.py:561,574,587,611](galileo/library/core/light_calibration.py#L561), [library/core/compress_files.py:498](galileo/library/core/compress_files.py#L498), [library/core/enhanced_quality.py:254](galileo/library/core/enhanced_quality.py#L254), [ui/library/cloud_sync_dialog.py:388](galileo/ui/library/cloud_sync_dialog.py#L388).
- [ ] For each `except Exception: pass` decide: narrow the exception type, log it, or document why it is deliberately ignored (`contextlib.suppress(SpecificError)`). At device/plugin boundaries keep the broad catch **but log with a traceback**.
- [ ] Use `logger.exception(...)` (or `exc_info=True`) inside handlers instead of `logger.error(f"...{e}")` (`TRY400`, 281 sites) — the traceback is currently lost from the log files.
- [ ] Chain re-raised exceptions: `raise NewError(...) from exc` (`B904`, 50 sites); remove the pointless `try/except: raise` at [library/core/file_processing.py:621](galileo/library/core/file_processing.py#L621).
- [ ] Stop raising bare `Exception(...)` (`TRY002`, 18 sites); use the hierarchy in [galileo/exceptions.py](galileo/exceptions.py), or add classes there.
- [ ] Add `strict=True/False` explicitly to `zip()` (`B905`, 18 sites) — silent truncation of mismatched sequences is a classic photometry/calibration bug.

## 4. Tooling, packaging and CI

- [ ] **Add `[tool.ruff]`, `[tool.mypy]`, and `[tool.coverage]` to `pyproject.toml`.** Suggested starting point: `line-length = 100` (pick one and stick to it); `select = ["E","F","W","I","B","UP","SIM","C4","RUF","S","ASYNC","LOG","G","DTZ","PTH"]`; per-file ignores for `tests/**` (`S101`, `ANN`, `D`), `galileo/library/models/**` and `migrations/**` (camelCase names are intentional per `CLAUDE.md`), and `galileo/commands/**` (`T201` — CLI `print` is fine).
- [ ] **Add a `[build-system]` table** (e.g. `setuptools>=68` + `wheel`, or `hatchling`). Today `pyproject.toml` has none, so pip silently falls back to legacy setuptools behaviour.
- [ ] **Declare packages and package data explicitly.** The repo root holds `galileo/`, `tests/`, `assets/`, `docs/`, `logs/`; setuptools' flat-layout auto-discovery may refuse to build with several top-level directories (it only skips well-known names like `tests` and `docs`). Set `[tool.setuptools.packages.find] include = ["galileo*"]` and `package-data` for `galileo/library/migrations/*.py`, `galileo/ui/translations/*`, and any bundled catalogs. Then verify with `python -m build` and installing the wheel into a clean venv (migrations and translations are the usual casualties).
- [ ] **Single source of truth for dependencies.** `requirements.txt`/`requirements-dev.txt` duplicate `pyproject.toml` by hand and will drift. Make `requirements*.txt` either generated (`pip-compile`) or removed in favour of `pip install -e ".[test,dev]"`. Add upper bounds or a lock file for the fragile stack (PySide6, numpy 2.x vs `sep`/`astroalign`, astropy).
- [ ] **Complete the `dev` extra** (`ruff`, `mypy` are unpinned; add `pytest-cov`, `types-requests`, `types-paramiko`, `pandas-stubs`, `bandit`, `pre-commit`, `build`).
- [ ] **CI** — there is no `.github/`. Add a workflow running on Windows, macOS and Linux × Python 3.11/3.12/3.13 (the local venv is 3.13, `requires-python` is `>=3.11`): install, `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not soak and not hardware and not integration"` with coverage, and `pip-audit`. Run Qt tests with `QT_QPA_PLATFORM=offscreen`.
- [ ] **`pre-commit`** hooks for ruff (lint + format), trailing whitespace, end-of-file newline (36 files lack one), and `check-added-large-files`.
- [ ] **Ship `galileo/py.typed`** once the public API is annotated, so downstream plugin authors get type checking.
- [ ] Confirm log output goes through `galileo.platform` (`NFR-PORT-010`) and not a repo-relative `logs/` directory; the repo root currently contains one with dated log files.

## 5. Formatting and mechanical clean-up (auto-fixable — do in one isolated commit)

Do this as a single "no functional change" commit, add its hash to `.git-blame-ignore-revs`, and run the test suite before and after.

- [ ] `ruff format` the tree. Trailing whitespace is pervasive — 3,452 blank lines with whitespace (`W293`) and 196 trailing spaces (`W291`), overwhelmingly in the vendored AstroFiler/VSTarget code. 2,899 lines exceed 88 columns (`E501`); resolve by choosing the line length above rather than hand-wrapping.
- [ ] `ruff check --fix` for: unsorted imports (`I001`, 243), unused imports (`F401`, 201), quoted annotations that no longer need quotes (`UP037`, 195), `Optional[X]`→`X | None` (`UP045`, 92), `typing.List`→`list` (`UP006`/`UP035`), f-strings with no placeholders (`F541`, 73), unused `noqa` (`RUF100`, 22), `datetime.timezone.utc`→`datetime.UTC` (`UP017`), missing final newline (`W292`).
- [ ] Review then remove unused local variables (`F841`, 44) and unused unpacked variables (`RUF059`, 21) — some may hide a forgotten use.
- [ ] Fix ambiguous Unicode in strings/comments/docstrings (`RUF001-003`, 49) — en/em dashes and multiplication signs that look like ASCII.
- [ ] Replace `== True` / `== False` (`E712`, 40) — but check each first: in a Peewee query (`Model.flag == True`) the comparison builds a SQL expression, so keep it with `# noqa: E712` (or use `Model.flag.is_null(False)`-style methods); only plain Python booleans should become `if x:`.
- [ ] Split `a; b` statements (`E702`, 14).

## 6. Logging

- [ ] **231 calls use the root logger** (`logging.info(...)`, `LOG015`) rather than a module `logger = logging.getLogger(__name__)`. That bypasses per-module log levels/handlers, and calling `logging.info` on the root logger can implicitly configure logging as a side effect. Convert all of them.
- [ ] **1,061 f-string log calls** (`G004`). Use lazy `logger.info("x %s", x)` so disabled levels cost nothing and log aggregators can group messages. Do this together with the `TRY400` item in §3.
- [ ] Replace the 2 remaining non-CLI `print()` calls in `galileo/` with the logger.

## 7. Dates and times

- [ ] 37 `datetime.now()` without a timezone (`DTZ005`), 12 `datetime.utcnow()` (`DTZ003`, **deprecated since 3.12**), 7 `strptime` without a zone, 3 `date.today()`. For an application whose data (FITS headers, session boundaries, twilight, AAVSO reports) is time-critical, pick a convention — timezone-aware UTC internally, local time only at the UI edge — and apply it everywhere. Check the migrations and the AstroFiler-compatible columns before changing what gets stored, since existing databases hold naive values.

## 8. Type hints

Mypy (default settings) reports 648 errors in 74 files. Roughly 280 are `attr-defined`, most of them PySide6 enum access, and 76 are missing stubs; the rest include real problems.

- [ ] **Qt enums** — `Qt.AlignCenter`, `QImage.Format_RGB888`, `QPainter.SmoothPixmapTransform`, `Qt.DashLine` etc. work at runtime through PySide6's forgiving-enum shim but are wrong for type checkers and are removed under strict mode. Use the scoped form (`Qt.AlignmentFlag.AlignCenter`, `QImage.Format.Format_RGB888`, …). Ruff can't fix this; a scripted search-replace over `galileo/ui/` will.
- [ ] **Missing stubs (76 `import-untyped`, 13 `import-not-found`)** — install `types-requests`, `types-paramiko`, `pandas-stubs`, `scipy-stubs`; add `[[tool.mypy.overrides]] ignore_missing_imports = true` only for genuinely untyped packages (`sep`, `astroalign`, `lz4`, `smb`, `peewee_migrate`, `qasync`, …).
- [ ] **Real typing bugs to fix by hand** (examples): [core/devices.py:115-402](galileo/core/devices.py#L115) — `DeviceBackend` has no `start_exposure`, `slew_to_coordinates`, `move_to`, … so the per-category wrappers call methods the base type doesn't declare. Make `DeviceBackend` a `Protocol` per category (this is the port interface the SDD promises), or use generics so `CameraDevice` wraps a `CameraBackend`. Also [ui/focus.py:440](galileo/ui/focus.py#L440) (`None`-typed attribute assigned an `AutofocusService`), [observatory.py:110,117](galileo/observatory.py#L110) (`None` has no `connect_all`/`run` — optionals used without narrowing), [ui/theme.py:218](galileo/ui/theme.py#L218) (`QCoreApplication` has no `setStyleSheet`; needs a `QApplication` cast/assert), and the 40 `union-attr` / 31 `arg-type` / 42 `call-arg` sites.
- [ ] **Annotate function signatures** — 898 unannotated parameters (`ANN001`), 306 public and 166 private missing return types (`ANN201/202`). Do it incrementally: turn on `disallow_untyped_defs` for the domain core first (`galileo.core`, `galileo.bus`, `galileo.sequencer`, `galileo.autofocus`, `galileo.platesolve`, `galileo.scheduler`, …) via per-module mypy overrides, then adapters, then UI. Add `ANN` rules to Ruff for those paths only.
- [ ] Replace 13 uses of `Any` (`ANN401`) in public signatures with `Protocol`s/`TypeVar`s where feasible; audit the 22 `# type: ignore` comments and give each an error code (`# type: ignore[attr-defined]`) and a reason.
- [ ] Fix implicit `Optional` defaults (`RUF013`, 6) and mutable class attributes (`RUF012`): [adapters/alpaca.py:542-544](galileo/adapters/alpaca.py#L542), [adapters/indi.py:518](galileo/adapters/indi.py#L518), [core/devices.py:55](galileo/core/devices.py#L55), [equipment/profiles.py:193](galileo/equipment/profiles.py#L193) — use `ClassVar[...]` for constants, `field(default_factory=...)` for per-instance state.

## 9. Structure, complexity and architecture

- [ ] **Break up `galileo/ui/app_window.py`** — 5,756 lines, one `AppWindow` class from line 230 to 5,518 plus five helper classes, 23 complexity/size findings. It already has the seam: `focus.py`, `solve.py`, `guider.py`, `star_atlas.py` are separate page modules. Move each remaining page (cameras, mount, filter wheel, focuser, rotator, optics, imaging, options, …) into its own `galileo/ui/<page>.py` widget with a narrow interface to the window, and leave `AppWindow` as the shell (nav, theme, page stack). Do it one page per commit, guarded by the existing UI tests.
- [ ] **Other oversized modules**: [ui/library/sessions_widget.py](galileo/ui/library/sessions_widget.py) (2,625 lines), [library/services/telescope.py](galileo/library/services/telescope.py) (1,577), [library/core/master_manager.py](galileo/library/core/master_manager.py) (1,421), [ui/library/cloud_sync_dialog.py](galileo/ui/library/cloud_sync_dialog.py) (1,364), [ui/library/images_widget.py](galileo/ui/library/images_widget.py) (1,103). The `telescope.py` merge with `galileo.library.adapters` is already in `TODO.md` — do the split as part of it.
- [ ] **Complexity budget** — 89 functions exceed 50 statements (`PLR0915`), 74 exceed 12 branches (`PLR0912`), 34 have >6 returns, 23 take >5 arguments. Set `max-complexity` (`C901`) at ~15 for new code, baseline existing offenders with per-function `# noqa: C901` only where a refactor is not planned, and chip away at the worst (start with those in `app_window.py`, `sessions_widget.py`, `master_manager.py`).
- [ ] **Remove the `if _HAS_QT else object` conditional base classes** in `app_window.py` (14 references). It exists so the module imports without Qt, but the module can't work without Qt; import it lazily at the app entry point instead and let the base classes be plain `QWidget`/`QThread`.
- [ ] **Enforce the hexagonal boundary from `CLAUDE.md` / SDD §6.1.** [galileo/guiding.py:378](galileo/guiding.py#L378) imports `galileo.adapters.phd2` from the domain core; [galileo/observatory.py:135-294](galileo/observatory.py#L135) imports Peewee models from `galileo.library.models` inside the domain layer. Inject adapter/repository factories from the composition root (`galileo.app`) or register them through the plugin mechanism, then add an import-linter (or a small pytest) contract: `galileo.core|sequencer|autofocus|…` may not import `galileo.adapters|ui|library`.
- [ ] **Local imports** — 685 imports are inside functions (`PLC0415`). Lazy Qt and heavy optional-dependency imports are legitimate; the rest (stdlib, `numpy`, `astropy`) are not. Move those to module level and record the policy in `CONTRIBUTING.md`. Resolve any cycles the move exposes rather than re-hiding them.
- [ ] **Module-level state** — 9 `global` statements (`PLW0603`), e.g. the `get_bus()` singleton. Make the lazy initialisation thread-safe (`functools.cache`, or a lock) and provide a reset hook for tests.
- [ ] **Path handling** — ~650 `os.path.*`/`open()` calls (`PTH*`, mostly the vendored library and commands). Adopt `pathlib.Path` in new code and convert opportunistically; do not bulk-convert working AstroFiler code without tests.

## 10. Naming

- [ ] Camel-case model fields, columns and migration names stay (documented exception; needed so AstroFiler databases open unchanged) — encode that as per-file ignores so `N802/N803/N806/N815` (≈300 hits) only fire for code that isn't part of that contract.
- [ ] Rename the remaining non-conforming functions/variables/classes (`N801` ×3, plus the non-library share of `N802/N806`) and check public-API renames against [docs/SDD.md](docs/SDD.md) and the plugin surface before changing them.

## 11. Documentation and docstrings

- [ ] Choose a docstring convention (the code already uses Google-style `Args:`/`Returns:`) and set `[tool.ruff.lint.pydocstyle] convention = "google"`.
- [ ] Missing docstrings: 16 modules (`D100`), 68 classes (`D101`), 453 public methods (`D102`), 112 functions (`D103`), 124 `__init__`s. Require them for the **public, non-UI API** (ports in `core/devices.py`, `bus`, `sequencer`, `plugins`, `scheduler`); leave UI slot methods exempt.
- [ ] Fix docstrings that contradict the code — e.g. the orphaned `algorithm` parameter documented at [compress_files.py:816-825](galileo/library/core/compress_files.py#L816) (see §1); enable `D417` to catch this class.
- [ ] Keep requirement IDs in docstrings/tests (already a strength); add a script or test that fails when a `TC-*` ID referenced in `tests/` is absent from `docs/RTM.md`, and vice versa.

## 12. Tests

- [ ] **Measure coverage** (`pytest --cov=galileo --cov-report=term-missing`) and record a baseline per package. The vendored `galileo.library`, `galileo.commands`, and `galileo.ui` (5.7 k-line window) are the likely blind spots — 42 test files exist, organised by SRS domain rather than by module, which makes uncovered modules easy to miss.
- [ ] **Stop blanket-ignoring `DeprecationWarning`/`PendingDeprecationWarning`** in `[tool.pytest.ini_options] filterwarnings`. It hides the breakage that arrives with new Python/numpy/astropy/PySide6 releases (and `utcnow`, §7). Use `error::DeprecationWarning` for `galileo.*` and ignore only specific third-party messages.
- [ ] Get test speed and hangs under control: mark slow tests, add `pytest-timeout` (a per-test ceiling stops one wedged INDI/Alpaca fake from hanging CI), and report `--durations` in CI.
- [ ] Replace `time.sleep` in [tests/test_plt.py:598](tests/test_plt.py#L598) with `await asyncio.sleep` or an event/condition.
- [ ] Add regression tests for each bug in §1 and each security fix in §2 (a file name with a `"` opened through the Library screens; SFTP with an unknown host key; `_verify_*` compression round trip).
- [ ] Consider `hypothesis` for the parsers (`parse_horizon_text`, INDI XML framing, FITS header/naming macros) and `pytest-randomly` to expose inter-test order dependence in the module-scoped DB/catalog fixtures.

## 13. Suggested order of work

1. §1 defects and §2 security fixes (small, high value, each needs a regression test).
2. §4 tooling config + CI, with the current findings baselined so CI is green on day one (`ruff --add-noqa` or a per-rule ignore list that later shrinks; `mypy` with the error-count ratchet).
3. §5 formatting commit and §6/§7 mechanical conversions.
4. §3 error-handling clean-up, module by module, with §8 typing of the domain core alongside.
5. §9 structural refactors (`app_window.py` split, boundary enforcement, telescope/adapter merge), one per PR, protected by §12 coverage.
6. §10–§11 naming and docstring enforcement, tightening rules as each package reaches zero findings.

---

## Note: test-suite state during this review

Two runs of `pytest -m "not soak and not hardware and not integration"` were started. The first (`-x`) reached about 90 % with every test passing before the 280 s window closed; the second (run in the background) stalled at about 64 % and had to be killed. No failure was seen, but **no complete run was observed**, and a test that sometimes hangs or is very slow is unresolved. Both runs overlapped for a while, so contention may account for part of it; re-run in isolation with `pytest --durations=20 -p no:cacheprovider` (and `pytest-timeout`, §12) to find the culprit.
