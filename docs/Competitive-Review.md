# Competitive Review — Features Beyond the ASIAIR Baseline

Companion to **Functions.md**. Functions.md describes what the ZWO ASIAIR app does. This document looks at similar controllers and control software and lists functions they offer that the ASIAIR does not, or does only partly. Each one is a candidate for a comparable app.

*Research date: November 2026. Feature claims come from vendor pages, changelogs, reviews and user forums (see Sources). Items marked "user request" come from the ZWO forum and show demand that hasn't been met, not a competitor's feature.*

---

## 1. Products reviewed

| Product | Type | Platform / openness | Why it matters |
|---|---|---|---|
| **Sky-Watcher SynLink** | Dedicated controller + app (Android, iOS, macOS, Windows) | Proprietary app, multi-brand hardware. Launched Oct 2026. | The newest and most direct ASIAIR rival, from a major mount maker. See §1a. |
| **StellarMate (X, Pro, OS)** — Ikarus | Dedicated controller + phone app | Linux, KStars/Ekos/INDI. Multi-vendor. | Closest full-featured rival. Fast release cadence (OS 2.3, Aug 2026). |
| **KStars / Ekos** | Control suite (runs StellarMate) | Cross-platform, open source | Reference for scheduling, focus analysis and session analytics. |
| **N.I.N.A.** | Windows acquisition suite | Open source, plugin ecosystem | De facto power-user benchmark. Its plugins define "advanced". |
| **PrimaLuceLab EAGLE6** | Windows 11 field computer | Open (any Windows software) | Benchmark for power management and on-board sensors. |
| **RB Focus Gaius-S2** | Windows mini-PC controller | Open, NINA/ASCOM preinstalled | Automatic dew control and switchable ports driven from the sequencer. |
| **ToupTek StellaVita** | ASIAIR-style box + app | Proprietary app, multi-brand hardware | The direct "ASIAIR, but brand-agnostic" competitor. |
| **AStarBox / AstroLink 4 Pi** | Raspberry Pi 5 hubs | Open (INDI, StellarMate OS, etc.) | High-current power and DIY openness. |
| **Pegasus Astro Unity** | Device control platform | Server + UI + ASCOM/Alpaca | Multi-client hub architecture. NYX mount uses environmental sensors. |
| **SharpCap Pro** | Capture software | Windows | Exposure optimization from measured sky brightness. |
| **PHD2** | Guiding software | Open source | Guiding diagnostics the ASIAIR guider lacks. |
| **Seestar app (ZWO)** | Smart-telescope app | Proprietary | Shows ZWO's own consumer-UX direction (AI processing, auto plans). |
| **Unistellar app** | Smart-telescope app | Proprietary | Citizen-science network model. |

---

## 1a. Sky-Watcher SynLink — closest new rival

SynLink is Sky-Watcher's ASIAIR-style box: a mini-PC, USB hub and power distributor in one unit, run from a free app. It went on sale in Europe and Australia first. Japan's release was 23 October 2026 (¥97,900). US retailers list it at $599, at pre-order or launch stage.

### Hardware (vs ASIAIR Plus)
| Item | SynLink | ASIAIR Plus |
|---|---|---|
| Processor / RAM / storage | Rockchip RK3566, 4 GB, 64 GB | RK series, up to 256 GB |
| USB | 4 × USB 3.0, 2 × USB 2.0, 1 × USB-C | 2 × USB 3, 2 × USB 2, USB-C |
| 12 V outputs | 4 outputs. Sky-Watcher USA: 5 A each, 10 A total. *A retailer quotes 7 A each, 14 A total, so confirm with the final spec.* | 4 outputs, under 3 A each and 6 A total |
| Power input | 9–16 V DC, two DC inputs, reverse-polarity protection | Single 12 V input |
| **Dew heaters** | **2 independent RCA channels with adjustable power in the app** | None (12 V port on/off only) |
| **Direct mount port** | **Serial (UART/RJ12) port and cable for Sky-Watcher/Synta mounts, no USB adapter needed** | USB or EQMOD cable required |
| Network | Dual-band Wi‑Fi. Ethernet through a USB adapter. | Wi‑Fi + built-in Ethernet |
| Weight / size | About 250 g without dovetail kit, 109 × 68 × 27 mm | Similar |

