# ASIAIR App — Telescope Control Functions

A functional summary of what the ZWO ASIAIR app does to control an astrophotography rig. It is based on *ZWO ASIAir: The Missing Manual* by Nicholas Loveday (v1.9, May 2026, written for app 2.3 and updated for 2.5), with recent feature notes from ZWO's release logs.

> The Missing Manual is an independent guide, not a ZWO publication. Exact menu names and defaults can change between app versions.

---

## 1. What the ASIAIR is

The ASIAIR is a small Wi‑Fi computer that sits on the telescope. It connects by USB to the mount, the cameras, the focuser, the filter wheel and the rotator, and it powers 12 V accessories. The phone/tablet app (iOS, Android, Apple‑silicon Mac) is the whole user interface. You use it to align, slew, focus, guide, run imaging sequences and manage files. The ASIAIR keeps running a sequence even when the app is disconnected.

**Core capability list:** preview, plate solving, GOTO with auto-centering, polar alignment, autoguiding (with multi-star guiding and dithering), autofocus, meridian flips, automated sequences (Autorun), multi-target and mosaic scheduling (Plan), live stacking, video capture, calibration frames, built-in Sky Atlas, 12 V power management, on-board storage and file access, and an INDI server for third-party software.

---

## 2. Hardware connection and power management

| Function | What the app does / notes |
|---|---|
| **USB device hub** | Two blue USB3 ports for high-bandwidth devices (main cameras, storage). Two black USB2 ports for the mount, EAF, EFW, CAA and small guide cameras. |
| **Daisy-chaining** | A filter wheel or CAA can plug into the camera's USB hub. The EAF and guide cameras (ASI120/220/174) are most reliable plugged straight into the ASIAIR. |
| **12 V power outputs** | Each output can be switched on and off in the app. Limits: under 3 A per port and under 6 A in total. Overloading causes random crashes. Large cooled cameras (ASI2600/6200, about 5 A) should have their own supply. |
| **Power monitoring** | Shows input voltage, current, power and temperature (Plus models). |
| **Anti-dew heaters** | Camera heaters can be toggled. They default to OFF and the setting is not kept between sessions. |
| **Base draw** | The ASIAIR alone draws about 0.3 A at 12 V. |

---

## 3. Networking and access

- **Hotspot mode:** The ASIAIR broadcasts its own SSID. Factory credentials are SSID password `12345678`, PIN `000000` and device lock code `000000` (lock added in 2.3). Change all three.
- **Station mode:** Joins your home Wi‑Fi or Ethernet for better range and speed. Ethernet is noticeably faster.
- **Remote access:** You can connect by IP, including through port forwarding (ports 139, 445, 4400, 4700, 4800).
- **Device Lock:** Stops another phone or tablet from taking over the rig.
- **Telescope Network (v3.0, July 2026):** Binds a device to an online service. Both the ASIAIR and the phone need internet access.
- **Single-controller rule:** Only one device should command the mount. A second controller can slew the mount without the ASIAIR knowing, which leads to bad flips and slews into the pier or ground.

---

## 4. Session setup

1. **Location and time:** These are set in the app. Since 2.5 the ASIAIR writes the location to the mount when it connects, so a wrong location breaks GOTO and polar alignment. Error patterns help diagnose this: a 15° error suggests the hour or DST is wrong, 30° the month, and 1° the day.
2. **ENTER DEVICE:** Connects to the ASIAIR. The app opens in Preview mode.
3. **Equipment configuration:** Turn on the main and guide cameras, set gain (start mid-slider), enable cooling, and enter an approximate focal length. Plate solving refines the focal length later.
4. **Shutdown:** Park the mount, then use the red SHUTDOWN slider under the ASIAIR icon.

---

## 5. Mount control

