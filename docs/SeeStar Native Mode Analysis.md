# SeeStar Native Mode Analysis

**Status:** analysis only; nothing described here is implemented. **Date:** 2026-11-26.

## 1. Summary

A native mode would drive a ZWO Seestar over its own JSON-RPC protocol (TCP 4700) instead of its Alpaca bridge. The reason to do it is **on-device recording**: the Seestar stacks and stores subframes on its own storage, and Galileo collects them afterwards. No route to this through the Alpaca bridge has been found.

**Recommendation**

- Build it as a first-party **Seestar plugin** that talks the protocol itself.
- Add a small set of **core extension points** first. Several are missing today (Section 4).
- Make version 1 "native control plus record on device": mount, focuser, filter wheel and recording. Leave a native *camera* (single frames returned to Galileo) for later.
- Run a **hardware spike** before committing. The protocol is reverse-engineered, and the public sources disagree on points this feature depends on.

**Decisions needed**

| Decision | Recommendation |
|---|---|
| Plugin or core | Plugin, with generic extension points in core |
| Own client or the `seestarpy` library | Own small client, using `seestarpy` as a reference (Section 5.2) |
| Authentication key | The user supplies it; Galileo never ships or extracts it (Section 3.2) |
| Native camera in version 1 | No |

## 2. What exists today

