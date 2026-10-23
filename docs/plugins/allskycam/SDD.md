# AllSkyCam Plugin — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — AllSkyCam Plugin |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-22 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md) |
| **Downstream document** | RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SDD](../../SDD.md) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how the plugin's package satisfies the requirements in [its SRS](SRS.md), and how it attaches to [Galileo core's architecture](../../SDD.md) exclusively through the plugin extension points core `galileo.plugins` exposes (core SDD Section 4.20).

### 1.2 Scope

The single package `allskycam`, its ADRs, and its data design. Core architecture is inherited unchanged.

### 1.3 References

[PSD](PSD.md), [SRS](SRS.md); [Galileo Core SDD](../../SDD.md) Sections 2.3 (concurrency), 4.20 (`galileo.plugins`) and 6.3 (plugin API surface).

---

## 2. Design Considerations

### 2.1 Consume `/latestimage`; Do Not Add an API to indi-allsky (ADR-ASC-001)

**Decision:** the plugin reads indi-allsky's existing `GET /latestimage[?camera_id=N]` route, which answers with a 302 to the newest processed image, rather than adding a REST endpoint to indi-allsky.

**Rationale:** the route already returns exactly what is needed — the newest image of a camera, unauthenticated by default — so no upstream change, release coupling or version negotiation is required, and the plugin works with any indi-allsky that has the route. A richer API (a JSON "latest" with timestamps, an API key on read routes) remains possible later; it would be an upstream contribution and an additive change here. indi-allsky's `/js/latest` JSON view was considered and rejected: it describes freshness for its own web page, not for a client, and its image URL is relative to its web UI.

### 2.2 Follow the Redirect by Hand (ADR-ASC-002)

**Decision:** `AllSkyClient` requests `/latestimage` with redirects disabled, resolves each `Location` itself (at most five hops), and compares each target with the previously fetched image's address before requesting it.

**Rationale:** the redirect target is a timestamped file name, so equality with the last one is a free, exact "nothing new" test. Letting `requests` follow the redirect would start the image download even when it is not wanted. A test against a real local server (`TC-ASC-010`) caught exactly that in the first, automatic-redirect version.

### 2.3 Frames Held Compressed, Decoded on Display (ADR-ASC-003)

**Decision:** `FrameBuffer` stores the JPEG/PNG bytes and `AnimationView` decodes (downscaled by the image decoder to at most 1280 px) when a frame is shown, caching a handful of decoded frames; a 256 MB total cap drops the oldest frames first, never below two.

**Rationale:** a 3000 px all-sky frame is ~2 MB encoded and ~36 MB decoded; holding 100 decoded frames would cost gigabytes, which matters on a Raspberry Pi 5 (core PC1). Decoding with a scaled size makes the on-display cost small.

### 2.4 One Service, Many Views (ADR-ASC-004)

**Decision:** one `AllSkyService` per plugin owns the timer, the worker thread and the frame buffer; the sidebar page and the dock pane are only views of it.

**Rationale:** an image is downloaded once however many places show it, the options and the dock's open/closed state have one owner, and disabling the plugin has one thing to stop.

---

## 3. Module / Component Design

### 3.1 `allskycam` — AllSkyCam Plugin

- **`allskycam.AllSkyCamPlugin`** (`PluginBase`) — declares `panel_level = "top"`, `panel_label = "AllSkyCam"`, `dock_label = "AllSkyCam"`, paints its own sidebar icon (`panel_icon_painter`), and hands out the page (`build_page`) and the pane (`build_dock_widget`). `activate` creates the service when a Qt application exists; `on_enabled_changed` stops/starts it and closes/reopens the pane (`ASC-090`); `on_dock_visibility_changed` records the pane's state (`ASC-070`). Satisfies `ASC-070`, `ASC-080`, `ASC-090`.
- **`allskycam.config.AllSkyConfig`** — the options as plain data; `from_dict` clamps every numeric to its range and coerces booleans, so corrupt stored values cannot produce a zero interval or a crash. Satisfies `ASC-040`.
- **`allskycam.client`** — `normalize_base_url`/`latest_image_url` (address handling, `ASC-010`), `AllSkyClient.fetch_latest(known_url)` (manual redirect following, content-type check that turns a login page into an explanation, size cap, empty-body check, every failure mapped to `AllSkyError`; `ASC-010`, `ASC-020`) and the `Frame` value (bytes, URL, fetch time).
- **`allskycam.daytime.check_pause`** — compares `galileo.planning.visibility.sun_altitude_deg` for the Observatory location with the configured limit; unknown location or altitude never pauses and returns an explanatory message. Satisfies `ASC-030`.
- **`allskycam.cycle.run_cycle`** — one scheduled fetch: pause check, then fetch, returned as a `CycleResult` (`FRAME`/`UNCHANGED`/`PAUSED`/`ERROR`); never raises, so it is safe on a worker thread. Satisfies `ASC-020`, `ASC-030`.
- **`allskycam.buffer.FrameBuffer`** — the rolling, memory-capped frame set (`ADR-ASC-003`). Satisfies `ASC-060`.
- **`allskycam.service.AllSkyService`** (`QObject`) — owns a repeating `QTimer`, a one-fetch-at-a-time `QThreadPool` job, the `FrameBuffer`, the status text and the options (loaded from, and saved to, `PluginContext.settings()`). Signals: `frame_added`, `status_changed`, `config_changed`, `test_finished`. A result arriving after `stop()` is discarded. Satisfies `ASC-020`, `ASC-040`, `ASC-090`.
- **`allskycam.ui`** — `AllSkyCamPage` (status line, **Fetch now**, Latest/Animation tabs), `LatestView` (`ASC-050`), `AnimationView` (`ASC-060`; timer runs only while shown), `SettingsPage`/`SettingsForm` (`ASC-040`, shown under Options > AllSkyCam via `build_options_page()`, core `PLUG-170`; nothing applies until **Save**; **Test connection** validates locally first), `DockPane` (`ASC-070`).
- **`allskycam/help/plugin.AllSkyCamPlugin.md`** — one section per control (`ASC-090`).
- **Satisfies:** `ASC-010`–`ASC-090`.

### 3.2 Core extension points this plugin required

Added to core `galileo.plugins` and the main window for this plugin (core `PLUG-130`–`PLUG-160`, core SDD Section 4.20): `panel_level = "top"` with `panel_icon_painter()`; `dock_label`/`build_dock_widget()`/`dock_initially_visible()`/`on_dock_visibility_changed()` and `PluginContext.set_dock_visible()`; `PluginContext.settings()`; `PluginContext.site_location()`; and `PluginBase.on_enabled_changed()`.

---

## 4. Data Design

| Data | Format | Storage |
|---|---|---|
| Options (address, camera, interval, image count, daytime pause and limit, speed, pane shown) | JSON-valued keys | Galileo's shared database, `app_settings` table, namespace `plugin.AllSkyCamPlugin` (core `PLUG-150`) |
| Recent images | JPEG/PNG bytes | Memory only; not persisted |

The plugin adds no table or migration of its own.

---

## 5. Interface Design

- **Plugin boundary:** depends only on `galileo.plugins` (`PluginBase`, `PluginContext`) and the solar-position helper `galileo.planning.visibility.sun_altitude_deg`; no import of `galileo.ui.*` internals other than the in-test help audit.
- **External interface added:** HTTP(S) `GET <server>/latestimage[?camera_id=N]` and the image URL it redirects to, to a user-configured host.

---

## 6. Path to Traceability Matrix

A row per requirement ID in [this plugin's SRS](SRS.md), mapped to the module above and a test case ID — see [RTM.md](RTM.md).