### Software
- **Multi-brand devices:** cameras (most astro brands plus Canon, Nikon, Sony and Fujifilm bodies), mounts (Sky-Watcher SynScan and legacy, Celestron AUX or through the handset, iOptron, ES/Losmandy PMC-Eight, ZWO, Takahashi), focusers, filter wheels, rotators and **flat panels**. Most are auto-detected.
- **App on four platforms** (Android, iOS, macOS, Windows 7+). ASIAIR has no native Windows app.
- **EASY mode / PRO mode:** EASY builds a night from exposure, gain and count. PRO adds advanced, scripted sequencing. This is the two-tier UI this review recommends.
- **Sequence options:** dithering, autofocus triggers, **cloud recovery**, meridian-flip behavior, and park plus controller shutdown at the end.
- **Built-in device simulators:** practice polar alignment, guiding and sequences indoors with no gear connected.
- Guided polar alignment, focusing wizard, multi-star guiding, plate-solved GoTo with auto-centering, Tonight's Best and a sky map with nebula overlays.
- Capture modes: single exposure, mosaic, simple and advanced sequences, video. Live stacking for EAA.
- **Built-in remote access over the internet.**

### What SynLink adds over ASIAIR
Brand openness (including flat panels and non-ZWO cameras), app-controlled dew heaters, more power headroom, a direct mount serial port, a Windows app, simple and pro sequencer modes, simulators, and cloud recovery.

### Where ASIAIR still leads
Larger storage (256 GB), built-in Ethernet, a mature and well-documented ecosystem (CAA, EAF filter offsets, AM-mount integration), and years of field use. SynLink is brand new: real-world reliability and the full device list are still unproven.

---

## 2. Gap analysis by function area

Priority key: **P1** = expected by serious users and offered by several rivals. **P2** = strong differentiator. **P3** = niche or longer-term.

### 2.1 Hardware openness and device support
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Multi-vendor camera, focuser, wheel and rotator support** through standard driver layers (INDI, ASCOM Alpaca) | SynLink (cameras incl. DSLR/mirrorless, mounts, focusers, wheels, rotators, flat panels), StellarMate (full INDI driver set, added Alpaca devices in 2.2), StellaVita (has run ZWO cameras alongside its own), EAGLE/Gaius (any Windows driver), AStarBox (any Pi software) | Mostly ZWO devices plus a list of mounts | **P1** |
| **Network devices** (Alpaca over Wi‑Fi, controlling a smart scope as a device) | StellarMate 2.2 (Alpaca, Seestar) | No | P2 |
| **Direct serial mount port** (no USB/EQMOD adapter) | SynLink (UART for Sky-Watcher/Synta mounts) | No | P3 (hardware) |
| **Third-party flat panels, domes, weather stations, safety monitors** | SynLink (flat panels), StellarMate/Ekos, NINA | No (flat-panel support is a user request) | P1 for flat panels, P2 for observatory gear |
| **Alt-az mount support with plate-solved GOTO and tracking** | Users report it as missing or unreliable on ASIAIR (user request). Open INDI/ASCOM stacks are the usual workaround. | Unreliable for alt-az | P2 |
| **Dual-rig sync** (one master controls the mount, a second unit follows dither and pause) | NINA and Ekos workarounds | Missing. A long-running user request ZWO has called complex. | P2 |

**Takeaway:** The ASIAIR's biggest structural weakness is lock-in. A comparable app should build on a device-abstraction layer (INDI and/or Alpaca) from day one, even if it ships with a curated "certified" device list for simplicity.

