# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Galileo is a cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM) astrophotography imaging application, built on INDI and ASCOM Alpaca device protocols rather than Windows-only ASCOM/COM drivers. It consolidates three of the author's prior projects — AstroFiler (image library/calibration), VSTarget (AAVSO variable-star planning/photometry), and Obsy (sky-atlas/framing logic) — into one PySide6 desktop app.

**Note on repo state:** `README.md`'s Status section and `CHANGELOG.md` are kept up to date as of each change (see below) — check both for what's actually implemented versus still a placeholder. The design docs in `docs/` are the authoritative source for intended architecture, which is not the same thing as current implementation status.

## Changelog

**Every change to this repository — code, tests, or docs — must add an entry to [`CHANGELOG.md`](CHANGELOG.md) in the same turn the change is made**, under the `## [Unreleased]` heading, in the appropriate `Added`/`Changed`/`Fixed`/`Removed` subsection ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format). Write entries for someone who wasn't watching the session — state what changed and why it matters, not a diff summary. Don't batch this up for later; a change without a changelog entry is not done.

## Design documents (read these before making architectural changes)

The `docs/` folder is a linked requirements → design → traceability chain, in this order of authority:

- [`docs/PSD.md`](docs/PSD.md) — Project Scope Document: goals, non-goals, requirement domains, constraints, licensing decisions.
- [`docs/SRS.md`](docs/SRS.md) — Software Requirements Specification: numbered, testable requirements (e.g. `ARCH-010`, `SEQ-090`) grouped into domains.
- [`docs/SDD.md`](docs/SDD.md) — Software Design Description: **the primary architecture reference**. Section 3 has the architecture diagram; Section 4 is a module-by-module design doc (one subsection per `galileo.*` module) each ending in a "Satisfies: <requirement IDs>" line; Section 2 covers the ADRs (tech stack, concurrency model, merge strategies for AstroFiler/VSTarget/Obsy/AstroLlama).
- [`docs/RTM.md`](docs/RTM.md) — Requirements Traceability Matrix: every SRS requirement ID mapped to its SDD component and a reserved `TC-*` test case ID.

Every requirement ID referenced in code/test comments (e.g. `ARCH-010`, `SEQ-ADV-040`, `LIB-160`) is traceable through this chain — grep the SRS/SDD for the ID if a comment references one you don't recognize.

## Commands

```bash
pytest                          # run the full suite (excludes nothing by default — see markers below)
pytest tests/test_arch.py       # run one test file
pytest -k test_tc_arch_010      # run one test by name
pytest -m "not soak and not hardware and not integration"   # fast local/CI run — skip long/external-dependency tests
ruff check .                    # lint (dev dependency)
mypy .                          # type check (dev dependency)
```

Install with `pip install -e ".[test,dev]"` (or `.[test]` for just the test deps). Requires Python >= 3.11.

## Test architecture

Tests are organized **by SRS requirement domain, one file per domain**, not by source module — e.g. `tests/test_arch.py` covers `ARCH-*` requirements, `tests/test_seq_adv.py` covers `SEQ-ADV-*`, `tests/test_vst_an.py` covers `VST-AN-*`. The mapping from short test-file suffix to domain is in each file's module docstring (e.g. `test_eqp.py` → `EQP`, `test_foc.py` → `FOC`/Autofocus, `test_mflip.py` → `MFLIP`/Meridian Flip, `test_nfr.py` → cross-cutting non-functional requirements).

Every test function is tagged with the RTM test case ID it implements and its priority:

```python
@pytest.mark.requirement("TC-ARCH-010")
@pytest.mark.priority("MVP")   # MVP, P2, or P3
def test_tc_arch_010_device_abstraction_per_category():
    """ARCH-010: <restates the requirement text>"""
    ...
```

When adding a new test, follow this pattern: one `test_tc_<domain>_<nnn>_<description>` function per test case ID, decorated with `@pytest.mark.requirement(...)` and `@pytest.mark.priority(...)`, docstring starting with the requirement ID it verifies. Check `docs/RTM.md` for the requirement's already-reserved `TC-*` ID before inventing a new one.

Custom markers (declared in `tests/conftest.py` and `pyproject.toml`):
- `soak` — requires extended (hours-long) runtime; excluded from normal runs.
- `hardware` — requires physical INDI/Alpaca hardware reachable on the LAN.
- `integration` — requires a running external service (INDI server, PHD2, a solver, etc.).

Most device/hardware interaction is tested against `MagicMock`/`AsyncMock` fixtures defined in `tests/conftest.py` (`mock_indi_camera`, `mock_indi_mount`, `mock_filter_wheel`, `mock_focuser`, `mock_rotator`, `mock_flat_panel`, `mock_weather_station`, `mock_safety_monitor`, `mock_dome`, `mock_guider`, `mock_switch_device`, plus `minimal_sequence`/`minimal_profile` fixtures and an `event_bus` mock) rather than real hardware — real devices are only exercised by `hardware`-marked tests. A session-scoped autouse fixture pre-populates a synthetic 10K-object sky atlas catalog cache so offline catalog tests don't need network access.

`asyncio_mode = "auto"` is set, so `async def test_...` functions work without `@pytest.mark.asyncio`.

## Architecture

Galileo uses a **layered, ports-and-adapters (hexagonal) architecture** (SDD §2.2):

