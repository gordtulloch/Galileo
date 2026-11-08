# Galileo Mobile App — Recommended Features

**Status:** Draft for review. Not yet reflected in any SRS.
**Sources:** `Comparison of Functions.md` (ASIAIR baseline), `Competitive-Review.md` (rivals), MobileConnect SRS (`MCON-*`) and app PSD.
**Scope:** Gaps in the *anticipated mobile feature set*. The app operates an observatory and never configures it (PSD §5), so core-only gaps are listed separately at the end.

---

## Summary

The planned feature set already covers the ASIAIR's operating functions and goes further: a per-Pier lease instead of the single-controller rule, Viewer and Operator roles, multi-Pier and multi-node, outreach guest mode and a red theme. The gaps below are specific and mostly small. Power and dew, a demo mode and node health are cheap and should come first. Alerts and the Guiding Assistant need a design decision.

## Recommended additions

### High priority

| # | Feature | Why | Affects |
|---|---|---|---|
| 1 | **Alerts while the app is closed**: keep D4 (no app push) but document the route: Galileo's own notification channels on the Master (Pushover, ntfy, email) | Competitors alert on sequence end, guiding lost and safety stop. Users expect it for unattended nights | PSD D4, `MCON-340`, docs only |
| 2 | **Power and dew control**: numeric/PWM switch values (dew heater %) and read-only per-port power telemetry | `MCON-420` only toggles switches. SynLink has adjustable dew power. The ASIAIR manual's top crash cause is overloaded ports | `MCON-420`, core switch port |
| 3 | **Demo observatory mode** in the app (the iOS mock Master, user-visible) | First-night training (SynLink simulators). App Store and Play reviewers have no observatory to test with | New `MCON-8xx` |
| 4 | **Guiding depth**: tap-to-select guide star; Guiding Assistant run and results once core has it | `MCON-460` covers start, stop, dither, recalibrate and trace only | `MCON-460`, core |

### Medium priority

| # | Feature | Note |
|---|---|---|
| 5 | **Node health and shutdown/restart**: disk free, CPU temperature, input voltage; confirmed, audited shutdown for a headless Pi | The ASIAIR has a shutdown slider. Nothing equivalent is planned |
| 6 | **Pre-run summary**: estimated total time, storage needed, time to flip, storage free | The ASIAIR Autorun shows these before start |
| 7 | **Polar alignment live loop**: state that live error and refresh must stream to the app | Where a tablet at the mount matters most. `MCON-450` is silent on it |
| 8 | **Library frame to GOTO**: slew to the field of a stored frame | The ASIAIR offers it. Cheap link between `MCON-540` and `MCON-440` |
| 9 | **Save or share a preview to the phone** (JPEG to camera roll or share sheet) | `MCON-620` covers FITS download only |
| 10 | **Annotate a solved frame** with object labels | The ASIAIR "Annotate". Not in `MCON-430` or `MCON-450` |
| 11 | **Target import** (paste or share-sheet CSV, e.g. Telescopius) | Needs a PSD §6.4 ruling: target list vs stored definition |
| 12 | **Focus detail**: per-filter offsets, aberration/tilt result (`FOC-080`), per-run autofocus parameters | `MCON-470` omits them. `MCON-570` already permits per-run parameters |
| 13 | **Tonight view and forecast**: twilight, Moon, altitude graphs, cloud forecast | Seestar offers a forecast. We show live weather only |
| 14 | **Several saved Masters** (named, including VPN addresses) | `MCON-830` is silent on more than one |
| 15 | **Live-stack control**: start, reset and parameters, not view only | `MCON-430` says "view" |

### Decisions needed

- **Custom objects and favourites**: target data or configuration? (PSD §6.4)
- **Phone GPS and time to the Master** for portable setups: in scope or not? Site and time are configuration today.
- **Phone layout** (O2): which of the above reach the phone.

### Confirm as deliberate non-goals

Video/planetary capture, AI denoise and gradient removal (core first), iOS Live Activities and widgets (blocked by no-push), Windows app (WebConnect covers it), internet/cloud access (excluded by design).

## Core gaps the app inherits (track in core, not here)

Constraint-based scheduler and artificial horizon, smart exposure advisor, backlash compensation, atomic updates with rollback, Guiding Assistant itself, manual-filter FITS metadata, session analytics and sub grading.

## Suggested next step

Turn items 1–4 into `MCON-*` requirements with RTM rows once this list is agreed.