### 2.2 Power, environment and observatory sensing
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Per-port current measurement** and input power monitoring | EAGLE6 | Total input only (Plus) | **P1** — the manual's top crash cause is overloaded ports |
| **Automatic dew-heater control** from temperature and humidity (dew point), with PWM outputs | SynLink (2 dedicated channels, power adjustable in the app), Gaius-S2 (included sensor, PWM ports), EAGLE | Manual on/off. Heater state isn't remembered (user request). | **P1** |
| **Power ports as sequence steps** (switch on or off during a plan) | Gaius-S2 through ASCOM Switch in NINA | Manual only | P2 |
| **High-current distribution** (e.g. 30 A, auto-resetting fuses, XT60) | AStarBox. SynLink (5 A per port, 10 A total, dual inputs, reverse-polarity protection). | 6 A total | P2 (hardware) |
| **Built-in GPS, real-time clock** | EAGLE6 and StellarMate Pro (GPS), AStarBox (RTC) | Uses the phone's GPS or a map | P2 |
| **Sky-quality (SQM-style) sensor** | EAGLE6 "EYE" | No | P3 |
| **Inclinometer, motion detector** (bump detection, level check) | EAGLE6 | No | P3 |
| **Dark mode for all LEDs** | EAGLE6 | No | P3 (cheap win) |
| **Observatory relay inputs and outputs** (roof, dome, alarms) | EAGLE6 control ports, Ekos startup/shutdown scripts | No | P3 |
| **Barometric and temperature refraction correction** in pointing | Pegasus NYX mounts | No | P3 |

### 2.3 Planning and scheduling
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Constraint-based dynamic scheduler** that picks the best target in real time by altitude, twilight, Moon and priority | Ekos Scheduler, NINA Target Scheduler plugin | Plan mode runs fixed time slots | **P1** |
| **Artificial horizon / custom obstruction map** used by the scheduler | Ekos (horizon and ceiling constraints) | No | **P1** |
| **Multi-night projects** with exposure goals and progress tracking | Target Scheduler, StellarMate 2.1 multi-night scheduler | Plan saves progress across nights, but without goal-based planning | P2 |
| **Automatic sub grading** (reject frames by HFR, FWHM, eccentricity, star count) and re-schedule the missing time | NINA Target Scheduler (with Hocus Focus) | No | P2 |
| **Logic-based sequencer** (conditions, loops, triggers, "loop while safe", error recovery) | NINA Advanced Sequencer, Ekos Task Queue, SynLink PRO mode (advanced scripting) | Linear Autorun | P2 (advanced mode) |
| **Weather and safety interruption** (pause when cloudy, resume when safe) | SynLink ("cloud recovery" sequence option), NINA, StellarMate 2.1 scheduler with Safety Monitor | No | **P1** for unattended use |
| **Several plans with different start and stop windows**, copy targets between plans | User request | No | P2 |
| **One-tap auto plan** for beginners | Seestar app 3.3 | No | P2 |
| **In-app weather and visibility forecast** | Seestar app | No | P2 |

### 2.4 Guiding
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Guiding Assistant**: unguided drift measurement, periodic error, polar error, Dec backlash test, recommended settings | PHD2 | No | **P1** — the manual's guiding chapter is mostly manual tuning advice this would replace |
| **Adaptive Dec backlash compensation** | PHD2 | No | P1 |
| **Predictive PEC algorithm** for RA | PHD2 | No | P2 |
| **"Advanced" guiding settings panel** (min-move, algorithm choice) | PHD2, NINA | ZWO hides these to keep things simple (repeated user request) | P2 |
| **Auto-tuning or AI guider** that adjusts aggressiveness and limits during the session | StellarMate 2.3 "AI Guider" (vendor claim, few details yet). Users ask ZWO for the same. | No | P2 (differentiator) |
| **Guide-log analysis in the app** | Ekos Analyze. PHD2 logs plus external viewer. | External tools only | P2 |