| Function | Description |
|---|---|
| **Sync to Mount** | Aligns the ASIAIR's model with the mount. Do it while the mount is parked (counterweight down). In the southern hemisphere, confirm that park shows Dec −90°. |
| **Tracking** | On/off, usually at sidereal rate. Tracking is off while parked and pauses before a meridian flip. |
| **Manual slew** | Directional pad with selectable slew rates. |
| **GOTO** | Slews to an object picked in the Sky Atlas, to typed RA/Dec coordinates (JNow or J2000), or to the field of a previously stored image. |
| **GOTO Auto Center** | After the slew, plate-solves and re-slews until the target is centered (accuracy about 5′). |
| **Sync (from solve)** | Plate-solves and syncs the mount to the true position, which works like a one-star alignment. |
| **Cancel** | Aborts a slew or a long plate solve. |
| **Park / Home** | Returns to park or home. Since 2.5, Park can be the end action for Autorun and Plan (ASIMount). |
| **ASIMount extras** | EQ/Alt-Az mode switch, guide speed, Heavy Duty Mode (AM3/AM5), and mount firmware updates. |
| **Backlash practice** | Approach the target from the east on repeated GOTOs, and keep the scope slightly east-heavy, to reduce RA backlash. |

**Interlock:** The app refuses to GOTO while the main camera is exposing.

### Meridian flip
- This is a global setting. You choose the minutes before the meridian when tracking pauses, the delay after the meridian before flipping, and whether to recalibrate the guider afterwards (ZWO recommends ON).
- **Automated sequence:** stop the exposure, stop tracking, flip, rotate 180° with the CAA if one is fitted, plate-solve and re-center, recalibrate the guider, optionally autofocus, then resume imaging.
- Autorun and Plan can flip mid-session. The manual advises watching the first few flips for cable snags.

---

## 6. Plate solving

- Identifies the exact sky position of any frame. GOTO centering, sync, polar alignment, framing and mosaics all depend on it.
- **Works best with:** a field of view between 0.4° and 33° (roughly up to 3000 mm focal length on APS-C and 4500 mm on full frame), and at least 20 stars, with 50–100 being reliable.
- **Common failures:** too few stars, bright nebulae or clusters filling the frame (M42, globulars), or a field under about 30′.
- **Fixes:** use a slightly longer exposure or more gain, or solve on a star field off to one side and then offset manually.
- A "new plate-solving routine" option exists for sparse star fields. The manual suggests leaving it OFF otherwise.

---

## 7. Polar alignment

- Uses the **main camera**, so no polar scope is needed. It works in both hemispheres.
- **Standard method:** Images the sky, rotates RA about 60°, images again, and computes the offset of the mount's axis from the pole. The pole must be within about 5° of the field.
- **All-Sky PA:** For sites where the pole is blocked (up to about 30° away). It rotates in 15° steps and moves about 30° east, so start west of the meridian. The manual's author finds the original method more accurate.
- **Live adjustment:** After START, adjust altitude and azimuth until the orange RA-axis circle lands on the green pole marker. Press REFRESH to re-shoot.
- **Suggested exposure:** about 10 s at medium gain for f/5–f/12. The ideal star count is 50–200.
- **To restart:** stop, change settings, return the mount to park, then start again.

---

## 8. Focusing

### Tools
- **HFD readout:** Half-flux diameter, shown in pixels and arcseconds in Preview, Autorun, Plan and the guider. Press DETECT in Preview to measure stars.
- **Manual focus:** Minimize the average HFD, ideally with a Bahtinov mask.
- **EAF control (Focus mode):** Move in and out with coarse and fine step buttons. The range is 0–60,000 steps, raised to 300,000 in a late-2025 update. The focuser beeps and stops at its limits.

### Autofocus (EAF)
- Racks through focus, samples HFD at each step, fits a V-curve or parabola, and marks best focus with a red dot.
- **Step sizes scale with focal ratio:** the defaults suit f/5. Try 20 (fine) and 100 (coarse) at f/10, or 30 and 150 at f/15. ±50% is fine.
- **Triggers:**
  - on a timer (for example every 30 min)
  - at the start of each Autorun
  - after a meridian flip (important for SCT and Cassegrain mirror shift)
  - on a temperature change
- **Temperature compensation:** Needs an external probe at the middle of the tube. The EAF's internal sensor measures its own electronics, not the air.
- **Filter offsets (2.5+):** After a filter change in Autorun or Plan, the EAF moves to a stored per-filter offset.
- **Failed curves** usually point to a slipping coupler or Crayford roller, the end of focuser travel, or poor seeing.

---

## 9. Autoguiding

The guider is built in and works much like PHD2. Logs are saved in PHD2 format.