- **Domain core** (`galileo.core.devices`, `galileo.sequencer.*`, `galileo.autofocus`, `galileo.platesolve`, `galileo.calibration`, `galileo.meridianflip`, `galileo.safety`, `galileo.history`, `galileo.scheduler`, `galileo.observatory`, `galileo.bus`) is plain Python with **no direct dependency on INDI, Alpaca, Qt, or the filesystem**. It depends only on abstract port interfaces.
- **Adapters** (`galileo.adapters.indi`, `galileo.adapters.alpaca`, persistence, external-process, notification, `galileo.ui.*`) implement those port interfaces. The domain core and UI must never import `galileo.adapters.indi`/`galileo.adapters.alpaca` directly — only the port interfaces in `galileo.core.devices` — per SDD §6.1's module-boundary rule.
- **Plugins** register new adapters or new domain-core extensions (`SequencerNode` implementations) against the exact same port interfaces used internally — there is no separate "plugin API." `galileo.vstarget.planning`/`galileo.vstarget.analysis` are themselves shipped as first-party pre-loaded plugins (the reference implementation of this boundary), not special-cased core modules.

**Cross-module communication goes through the event bus** (`galileo.bus.EventBus`, obtained via `get_bus()`), never direct calls between unrelated domain-core modules. E.g. the sequencer publishes `SequenceCompleteEvent`/frame-written events; `galileo.library` and `galileo.history` subscribe rather than being called into directly. This is what keeps a safety-monitor "unsafe" event reaching the sequencer without a hard dependency, and what gives fault isolation between devices (`ARCH-060`). Handlers run synchronously on the publishing thread — Qt code must marshal onto the Qt event loop (`Qt.QueuedConnection`) before calling into the bus.

**Concurrency model** (SDD §2.3): the Qt UI thread owns the event loop and never blocks; async I/O (Alpaca HTTP, external solver/guider processes) runs via `asyncio` bridged through `qasync`; INDI I/O runs on a per-server reader thread in `galileo.adapters.indi_client` (a native INDI-protocol client — `pyindi-client` is not used because libindi can't be built on Windows), called via `asyncio.to_thread` so it works from any event loop; CPU-bound work (star detection, HFR curve fitting) is dispatched to a `ProcessPoolExecutor`, never run on the UI thread.

**Multi-mount support**: device instances live in a `DevicePool` keyed per **Pier** (`galileo.core.devices`, `ARCH-080`) — not a single global registry — because `galileo.observatory` groups multiple Piers into an Observatory with shared or per-Pier resource scoping (dome/safety) on top, without the device layer itself needing to know about Observatories. Each Pier runs its own independent sequencer/scheduler pair.

**Star detection uses SEP everywhere** (autofocus, imaging-tab stats, library quality metrics) — `photutils` is deliberately reintroduced only in `galileo.vstarget.analysis` for aperture photometry, a different problem SEP doesn't solve. Don't conflate the two or "unify" them; SDD §2.6 explains why they coexist.

**Persistence is unified**: one Peewee ORM database (`galileo.library`'s repository catalog, `galileo.history` session metrics, scheduler job queue, and VSTarget's variable-star data all share the same DB via `peewee-migrate`-managed schema) — not separate SQLite files per module. A schema change is a new numbered file in `galileo/library/migrations/` (never `create_tables` or hand-patched columns); `init_db` applies pending ones at start-up. The catalog models keep AstroFiler's names (`fitsFile`, `fitsSession`, …) and camelCase columns on purpose, so AstroFiler databases open unchanged.

**FITS is the sole working image format** (project-wide constraint, SDD §4.18); XISF is accepted only on import via a best-effort converter in `galileo.library` and never read/written anywhere else in the codebase.

### Key modules at a glance

| Module | Responsibility |
|---|---|
| `galileo.core.devices` | Device-category port interfaces, `DeviceCapabilities`, `DevicePool` (per-Pier) |
| `galileo.adapters.indi` / `galileo.adapters.alpaca` | INDI / Alpaca implementations of every device port |
| `galileo.equipment.profiles` | Pier = one mount + one or more `OpticalTrain`s; JSON/pydantic persistence |
| `galileo.observatory` | Groups Piers into an Observatory; shared dome/safety resource scoping |
| `galileo.sequencer.basic` / `.advanced` | Linear sequence runner / nested instruction-condition-trigger engine (`SequencerNode`) |
| `galileo.scheduler` | Multi-night job queue layered above the sequencer (triggers, doesn't duplicate, `SequenceRunner`) |
| `galileo.autofocus`, `galileo.platesolve`, `galileo.calibration`, `galileo.meridianflip`, `galileo.guiding`, `galileo.dome`, `galileo.safety` | Domain-core workflow services, each behind its own adapter interface (`SolverAdapter`, `GuiderAdapter`, etc.) |
| `galileo.library` | Vendored AstroFiler: catalog models + `migrations/` (the schema — AstroFiler's `001`-`012`, then Galileo's), `core/` (ingest, sessions, master frames, calibration, quality, duplicates), `services/` (GCS, smart telescopes), `registrar` (sequencer hook), `config` (`library.ini`). Screens are `galileo.ui.library`; batch utilities are `galileo.commands` |
| `galileo.vstarget.planning` / `.analysis` | Vendored VSTarget: AAVSO planning and photometry, shipped as first-party plugins |
| `galileo.planning.sky_atlas` / `.framing`, `galileo.ui.skymap` | Catalog/visibility, FOV/framing, and the live planetarium view — three distinct UIs sharing one bundled catalog DB |
| `galileo.plugins` | Entry-point-based plugin discovery/load, manifest/version checks, `PluginContext` callback surface |
| `galileo.bus` | The `EventBus` / `Event` types used for all cross-module decoupling |
| `galileo.platform` | All OS-specific path resolution (config/data/cache/log dirs) — isolated here per `NFR-PORT-010` |

When changing a module's public behavior, check whether its SDD §4.x subsection's "Satisfies" line names requirement IDs you'd be affecting, and whether a corresponding `TC-*` test in `tests/` needs updating.