### 2.5 Focus and optical diagnostics
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Aberration inspector**: autofocus on 9 sensor tiles to measure tilt and back-focus | Ekos (since 3.6.8), NINA Hocus Focus | No | **P1** for large sensors |
| **Tilt-correction advisory** (which screw to turn, how much) | StellarMate 2.3, Ekos | No | P2 |
| **Multiple autofocus algorithms** (e.g. Linear 1-Pass) and quality metrics (R²) | Ekos | Single parabola fit | P2 |
| **Preferred focus filter** (focus through L, then apply offsets) | NINA. ASIAIR user request. | Focuses with whatever filter is in place | P2 |
| **Collimation assistant** using defocused stars | User request | No | P3 |
| **Motorized tilt adjuster support** (e.g. Wanderer ETA) | StellarMate 2.2 | No | P3 |

### 2.6 Exposure and image-quality guidance
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Smart exposure calculator**: measure sky background, combine with sensor analysis, recommend gain and sub length | SharpCap Pro (Smart Histogram "Brain", also as a sequence step) | No. The manual relies on rule-of-thumb tables. | **P1** |
| **Live seeing, FWHM and eccentricity trends** per sub | NINA (Hocus Focus), Ekos Analyze | HFD per frame only | P2 |
| **Manual-filter metadata** written into FITS (for filter drawers) | User request | No | P1 (trivial, high annoyance) |

### 2.7 Polar alignment and mount modeling
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Three-point polar alignment anywhere in the sky** (no meridian-flip side constraints) | NINA TPPA plugin, Ekos | All-Sky PA exists. The manual's author finds it less accurate. | P2 |
| **Pointing and tracking mount model** | StellarMate 2.2 ("SPK physics-based mount model") | No | P2 |

### 2.8 Calibration frames
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Flat wizard**: auto exposure to a target ADU per filter, sky or panel flats | NINA Flat Wizard, Ekos auto-flats (SynLink supports flat panels as devices) | Manual flats in Autorun or Live | **P1** |
| **Dark library** with auto-matching | Ekos (guide darks), NINA | No | P2 |

### 2.9 Monitoring, remote access and sharing
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Push notifications and alerts** (sequence done, guiding lost, safety stop, roof) | NINA Ground Station (Pushover, etc.), Seestar message push | v3.0 status card, no alerting | **P1** |
| **Session analytics timeline** (captures, focus runs, guiding, flips on one timeline) | Ekos Analyze | No | P2 |
| **Saved remote connections** (named IP or VPN profiles) | User request | Must retype the IP | P1 (trivial) |
| **Cloud or remote control service** | ASIAIR v3.0 Telescope Network, Seestar remote sharing and guest mode, EkosLive | New in v3.0 | Baseline now |
| **Guest / read-only viewers** for outreach | Seestar guest mode | No | P2 |
| **Browser client** (no app install) | StellarMate Web, EkosLive | No | P2 |
| **Native desktop app on Windows as well as macOS** | SynLink (Android, iOS, macOS, Windows) | No Windows app (emulators only) | P2 |

### 2.10 Live stacking and processing
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Automatic gradient removal** in live stacks | StellarMate 2.2 | No | P2 |
| **AI denoise and enhance**, DBE | Seestar app (live and in gallery) | No | P2 (consumer appeal) |
| **No live-stack time cap** | User request (2 h limit reported) | Limited | P2 |
| **Video sequence capture** for EAA and planetary | Ekos 3.7.5 | Basic Video mode | P3 |
| **ADC (dispersion corrector) control** for planetary | ZWO ASIStudio has it. Users want it in ASIAIR. | No | P3 |