| Function | Detail |
|---|---|
| **Guide hardware** | Guide scope, OAG, ONAG, or an integrated DUO camera. |
| **Guide speed** | 0.25×–1.0× sidereal. Start at 1.0× for guide focal lengths up to about 1000 mm. Very long focal lengths may need about 0.5×. |
| **Calibration** | Measures how the guide star moves with each pulse. Do it on the side of the meridian you will image. Redo it after a flip, after rotating the guider, or after changing the rig. OAG/DUO with a CAA does not need recalibration. The default step is 1000 ms (aim for about 25 px per axis). |
| **Auto-restore calibration** | Reloads the last calibration at startup. Turn it off for portable setups. |
| **Exposure (cycle time)** | Typically about 1 s (range 0.1–5 s). Strain-wave mounts often need 0.5–1 s. Above about 2–3 s the guider stops correcting mechanical errors. |
| **Max RA/Dec duration** | Longest correction pulse (default 1000 ms). |
| **Aggressiveness** | Per axis. Raise it until the mount oscillates, then back off 25–30%. |
| **Dec mode** | AUTO for most mounts. North/South only for backlash-prone trackers. |
| **Star selection** | Automatic, or tap a star. Target a peak of 100–200 ADU. |
| **Multi-star guiding** | Used automatically when several good stars are available. Allows shorter cycles. |
| **Binning** | Bin 1 or 2 for the guide camera on long guide scopes. |
| **Settle time** | How long guiding must stay stable before an exposure starts. |
| **Status** | Green GUIDING means stable. Red LOOPING means the star was lost. |

**Image scale rule of thumb:** the guide image scale should be no more than about 3× the main camera's.

### Dithering
Configured in the guider's Advanced Settings. It shifts the pointing slightly between exposures to reduce walking noise and to allow drizzle integration.

---

## 10. Sky Atlas and object library

- **Planetarium view:** A blue box marks the target and a red box shows the camera field. You can GOTO at a specific framing angle.
- **Catalogs:** Solar system, Messier, Caldwell, NGC/IC, LBN, planetary nebulae, named and double stars, and others. Comet GoTo accuracy improved in 2.3.
- **Tonight's Best:** Popular targets with rise and transit altitude graphs.
- **Favourites:** Heart icon.
- **Custom objects:** Your own name and RA/Dec, organized in groups. Since 2.5 you can edit name, type and coordinates.
- **Filters:** By time, altitude, azimuth and field of view.
- **Object details:** Double-tap for rise/set, magnitude and coordinates. Images and articles need internet.
- **Annotate:** Labels known objects on a captured frame.
- **Mosaic tool:** Launches from the atlas (see §13).

---

## 11. Operating modes

| Mode | Purpose |
|---|---|
| **Preview** | Single or continuous test exposures (start with Bin 4 at 2 s) for framing, star counts, focus checks and plate solving. |
| **Focus** | EAF control and autofocus. |
| **Live (Live Stacking)** | Stacks frames in real time for outreach, star parties and EAA. Also captures darks, flats and bias for calibration. |
| **Autorun** | Automated imaging sequence on the current target. |
| **Plan** | Scheduled multi-target, multi-night automation. |
| **Video** | Short planetary and lunar clips. |

The active mode is highlighted in green on the right side. Since v3.0, a status card on the home screen shows sequence progress and guiding without opening the shooting page.

---

## 12. Autorun (automated sequence)

- Build exposure groups with **+**. Each group sets frame type (light, dark, flat, bias), filter, exposure, gain, binning and count.
- Options include autofocus triggers, dithering, meridian flip (global), cooling and an **end action** (Park, Go Home, stop tracking, return the CAA to its start angle).
- Shows estimated total time, storage needed and time until the meridian flip.
- **Pause** holds the sequence (for a passing satellite or plane, for example). Paused sequences need **Reset** before re-running. **Clear sequences** empties the list.
- The same Autorun template can be reused on other targets.
- **Pre-start checklist:** target centered, guiding stable, focus confirmed.

---

## 13. Plan mode (multi-target scheduling) and mosaics

### Plan
- A chain of Autoruns for multiple targets. For each one it does GOTO, plate solve and center, guider calibration and start, optional autofocus, then the exposure groups, and moves to the next target at its scheduled time.
- Supports framing angles (with a CAA), meridian flips, cooling and autofocus, and ends with park, tracking off or shutdown.
- **Progress carries over between nights.**
- **Import:** paste CSV text (name, RA, Dec in JNow), for example from Telescopius. Targets can be edited in the Sky Atlas.

