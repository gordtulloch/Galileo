# Plugin Distribution & Marketplace — Implementation Checklist

Tracks the work required to implement plugin packaging, distribution via galileo-imaging.com, the in-app Plugin Marketplace, and VSTarget's migration from a bundled plugin to a downloadable one. Requirements: `PLUG-030`, `PLUG-060`, `PLUG-090`–`PLUG-120` (SRS §4.19); design: SDD §4.20.

---

## 1. Website (galileo-imaging.com)

- [ ] Create a `/plugins` page listing available plugins, each as a direct `.zip` download link
- [ ] Embed a `<script type="application/json" id="galileo-plugins">` block in the page — a JSON array of plugin entries `{name, description, version, tier, author, download_url}` — this is what the Marketplace client will prefer over HTML scraping
- [ ] Host the VSTarget planning ZIP (`vstarget-planning-<version>.zip`) and analysis ZIP (`vstarget-analysis-<version>.zip`) as direct links on that page
- [ ] Establish a process for publishing future plugin ZIPs (naming convention, version bumping, page update)

---

## 2. Plugin ZIP Package Format

- [x] Define and document the `plugin.toml` manifest schema:
  - Required: `name`, `version` (semver), `api_min`, `api_max`, `author`, `description`, `tier` (`first_party` or `third_party`)
  - Optional: `nav_level` (`primary` or `secondary`), `entry_point` (defaults to `galileo.plugins.<name>`)
- [ ] Write a packaging script / Makefile target that produces a well-formed plugin ZIP from a plugin source tree
- [ ] Verify the ZIP structure: `plugin.toml` at the root, plugin package at the root level of the ZIP (not nested under `galileo/`)

---

## 3. VSTarget Packaging

- [x] `galileo/plugins/vstarget/plugin.toml` manifest written (covers both VSTPlugin and VSTAnalysisPlugin in one package; `entry_point = "galileo.plugins.vstarget"`)
- [x] VSTarget removed from `initialize_preloaded()` — `initialize_from_disk()` replaces it; neither plugin loads unless installed from disk
- [ ] Write a packaging script that produces `vstarget-<version>.zip` from the source tree for hosting on galileo-imaging.com
- [ ] Verify `vstarget.zip` installs cleanly through `PluginManager.install()` on a fresh plugins_dir
- [ ] Update `docs/plugins/vstarget/SRS.md`, `SDD.md`, and `RTM.md` to remove references to `PLUG-060` pre-loading and add references to `PLUG-090`/`PLUG-110` distribution

---

## 4. Core Plugin Loader (`galileo/plugins/__init__.py`) ✅

- [x] Plugin discovery changed from `importlib.metadata` entry points to scanning `<plugins_dir>` for `plugin.toml` manifests at startup (`initialize_from_disk()`)
- [x] **Install pipeline** implemented (`PluginManager.install(zip_path)`): validate ZIP → parse/validate manifest → version-check → extract to `<plugins_dir>/<name>-<version>/` → load → rollback on failure
- [x] **Remove pipeline** implemented (`PluginManager.remove(name)`): unload immediately, `shutil.rmtree`; on `OSError` writes `.pending_removal` marker; `initialize_from_disk()` processes markers at next startup
- [x] `galileo.platform.get_plugins_dir()` added
- [x] `PluginManager` API: `install()`, `remove()`, `set_enabled()`, `list_installed()`
- [x] `PluginManifest` and `PluginRecord` dataclasses added

---

## 5. `galileo.plugins.marketplace.MarketplaceClient` ✅

- [x] HTTP GET to `https://www.galileo-imaging.com/assets/plug-ins` (configurable `base_url`)
- [x] **Primary parse strategy:** JSON embed (`<script … id="galileo-plugins">`)
- [x] **Fallback parse strategy:** HTML scrape for `<section id="plugins">` `<a>` links
- [x] Returns `list[MarketplaceEntry]`; graceful failure returns `([], error_str)`
- [x] Session-level in-memory cache; `refresh()` clears it
- [x] `download(entry, dest_path, progress_callback, cancel_flag)` streams ZIP with progress and cancellation

---

## 6. Options > Plugins Screen (`galileo/ui/app_window/_plugins_page.py`) ✅

- [x] `AppWindowPluginsPageMixin._build_plugins_settings_page()` implemented
- [x] Wired into Options nav (`_common.py` OPTIONS_ITEMS, `_core.py` option_builders, `__init__.py` mixin list, `_state.py` Protocol)

### Installed tab ✅
- [x] Table: name, version, tier, author, enabled toggle + Remove button per row
- [x] Enabled toggle calls `set_enabled()`; shows restart banner
- [x] Remove button shows `QMessageBox` confirmation; calls `remove()`; shows restart banner if deferred; refreshes table

### Install from file ✅
- [x] `QFileDialog` filtered to `*.zip`; calls `PluginManager.install()`; shows error dialog on failure

### Marketplace tab ✅
- [x] Fetches on first open (lazy); `QThread`-based fetch so UI stays responsive
- [x] Table: name, version, tier, author, Install/Installed label per entry
- [x] Install triggers `MarketplaceClient.download()` + `PluginManager.install()`
- [x] Refresh button; offline error state shown in place of table

---

## 7. Tests (`tests/test_plug.py`) ✅

### TC-PLUG-090 — Install from local ZIP ✅
- [x] Valid ZIP → plugin installed and loaded
- [x] Missing `plugin.toml` → `PluginInstallError`; no files left
- [x] Missing required manifest field → `PluginInstallError`; no files left
- [x] Incompatible API version → `PluginInstallError`; no files left
- [x] Corrupt ZIP → `PluginInstallError`; no files left

### TC-PLUG-100 — Marketplace fetch ✅
- [x] JSON embed → correct `MarketplaceEntry` list
- [x] HTML fallback (`<section id="plugins">`) → correct list
- [x] Network failure → empty list + error string; no exception
- [x] Cache: second call no extra HTTP request
- [x] `refresh()` forces new HTTP request

### TC-PLUG-110 — Marketplace download + install ✅
- [x] Mock download + valid ZIP → plugin installed

### TC-PLUG-120 — Remove ✅
- [x] Full removal: unloaded, directory deleted
- [x] Non-existent plugin → graceful no-op
- [x] OSError on rmtree → `.pending_removal` marker written; `remove()` returns `False`

### TC-PLUG-060 — Installed plugin enable/disable ✅
- [x] Updated to use a minimal `load()`-registered plugin; no longer relies on `initialize_preloaded()`

---

## 8. Documentation (already updated)

- [x] `docs/PSD.md` — G5, G8, PLUG domain row updated with distribution model
- [x] `docs/SRS.md` — PLUG section rewritten; PLUG-030 expanded; PLUG-090/100/110/120 added; all at MVP
- [x] `docs/SDD.md` — §4.20 expanded with ZIP format, manifest schema, install pipeline, Marketplace scraping strategy, Options > Plugins screen behavior
- [x] `docs/RTM.md` — TC-PLUG-090/100/110/120 rows added
- [x] `docs/plugins/vstarget/PSD.md` — G1/G2 updated to downloadable ZIP distribution
- [x] `CHANGELOG.md` — entry added
- [x] `docs/plugins/vstarget/SRS.md` — §2.1 updated to downloadable ZIP; §2.5 updated to `PLUG-010`–`PLUG-120`
- [x] `docs/plugins/vstarget/SDD.md` — ADR-VST-001 rewritten; §3.1/3.2 pre-loaded language replaced with ZIP distribution
- [x] `docs/plugins/vstarget/RTM.md` — §4 cross-reference updated to `PLUG-010`–`PLUG-120`