### 2.11 Extensibility, automation APIs and AI
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Plugin ecosystem** | NINA (about 90 listed plugins in 2026) | Closed | P2 |
| **Scripting / API** | Ekos (D-Bus), Pegasus Unity (server API), NINA Advanced API plugin | No public API (INDI server only) | P2 |
| **LLM / AI assistant integration (MCP server)** | StellarMate OS 2.3, Ekos "AI Assistant (MCP)" | No | P2 (emerging differentiator) |
| **Multi-client hub architecture** (server brokers devices to several apps) | Pegasus Unity Server | Single controller expected | P2 |

### 2.12 Software lifecycle and reliability
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Atomic system updates with one-click rollback** | StellarMate OS 2.3 (Arch-based, atomic updates, rollbacks) | Rolling back needs RESET FIRMWARE and sideloading tools (Functions.md §18) | **P1** — the Missing Manual devotes whole sections to this pain |
| **OTA updates decoupled from phone app store** | StellarMate | Firmware is bundled in the phone app, so an app auto-update forces a firmware change | **P1** |

### 2.13 Community and science
| Function | Who offers it | ASIAIR today | Priority |
|---|---|---|---|
| **Citizen-science campaigns** (occultations, exoplanet transits, comets) with predictions, reminders and data upload | Unistellar app (SETI Institute partnership) | No | P3 (strong niche, good fit for timing-accurate controllers) |
| **In-app community, tutorials, AI help** | Seestar app (community, AI assistant), ASIAIR v3 tutorials | Partial | P2 |
| **Simulation mode**: virtual mount, cameras and focuser to practice PA, guiding and sequences indoors | SynLink (built-in simulators for all devices) | No | **P1** — cheap to build, directly addresses the steep first-night learning curve the Missing Manual describes |

---

## 3. Recommended shortlist for a comparable app

Ranked by user value against implementation effort, giving extra weight to pain points the Missing Manual documents.

1. **Open device layer** (INDI/Alpaca), with a curated "works out of the box" list. This removes the main reason users leave ASIAIR.
2. **Safe, decoupled updates**: atomic OS updates with rollback, and firmware independent of the phone app version.
3. **Guiding Assistant + backlash compensation**: measure the mount, then recommend or apply settings automatically. Optionally add a self-tuning guider.
4. **Constraint-based scheduler** with an artificial horizon, Moon and twilight rules, multi-night goals and weather-safe pause/resume.
5. **Smart exposure advisor** (sky background plus sensor model gives a recommended gain and sub length).
6. **Flat wizard and flat-panel support**, plus manual-filter names in FITS headers.
7. **Smart power**: per-port current monitoring, overload warnings, automatic dew control from the dew point, and ports switchable inside sequences.
8. **Aberration / tilt inspector** with screw-turn advice.
9. **Notifications and session analytics** (push alerts, a night timeline, sub grading).
10. **Simulation mode** with virtual devices for training and testing (as in SynLink).
11. **Open API, with an MCP/AI-assistant endpoint.**

**Design principle from the research:** ZWO keeps advanced settings hidden to protect beginners, and that is the most common complaint from power users. A two-tier UI (simple by default, an "advanced" panel per module) keeps the ASIAIR's ease of use while closing most of these gaps. Sky-Watcher's SynLink has already shipped exactly this with its EASY and PRO modes, so it is now table stakes rather than a differentiator.

---