| Area | Current state |
|---|---|
| Control | INDI or Alpaca only. `EXT-020` says device drivers are reached *only* through those two. |
| Seestar over Alpaca | Mount, camera (including the S30 Pro's wide camera), focuser, filter wheel and switch through the standard adapters in `galileo/adapters/alpaca/`. |
| Capture | `ImagingService.capture_series` takes one frame at a time through `start_exposure` then `get_image_array`; Galileo writes the FITS file, stacks and registers it. |
| File retrieval | Library download over SMB (`galileo/library/services/telescope_smb.py`): share `EMMC Images`, folder `MyWorks`, only folders ending `_sub`. Downloaded Seestar frames are marked pre-calibrated (`LIB-090`). |
| Power | The SwitchBot Bot plugin can press the Seestar's power button. |

The download half of a record-on-device workflow therefore already exists. What is missing is the ability to start, watch and stop the recording.

## 3. The native protocol

Everything here comes from the community projects [seestarpy](https://github.com/astronomyk/seestarpy) (GPL-3.0, Python 3.11+) and [seestar_alp](https://github.com/smart-underworld/seestar_alp) (GPL-3.0), not from ZWO. **None of it has been tested against hardware for this analysis.**

### 3.1 Transport

| Item | Detail |
|---|---|
| Commands and events | TCP 4700, JSON messages ending `\r\n`; replies matched by `id`; unsolicited `Event` messages arrive on the same socket |
| Images | TCP 4800 (binary); 4804 is also mentioned, role unconfirmed |
| Discovery | UDP 4720, `scan_iscope` broadcast |
| Keepalive | The scope drops an idle socket after about 15 s (measured on firmware 8.89); ping about every 5 s |
| Several clients | Apparently allowed; limits and guest/master arbitration with the phone app are undocumented |

### 3.2 Authentication (firmware 7.18 and later)

Each connection must pass `get_verify_str` → sign the challenge (RSA, SHA-1) → `verify_client` → `pi_is_verified`. The private key is one shared key embedded in ZWO's Android app. `seestarpy` does not ship it; users extract it from the app package.

This has consequences:

- Galileo must not bundle, download or extract the key. The user points Galileo at a PEM file they obtained.
- `seestarpy`'s [authentication page](https://seestarpy.readthedocs.io/en/latest/info/authentication.html) discusses the US DMCA and EU law. **Get a view on this before shipping the feature**; this analysis does not give one.
- ZWO can change the key or the scheme in any firmware or app release.
- Store the key's file path in the plugin's database settings. Putting the key itself in the OS keychain is an alternative, but check the Windows Credential Manager size limit first.

### 3.3 Commands needed

| Function | Method | Confidence |
|---|---|---|
| Site and time | `set_user_location`, `pi_set_time` | Good. Must run on every connect, as the Alpaca mount adapter does. |
| Slew only | `scope_goto` `[ra_hours, dec_deg]` | Good; equinox (J2000 or JNow) unconfirmed |
| Slew, centre and view | `iscope_start_view` (`mode`, `target_ra_dec`, `target_name`, `lp_filter`) | Good |
| Start / stop stacking | `iscope_start_stack` `{restart}`, `iscope_stop_view` | Good |
| Exposure, gain | `set_setting` `{exp_ms: {stack_l}}`, `set_control_value ["gain", n]` | Good |
| **Keep subframes** | `set_stack_setting` `{save_discrete_frame, save_discrete_ok_frame}` | **Conflicting.** seestar_alp uses it; seestarpy says it was removed at firmware 6.7 and the options moved into `set_setting`'s `stack` block. |
| Filter wheel | `set_wheel_position`, `get_wheel_position` | **Conflicting** position meanings |
| Focuser | `move_focuser`, `get_focuser_position`, `start_auto_focuse` (sic) | Good |
| Park | `scope_park` | Good; how to *confirm* parked needs testing |
| Dew heater | `pi_output_set2` | Fair |
| State | `get_device_state`, `get_view_state`, `iscope_get_app_state` | Good; full payloads undocumented |
| Unattended plan | `set_view_plan`, `stop_func {name: "ViewPlan"}` | Fair; has known quirks |

Long operations report through events with states `working`, `complete`, `fail`, `cancel`. A finished operation can be reported twice, and only the outer message is the real end. The client must handle that.

## 4. Gaps in core

| # | Gap | Evidence | Change |
|---|---|---|---|
| G1 | **Plugin device backends are never used.** `register_device_backend` appends to `DeviceBackend.registered_backends`, but only tests read it. | `galileo/plugins/__init__.py`, `galileo/core/devices.py` | A single backend registry keyed by driver name, consulted by every factory |
| G2 | The driver lists are hard-coded to `["Alpaca", "INDI"]` | Equipment pages under `galileo/ui/app_window/` | Populate them from the registry, per device category |
| G3 | Adapter construction is repeated, and anything that is not `"INDI"` is treated as Alpaca | `galileo/engine/devices.py`, `galileo/device_ops.py`, `_imaging_support.py`, `_camera_page.py`, `_device_config_page.py` | One shared factory; an unknown driver is an error, not Alpaca |
| G4 | There is no port for a device that records by itself | The camera port assumes Galileo asks for each frame | New `OnboardRecorder` port (Section 5.4) |
| G5 | `SessionContext` has no recorder, and stopping aborts only camera and mount | `galileo/session_exec.py` | Add the field; stop the recorder in `_abort_hardware` |
| G6 | The protective stop aborts only camera exposures and mount slews | `galileo/engine/guard.py`, `galileo/safety_supervisor.py` | Stop recording **before** parking; check `galileo/ui/safety_host.py` too |

G1 to G3 are worth fixing even without Seestar support: `PLUG-010` and `ARCH-070` say a plugin can add a backend, and a registered one cannot currently be picked through these lists. Confirm how the three switch plugins reach their pages before changing this, so they keep working.

No database migration is expected: `DeviceConfigRecord.driver` is free text, and plugin settings already live in the database (`PLUG-150`).

## 5. Proposed design

### 5.1 Layout

```
Galileo-Plugins/seestar/
  client.py      protocol: socket, framing, authentication, keepalive, events
  session.py     one shared connection per scope, reference counted
  mount.py       mount port
  focuser.py     focuser port
  filters.py     filter wheel port
  recorder.py    onboard recorder port
  blocks.py      "Seestar Record" session block
  settings.py    key path and recording defaults
```

### 5.2 Client

- **One connection per scope, shared** by its mount, focuser, wheel and recorder adapters. Galileo builds one adapter per device category, so they must find each other by host and port.
- **Its own reader thread**, like `galileo/adapters/indi_client.py`. Parts of Galileo call adapters with a fresh `asyncio.run`, so a socket tied to one event loop would break.
- **Two or more scopes at once** must work (the reference observatory has an S30 and an S30 Pro). No module-level connection state.
- **Own code rather than `seestarpy`:** only a small part of it is needed, the threading model has to be Galileo's, and its API has had breaking changes. Whether `seestarpy` handles several scopes cleanly was not checked; if it does, revisit this. If any code is copied, keep its GPL notices.

### 5.3 Device adapters

| Adapter | Notes |
|---|---|
| Mount | Core passes degrees, so convert RA to hours. Refuse motion while parked, apply the slew guard (as the Alpaca adapter does), report `equatorial_system` once confirmed, and report parked only when the scope confirms it. |
| Focuser | Read the travel range from the device. |
| Filter wheel | Verify position meanings on each model. Position 0 closes the shutter. |
| Switch (later) | Dew heater. |
| Camera (deferred) | Would need `start_exposure` and the image port, whose payloads are the least documented. |

Without a native camera, Galileo's own preview, plate solving, autofocus, framing and live stacking are unavailable in native mode. The Seestar's own goto-and-centre and autofocus stand in.

### 5.4 Recorder port

A new port in `galileo.core.devices`, deliberately not Seestar-specific:

```python
class OnboardRecorder(Protocol):
    async def start_recording(self, *, target: str, ra: float, dec: float,
                              exposure_s: float, gain: int | None,
                              filter_name: str, keep_subframes: bool) -> None: ...
    async def stop_recording(self) -> None: ...
    async def recording_status(self) -> RecordingStatus: ...   # state, stacked, rejected, free space, error
```

Progress goes out on the event bus, so the UI and history subscribe rather than call the plugin.

### 5.5 Sessions

A **Seestar Record** block: target, sub-exposure, gain, filter, and an end condition (duration, number of stacked frames, or clock time), plus "keep subframes" (on by default).

- It checks free storage first and fails clearly if the scope reports an error or stops by itself.
- Stop, skip and unsafe conditions all call `stop_recording`.
- Check how the Sessions editor offers plugin block types; `PLUG-020` requires it, but the editor side was not verified here.

Dithering, guiding and meridian-flip blocks do not apply. Handing a whole night to `set_view_plan` is a later option: it survives a network drop, but Galileo's safety stop could not reach a disconnected scope.

### 5.6 Getting the files

Reuse the existing SMB download. Additions:

- A "download when recording ends" option, using the host already known from the connection.
- Fetch only this run's files.
- Link them to the Galileo session, as `LIB-160` does for captured frames, matching on target and time.
- Never delete from the scope automatically.

Confirm that recordings started natively land in the same `_sub` folders, with the same headers, as app recordings. Per-frame history (HFR, star count) is only available after download.

### 5.7 UI

- A "Seestar" driver on the Mount, Focuser and Filter Wheel pages.
- A plugin settings page: key file, defaults, and a **Test connection** button reporting firmware and authentication result.
- A recording panel (Imaging screen or dock): state, frames stacked and rejected, storage, Stop.

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Firmware update breaks the protocol or authentication | Feature stops working | Show tested firmware versions, warn on others, keep Alpaca as the fallback |
| Legal position on the key | May block release | Decide before building (Section 3.2) |
| Scope keeps recording after Galileo disconnects or crashes | Safety stop cannot reach it | Say so in the help; on reconnect, detect a running recording and adopt or stop it |
| Phone app or Alpaca client used at the same time | Commands interfere | Show state changes Galileo did not request. Community analysis says each Alpaca exposure stops a running stack, so block mixing the two drivers on one scope. |
| Park cannot be confirmed | Roof logic could act on a wrong state | Treat unknown as not parked |
| Models differ (S50, S30, S30 Pro, dual camera) | Subtle failures | Test each model supported; claim only those |

## 7. Plan

Sizes are rough estimates for one developer who has a Seestar.

| Phase | Content | Size |
|---|---|---|
| 0. Spike | Script on real hardware: authenticate, set site and time, goto, record with subframes kept, stop, download. Settle the two conflicts, equinox and park confirmation. | 2–4 days |
| 1. Core | G1–G3: backend registry, one factory, dynamic driver lists | 3–5 days |
| 2. Plugin base | Client, shared session, mount, focuser, wheel, settings | 1–2 weeks |
| 3. Recording | G4–G6, recorder adapter, session block, panel, safety stop | 1–2 weeks |
| 4. Files | Auto-download and session linking | 3–5 days |
| Later | Native camera, live stacked preview, view plans, dew heater | — |

Stop after phase 0 if subframe saving cannot be controlled reliably or the key question is not resolved. The existing alternative (record with the Seestar app, download with the Library) keeps working.

## 8. Tests and documents

**Tests:** a fake Seestar server (framing, authentication with a test key, interleaved events, idle disconnect, error codes); adapter tests against it; session tests proving stop, skip and unsafe all end recording and that stop precedes park; `hardware`-marked tests for the real scope.

**Documents** to update as each phase lands:

- `docs/plugins/seestar/{PSD,SRS,SDD,RTM}.md` for the plugin's own requirements.
- Core `SRS.md`: widen `EXT-020` (plugin backends may use other protocols); add requirements for the recorder port and for stopping on-device recording in a protective stop. `SDD.md` and `RTM.md` to match.
- Plugin help, the Equipment and Sessions help files, the wiki, `README.md` and `CHANGELOG.md`.

## 9. Not verified

- No command was sent to a Seestar.
- Payloads for file listing and deletion, and the image stream, are not established. The design uses SMB and has no native camera, so version 1 does not depend on them.
- Firmware behaviour after 9.x, and differences between models.
- The Alpaca bridge behaviour cited here comes from [one third-party analysis](https://github.com/astronomyk/seestarpy/issues/4) of the decompiled server.