### Mosaics
1. Open the Mosaic tool from the Sky Atlas.
2. Choose a grid (1×2, 2×2, 3×3…), overlap (15–25% or more) and rotation, then drag it into position.
3. Save the mosaic to a Plan and set exposure, filters and count for each panel. With a CAA, panel angles can be optimized automatically, and pane auto-alignment can be switched on or off.
4. Enable all panels and run. Stitch afterwards in PixInsight or Astro Pixel Processor.

---

## 14. Accessory control

- **EFW (filter wheel):** Changes filters inside sequences and applies EAF filter offsets. Remember to lengthen exposures for narrowband or light-pollution filters (about 50% transmission means roughly 2× exposure).
- **CAA (Camera Angle Adjuster):** Rotates the camera to frame the target. It flips 180° automatically after a meridian flip, can return to its initial angle at the end of a sequence, and has a 180° range option. The guider stays calibrated through rotation. Zero it once against hardware home, and plate-solve to set the sky angle. Turn the CAA off if you don't want automatic rotation, and check cables before allowing 180° turns.
- **Smart cameras (ASI2600 Air, 585MC Air, DUO):** DUO fan and LED control, integrated guiding.

---

## 15. Video / planetary

- Adjust gain, exposure, white balance and ROI, then record short clips. Stack them later (for example in ASIStudio's ASIVideoStack). Shows meridian transit info.
- The ASIAIR is fine for casual planetary work but limited for serious high-frame-rate imaging (an ASI533 can produce about 9 GB/min). Use a laptop with a fast SSD for that.

---

## 16. File and storage management

- Saves FITS lights and calibration frames with JPG thumbnails to internal eMMC (Plus 256 GB), a micro-SD card or a USB drive. A USB drive may need a restart before it is recognized.
- **In-app File Manager:** View, save to phone, rename, delete, or GOTO the field of a stored image.
- **Transfer options:** Remove the SD card (fastest), USB-C to a Mac/PC (it mounts as a drive), Wi‑Fi or Ethernet SMB share (`smb://10.0.0.1`), or the micro-SD card directly.
- **Storage format:** Available in the app (2.3+).

---

## 17. Interoperability, maintenance and support

- **INDI server:** SkySafari, SharpCap and KStars can drive the rig through the ASIAIR (one mount controller at a time).
- **Firmware:** The app carries matching ASIAIR firmware and may install it when it connects, so app and firmware versions must match. Known-good builds cited are 2.3.3 / firmware 12.03 and 2.5. Rolling back is possible (iMazing on iOS, an older APK on Android) after **Reset Firmware**.
- **Report an Issue:** From the "i" page, with up to 3 screenshots and logs.
- **Tip:** Screenshot working settings after a good night.

---

## 18. Quick troubleshooting map

| Symptom | Likely cause |
|---|---|
| Freezes or crashes | Overloaded 12 V outputs or a bad USB cable. Power-cycle, reconnect, Sync to Mount, GOTO. |
| Plate solve or PA fails | Too few stars, noisy or overexposed frame, wrong focus, pole too far, or field too small. |
| Mount slews the wrong way or into the ground | Not synced while parked, or a second controller is active. |
| GOTO refused | Camera still exposing. |
| Tracking stopped | Parked, flip pending, or a bug. Re-enable tracking. |
| Guide star lost or oscillating | Star too dim, gain too high (hot pixels), wrong Dec mode, or aggression/pulse limits too high. |
| Dec drift | Dec mode set to North/South instead of Auto. |
| Elongated stars | Flexure between guide and main optics. Use an OAG or DUO. |
| CAA rotates unexpectedly | Auto-rotation after flip. Disable the CAA. |
| Camera or guider not detected | Bad USB3 cable or daisy-chaining. Connect directly. |

---

### Sources
- Nicholas Loveday, *ZWO ASIAir: The Missing Manual*, v1.9 (May 2026): https://images.clubexpress.com/951143/attach/4449174_0_ASIAir_Missing_Manual_1.9.pdf
- ZWO ASIAIR app release notes (2.3–2.5): https://bbs.zwoastro.com/d/20445/1 · https://marlvel.ai/apps/asiair/versions
- ZWO, ASIAIR v3.0 / Telescope Network guide (July 2026): https://www.zwoastro.com/2026/07/15/asiair-new-features-and-user-guide/2/