### Sources
- Sky-Watcher SynLink: https://www.skywatcherusa.com/products/synlink-universal-astroimaging-controller · https://www.astroshop.eu/controls/skywatcher-astrophotographie-controller-synlink/p,35050 · https://www.highpointscientific.com/sky-watcher-synlink-universal-astroimaging-controller · https://www.skypoint.it/en/sky-watcher-synlink-controller.html · https://agenaastro.com/sky-watcher-synlink-universal-astroimaging-controller-s30125.html · https://altairastro.com/sky-watcher-synlink-universal-astrophotography-controller-with-wi-fi-16906-p.asp · https://www.opticscentral.com.au/blog/sky-watcher-synlink-astrophotography-controller/ · https://www.diyphotography.net/?p=343614 · https://dc.watch.impress.co.jp/docs/news/2149048.html · https://www.techno-edge.net/release/prtimes2/20261023/25094.html
- StellarMate OS changelog (2.1–2.3): https://stellarmate.com/changelog/os
- StellarMate OS for Mini PC (release history): https://stellarmate.com/shop/sm-160-stellarmate-os-20-for-mini-pc-18373
- StellarMate Pro features (Astroshop): https://www.astroshop.eu/controls/ikarus-technologies-stellarmate-pro-8gb-256gb-nvme/p,99675
- StellarMate OS 2.2.0 news summary: https://scopetrader.com/search/chiefland-astrofest
- KStars/Ekos handbook: https://docs.kde.org/trunk5/en/kstars/kstars/ch05s02.html · https://kstars-docs.kde.org/ja/user_manual/ekos.html
- KStars Aberration Inspector (3.6.8): https://www.softpedia.com/progChangelog/KStars-Changelog-253392.html
- KStars 3.7.5/3.7.6 notes: https://knro.blogspot.com/2025/?m=0
- N.I.N.A.: https://nighttime-imaging.eu/
- NINA Target Scheduler plugin: https://dr.molodetz.nl/_proxy/https/tcpalmer.github.io/nina-scheduler/ · https://tcpalmer.github.io/nina-scheduler/target-management/profiles.html
- NINA unattended-operation guide (plugins, safety): https://astrotaca.github.io/guides/sleep-while-using-telescope-nina.html
- NINA Ground Station plugin: https://github.imc.re/daleghent/nina-ground-station
- PrimaLuceLab EAGLE6: https://www.skypoint.it/en/primalucelab-eagle6-computer-for-telescopes-and-astrophotography.html · https://scopetrader.com/primalucelab-eagle-6-lands/
- RB Focus Gaius-S2: https://astronomyplus.com/products/rb-focus-gaius-s2 · https://scopetrader.com/telescope-control-system-rb-focus-gaius-s2/amp/
- ToupTek StellaVita review: https://scopetrader.com/next-story/flat-frames-in-astrophotography/
- AStarBox: https://scopetrader.com/astarbox-controller-review/
- Pegasus Astro Unity Platform: https://pegasusastro.com/unity-platform · NYX-101: https://www.highpointscientific.com/pegasus-astro-nyx-101-harmonic-geared-mount
- SharpCap Smart Histogram: https://www.sharpcap.co.uk/sharpcap/features/smart-histogram · https://forums.sharpcap.co.uk/viewtopic.php?p=19299
- PHD2 Guiding Assistant / backlash: https://www.openphdguiding.org/PHD2_BestPractices_2019-12.pdf · https://forum.sequencegeneratorpro.com/t/phd2-question-backlash-compensation/3124
- Seestar app versions and features: https://marlvel.ai/apps/seestar/versions · https://apps.apple.com/us/app/apple-store/id6447429891 · https://scopetrader.com/using-the-seestar-app/
- Unistellar citizen science: https://science.unistellar.com/ · https://www.space.com/stargazing/skywatching-kit/help-defend-earth-from-asteroids-with-your-unistellar-telescope
- ASIAIR user feature requests (ZWO forum): https://bbs.zwoastro.com/d/16192/1 · https://bbs.zwoastro.com/d/22249-feature-request-for-asiair · https://bbs.zwoastro.com/d/17693/5 · https://bbs.zwoastro.com/d/21630-request-for-automated-dew-heater-control-integration-in-asiair · https://bbs.zwoastro.com/d/17249/1 · https://bbs.zwoastro.com/d/16675/8 · https://bbs.zwoastro.com/d/18766/2 · https://bbs.zwoastro.com/d/10826-asiair-manual-filter-option · https://bbs.zwoastro.com/d/18661/1 · https://bbs.zwoastro.com/d/26433/3 · https://bbs.zwoastro.com/d/13010/3
