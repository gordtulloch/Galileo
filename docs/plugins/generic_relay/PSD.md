# Generic Relay Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — Generic Relay Plugin (generic HTTP-toggled Internet relay board control) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-05 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose of This Document

This document defines the scope of the **Generic Relay plugin** — a first-party Galileo plugin that controls relay boards whose only control surface is a plain HTTP GET per relay/state combination, a pattern common to cheap ESP8266/Arduino-based Ethernet relay boards with no vendor SDK or structured API. It follows the same PSD→SRS→SDD→RTM structure as [the core document chain](../../PSD.md) and [the VSTarget plugin's chain](../vstarget/PSD.md).

This document intentionally stays above implementation detail — no URL-template syntax or class designs. Those belong in [SDD.md](SDD.md).

## 2. Background and Motivation

Galileo's core SRS reserves `EQP-SW-010` (enumerate switch/relay devices and their read/write state) at P2, satisfied in core by the generic INDI/Alpaca Switch adapters behind the Equipment > Switches screen. That screen is intentionally left unpopulated for now. A great many relay boards in observatory use — the kind that open/close a roll-off roof or power-cycle a piece of equipment — speak neither INDI nor Alpaca and have no common HTTP API either: each board's firmware exposes relay control as whatever fixed URL its author happened to wire up, e.g. (the motivating example, originally used to pulse a roof-control relay):

```
http://10.0.0.101/30000/01   # relay 1 on
http://10.0.0.101/30000/00   # relay 1 off
```

There is no vendor-neutral way to talk to "a relay board" the way INDI/Alpaca gives a vendor-neutral way to talk to "a mount." This plugin's answer is to make the URL itself configurable — host, relay count, and a template string the user fills in to match their own board — rather than hard-coding support for one specific vendor's firmware.

## 3. Vision Statement

> The Generic Relay plugin lets a Galileo user with an HTTP-toggled relay board in their observatory — whatever its exact URL scheme — control and monitor it directly from Galileo, by describing that scheme once as a template rather than waiting for vendor-specific support.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver generic relay-board control as the `RELAY` plugin — a first-party plugin distributed as a downloadable ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled once installed (core `PLUG-060`). The plugin is **not** bundled in the Galileo installer; users install it from the in-app Plugin Marketplace or by selecting the downloaded ZIP via Install from file |
| G2 | Register a Switch device backend (core `ARCH-070`/`PLUG-010`, satisfying `EQP-SW-010`) that toggles a relay by issuing an HTTP GET built from a user-supplied URL template, rather than a fixed vendor API |
| G3 | Default that template to reproduce the motivating example exactly, so the common case needs no editing, while remaining fully overridable for a board with a different scheme |
| G4 | Present a panel (core `PLUG-070`, secondary nav level) where any number of relay boards can be added side by side, each as its own tab, with a table of that board's relays (identifier + On/Off status) that toggles on click |

## 5. Non-Goals (Explicitly Out of Scope)

- **No hardware readback.** Most boards in this class expose no endpoint to query current relay state; a switch's displayed status is the last state *this plugin* commanded, not a polled hardware readout. This is stated as a non-goal rather than a defect because there is, in general, nothing to poll.
- **No momentary/pulsed relay mode.** The motivating example's original use (pulse a roof relay on, wait, then off) is a timed, momentary action; this plugin instead treats every relay as a simple persistent on/off switch, matching the table-with-toggle UI this plugin shares with the Kasa Switch plugin. A pulsed/momentary action belongs to the sequencer's own instruction-block layer (core `SES`), not this device backend.
- **No auto-detection of board type or URL scheme.** The user supplies the host, relay count, and URL template directly; there is no board-identification step.
- **No changes to the Equipment > Switches screen or its generic INDI/Alpaca Switch adapters.** This plugin is a separate, self-contained path to Switch control for HTTP-only boards, not a replacement for or an extension of that screen.

## 6. Dependencies on Galileo Core

This plugin is a client of the following core capabilities — each is an existing, unchanged core requirement this plugin's own requirements (Section 7) trace to, not something this document specifies:

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Discovered/loaded/isolated the same as any plugin |
| Installable-plugin enable/disable | `PLUG-060` | Independently toggleable once installed |
| Secondary-level UI panel insertion | `PLUG-070` | The Internet Relay panel is a secondary panel, not a peer to a built-in primary section |
| Device backend registration | `ARCH-070`/`PLUG-010` | `GenericRelayAdapter` is registered for `DeviceCategory.SWITCH` via `PluginContext.register_device_backend` |
| Switch device port semantics | `EQP-SW-010` | This plugin's backend satisfies the same read/write switch-state contract the generic INDI/Alpaca Switch adapters do — boolean switches only, and write-only in effect given Section 5's no-readback non-goal |

## 7. Functional Requirement Domains (Scope-Level)

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `RELAY` | Generic Internet Relay Control | Configurable host/relay-count/URL-template HTTP relay toggling, default-template fidelity to the motivating example, error handling, and the tabbed add/remove panel UI | MVP |

## 8. Stakeholders and Primary Persona

| Persona | Description | Primary Interests |
|---|---|---|
| Observatory Operator | Has an HTTP-toggled Ethernet relay board controlling observatory equipment power or a roll-off-roof relay | Being able to drive *their specific board's* URL scheme from Galileo without waiting for named-vendor support |

## 9. Assumptions and Constraints

- **PC1** — The relay board is reachable via plain HTTP on the same LAN as the Galileo host (or otherwise routable); the plugin issues an unauthenticated GET and does not implement any particular board's auth scheme.
- **PC2** — Because there is no common API across boards in this class, correctness of a specific installation depends on the user supplying an accurate URL template for their hardware — the plugin can only guarantee that its *default* template reproduces the documented motivating example exactly (traces to `RELAY-010`).
- **PC3** — No readback means a restart, or Galileo simply not having been running when a relay was toggled by some other means, leaves the panel's displayed state potentially stale until the next toggle from within Galileo. This is accepted (Section 5 non-goal) rather than worked around.

## 10. Risks

| Risk | Impact | Notes |
|---|---|---|
| A misconfigured URL template silently toggles the wrong relay, or none at all | Medium | The template is plain text the user can inspect/edit directly in the Add dialog; the default reproduces a known-correct example exactly so most users need not construct one from scratch |
| No readback means displayed state can drift from reality if a relay is toggled outside Galileo | Low | Explicit non-goal (Section 5); a user who also controls the board another way should expect the display to reflect only Galileo's own last command |

## 11. References

- The motivating example (pasted into this plugin's design discussion): a roof-control relay toggled via `http://10.0.0.101/30000/01` (on) / `http://10.0.0.101/30000/00` (off)
- [Galileo Core PSD](../../PSD.md) — the parent scope document this plugin depends on, particularly Section 8's `PLUG` domain
- [Galileo Plugins repository](https://github.com/gordtulloch/Galileo-Plugins) — this plugin's source and distribution

## 12. Glossary

Terms not already defined in [Galileo core PSD's Glossary](../../PSD.md#15-glossary) apply unchanged; the following are specific to this plugin:

| Term | Definition |
|---|---|
| URL template | A `str.format()` string with `{ip}`/`{port}`/`{state}` placeholders describing how this specific board's firmware expects a relay-toggle URL to be built |
| `port` (template placeholder) | The *zero-based* relay index within the URL template — relay 1 is `port=0`, relay 2 is `port=1`, etc. — distinct from a network port number |

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's PSD](../../PSD.md).*
