# Galileo — User Acceptance Test Script (Generic: your target, your equipment)

| | |
|---|---|
| **Scenario** | A user sets Galileo up, then images **a target of their own choosing** with **their own equipment** through a full night: plan, connect, point, focus, guide, capture, review and process. |
| **Audience** | A tester who has not read the design documents. Follow the steps in order. |
| **Related** | [`UAT.md`](UAT.md) is the same workflow fixed to M13 and the INDI simulators. Screen overviews: the [wiki](https://github.com/gordtulloch/Galileo/wiki). Per-control detail: the in-app help (**F1**). Intent: [`SRS.md`](SRS.md). |

## How to use this script

1. **Complete Part A (Test profile) first.** It records your target and your equipment. Every later step refers to it: *"your target"* means the object in A2, *"your camera"* means the camera in A3, and so on.
2. Work through Sections 1–20 **in order**. Each depends on the ones before it.
3. Mark each step `P` (pass), `F` (fail), `B` (blocked by an earlier failure) or `N/A` (not applicable, with the reason).
   - A step that needs a device you marked **No** in A3 is `N/A` automatically. Don't count it as a failure.
   - Steps marked **(opt)** need an optional tool (ASTAP, PHD2, a notification channel); `N/A` if you don't use it.
4. For every `F`, record the step ID, what you saw, the log file and any crash report in `reports/crash` (see [Where Galileo keeps its files](https://github.com/gordtulloch/Galileo/wiki/01.-Getting-Started-Guide#where-galileo-keeps-its-files)).
5. A ⛔ step is a **blocker**: if it fails, later sections depend on it. Raise it and restart from that section.
6. **Safety first on real hardware.** Before any motion step (Sections 7, 9, 13) check the telescope's path, cables, dome slit and limits, and keep a hand on the power or the **Stop** button. Do not leave real equipment unattended during the first run of Sections 13 and 15.

---

## Part A — Test profile (fill in before starting)

### A1. Environment

| Item | Value |
|---|---|
| Galileo version / commit | |
| OS and version | |
| Install method (installer / source) | |
| Python (source installs) | |
| Tester / date | |
| Real equipment, simulators, or a mix? | |
| Observing site (name, latitude, longitude, timezone) | |
| Date and time of test (night you will observe, or the date you will plan for) | |

### A2. Choose your target

Pick **one** primary target. Use the checklist, then record the choice.

| Check | How to check it in Galileo | Pass if |
|---|---|---|
| **Above the horizon long enough** | Planning > What's Up Tonight (set **Observing date**), or Star Atlas / Targets tile altitude chart | Above **30°** (or your horizon limit) for **at least 2 hours** tonight, and clear of your horizon file |
| **Fits your optics** | Star Atlas with **Telescope FOV overlay**, or Framing Assistant | Roughly **20–80%** of your field of view for a single frame. If bigger, plan a **mosaic** (A2 *Mosaic?* = Yes) |
| **Bright enough** | Magnitude / surface brightness in the target tile | You can see it in a short test exposure of your own (bright globular and open clusters, bright galaxies and nebulae are easiest) |
| **Moon-friendly** | Schedule / Autoschedule respects Moon distance | Not within ~30° of a bright Moon, unless you are testing that |
| **Not at the zenith or meridian limit** | Mount page **Time to meridian** | Does not cross the meridian during a short test (unless you are testing the meridian flip, A2 *Test meridian flip?*) |

If you have no preference, a good first target is a bright, compact deep-sky object high in your sky tonight. Ask What's Up Tonight for one.

| Item | Your choice |
|---|---|
| **Target name** (as typed in catalog search) | |
| Catalog designations / aliases to try | |
| Type, magnitude, angular size | |
| RA / Dec (J2000) | |
| Transit time and altitude at transit | |
| Observing window used (start – end) | |
| Mosaic? (No / Yes — columns × rows, overlap %) | |
| Test meridian flip? (No / Yes) | |
| **Secondary target** (a second, different object for the Plate Solve, History and Library "other object" steps) | |
| **Wrong-place target** (an object below your horizon, for the slew-refusal step 7.2) | |

If your chosen object is not found in the catalog search (step 5.2), that is itself a result: record it, then pick another.

### A3. Your equipment

For each device, say whether you have it, how it connects, and what it is called. Steps for a device marked **No** are `N/A`.

| Device | Have it? | Protocol (INDI / Alpaca) | Server host : port | Device name as Scan shows it |
|---|---|---|---|---|
| **Camera (imaging)** — required | Yes | | | |
| **Mount** | Yes / No | | | |
| **Filter wheel** | Yes / No | | | |
| **Focuser** | Yes / No | | | |
| **Rotator** | Yes / No | | | |
| **Dome / roll-off roof** | Yes / No | | | |
| **Flat panel** | Yes / No | | | |
| **Weather station** | Yes / No | | | |
| **Safety monitor** | Yes / No | | | |
| **Switches / power box** | Yes / No | | | |
| **Guide camera** | Yes / No | | | |
| **Autoguider software** | PHD2 / none | | | |
| **Plate solver** | ASTAP / other / none | | | |
| **Notification channel** | Yes / No | | | |

| Optics (one tube is enough) | Value |
|---|---|
| Name | |
| Focal length (mm) / aperture (mm) | |
| Optical design | |
| Camera sensor (pixel size µm, width × height px, mono or one-shot-colour, Bayer pattern) | |
| Filters in the wheel (names, in slot order) | |
| Mount type (equatorial / alt-az) | |

| Test settings derived from your gear | Value |
|---|---|
| Expected pixel scale (arcsec/pixel) = 206.265 × pixel size (µm) ÷ focal length (mm) | |
| Test exposure for a quick check (s) — long enough to see stars, short enough not to saturate | |
| Session light exposure (s) and count per filter | |
| Dark exposure lengths needed (match your lights) | |
| Autofocus: step size, points, backlash, exposure | |
| Mount altitude limit / hour-angle limit | |
| Cooling target temperature (cooled cameras) | |

> **No hardware at all?** You can still run Sections 1–3, 5, 6, 15–16 and 18 (on frames you already have). Or serve INDI simulator drivers from one `indiserver` and treat them as your equipment. [`UAT.md`](UAT.md) gives the exact command.

---

## Section 1 — Installation and first launch

| ID | Action | Expected | Result |
|---|---|---|---|
| 1.1 ⛔ | Install Galileo using the method in the Getting Started Guide. | Installer completes without error. A shortcut or launcher exists. | |
| 1.2 ⛔ | Start Galileo. | A splash screen shows a progress bar and operations list, then the main window opens. No error dialog. | |
| 1.3 | Look at the sidebar. | Star Atlas, Planning, Imaging, Guiding, Focus, Solve, Library, Science, then Equipment and Options. Dashboard appears if more than one Pier exists. | |
| 1.4 | Click the theme button three times. | Cycles light → dark → red night-vision → light. Every theme stays readable; red mode has no white or blue areas. | |
| 1.5 | Click **Help**, then the **?** beside a screen title, then press **F1** in a control. | Help opens for the screen, then the control. Hovering shows a tooltip. | |
| 1.6 | Click **About**. | Version and licence shown. | |
| 1.7 | Confirm the database and today's log file exist. | `galileo.db` and the log file are in their folders. | |

## Section 2 — Observatory and Pier

| ID | Action | Expected | Result |
|---|---|---|---|
| 2.1 ⛔ | Top bar **Observatory** > **New Observatory…**. Enter the site from A1: name, latitude, longitude, timezone. **OK**. | Observatory created and selected. Latitude outside ±90, longitude outside ±180 or a blank name is rejected. | |
| 2.2 ⛔ | **Pier** > **New Pier…**, name it. | Pier created and selected. | |
| 2.3 | Rename the Pier with the pencil, then rename it back. | Name changes each time. | |
| 2.4 | Edit the Observatory (e.g. add an owner). | Saves. | |
| 2.5 | Restart Galileo. | Observatory and Pier are still there and selected. | |

## Section 3 — Options

| ID | Action | Expected | Result |
|---|---|---|---|
| 3.1 | **Options > Library**: set a **Repository** and an **Incoming** folder (empty folders you own). Save. | Accepted. A non-existent or unwritable path is rejected with a message. | |
| 3.2 | **Options > Star Atlas**: upload your horizon file, if you have one. | Accepted and saved per Observatory. | |
| 3.3 | **Options > Planning**: set a minimum altitude (use your A2 value) and the horizon-refusal option. | Saves. | |
| 3.4 | Open **Options > Imaging**, **Focus**, **Solve**, **Guiding**. Set the solver path if not auto-detected (opt). | Each page opens; changes persist after leaving and returning. | |
| 3.5 | **Options > Notifications**: configure your channel and press the test button (opt). | A test message arrives, or a clear error says why not. | |
| 3.6 | **Options > Plugins**. | List shows, including the VSTarget plugin. | |
| 3.7 | Restart Galileo; revisit 3.1 and 3.3. | All values survived. | |

## Section 4 — Equipment

Use the Pier from Section 2. Settings are saved per Pier. For each device use **your** protocol, server and port from A3.

| ID | Action | Expected | Result |
|---|---|---|---|
| 4.1 ⛔ | **Equipment > Camera.** Set **Driver**, **Server**, **Port** from A3. Click **Scan**. | Status bar reports devices found; log pane lists them; **Device** drop-down fills. | |
| 4.2 ⛔ | Pick **your camera**, click **Download Info**, set the Bayer pattern if one-shot colour, **Save**. | Pixel size and sensor size fill in and match A3. Save confirms. | |
| 4.3 | Click **Scan** with a wrong server address (then restore it). | Clear failure message; no hang or crash. | |
| 4.4 | Switch **Driver** between INDI and Alpaca, then back. | Port default follows the driver (INDI 7624, Alpaca 32323). Restore your own values. | |
| 4.5 ⛔ | Re-select the Pier. | Status bar: "Connected to primary camera '…'". | |
| 4.6 | **Cooled camera only:** set the cooling target from A3. | Temperature falls toward target; power reading is plausible. `N/A` otherwise. | |
| 4.7 | **Equipment > Mount**: Scan, pick, **Save**, **Connect**. | Status panel shows RA/Dec, Alt/Az, sidereal time, pier side, tracking, parked. | |
| 4.8 | Compare the mount's clock and site with your Observatory. | Time and latitude/longitude match (Galileo syncs them on connect). | |
| 4.9 | Set **Flip if HA >** and your altitude / hour-angle limits from A3. Save. | Persist. | |
| 4.10 | **Filter Wheel**: Scan, pick, Save, Connect. Choose each filter and press **Change**. | Wheel moves; current filter and names match A3. | |
| 4.11 | **Focuser**: Scan, pick, Save, Connect. Move a few steps. | Position updates; "moving" clears. | |
| 4.12 | **Rotator**, **Dome**, **Flat Panel**, **Switches**, **Weather / Safety**: connect each device you have. | Each page shows live state. Mark the others `N/A`. | |
| 4.13 | **Safety** page: read the banner. | SAFE or UNSAFE with reasons. | |
| 4.14 ⛔ | **Equipment > Optics**: **+**, enter the A3 name, focal length, aperture and design. **+** by **Associated** to attach your camera, filter wheel, focuser, rotator. **Save**. | Only saved devices are offered. The tube appears in the top-bar **Optics** selector with focal length and f-ratio. | |
| 4.15 | Restart Galileo. | Cameras and focusers reconnect automatically; other devices keep their saved settings. | |

## Section 5 — Find and choose your target

No hardware needed.

| ID | Action | Expected | Result |
|---|---|---|---|
| 5.1 | Open **Star Atlas**. | Sky renders for your location and time. Drag pans, scroll zooms. Horizon overlay shows if uploaded. | |
| 5.2 ⛔ | Search for **your target** by name, then by each alias from A2. | The view centres on it each time; name, type, magnitude and size shown. | |
| 5.3 | Enable **Telescope FOV overlay** and zoom to your target. | The rectangle for your Optics/Camera appears, plausibly sized (compare with A3). | |
| 5.4 | Select the target. | Top bar shows "Current object: *your target*" on every screen. | |
| 5.5 | **Planning > What's Up Tonight**: set **Observing date**, **Min altitude**, include your target's type, **Run**. | Ranked list (up to 50 tiles) with type, magnitude, altitude chart, rise/transit/set. Your target appears if it meets the criteria. | |
| 5.6 | Change **Observing date** to a date when your target is below the horizon, **Run** again. | Target is absent or ranked low. Restore the date. | |
| 5.7 | **Planning > Targets**: search by **Name/ID**, then by **Object type** and **Constellation** for your target. | Found each way. | |
| 5.8 | On its tile, click **Select**. | Current object set. | |
| 5.9 | Compare rise/transit/set with a trusted source (Stellarium or similar). | Agree within a few minutes. | |

## Section 6 — Frame the target

| ID | Action | Expected | Result |
|---|---|---|---|
| 6.1 | **Imaging > Framing…**. | Framing Assistant shows your FOV on a sky-survey image centred on the target (needs network). | |
| 6.2 | Set a rotation angle (e.g. 30°). | Rectangle rotates. | |
| 6.3 | Set a 2 × 2 mosaic with 20% overlap. | Grid draws. With a rotation still set, the **whole grid** is tilted about its centre, not just the panes. | |
| 6.4 | Clear the mosaic back to a single frame. | Single rectangle. | |
| 6.5 | **If A2 says Mosaic = Yes:** set your own grid and overlap, then **OK**. | Status bar reports the panes; they are used by Imaging capture and the session Image block. `N/A` if No. | |
| 6.6 | Click **Annotate**. | Stars and DSOs labelled. | |
| 6.7 | Close without changes. | No error. | |

## Section 7 — Point the telescope (needs a mount)

| ID | Action | Expected | Result |
|---|---|---|---|
| 7.1 ⛔ | With your target selected, slew from Star Atlas or What's Up Tonight → **Slew To**. | Mount slews; tracking starts; Mount page RA/Dec converge on the target. | |
| 7.2 | Try to slew to the **wrong-place target** from A2 (below your horizon limit). | Slew refused with a message; mount does not move. | |
| 7.3 | Press **Stop** during a slew. | Motion stops promptly. | |
| 7.4 | **Imaging > Mount Nudge:** nudge N, S, E, W at each rate. | Motion matches direction, rate and duration. | |
| 7.5 | **Equipment > Mount**: **Time to meridian**, **Pier side**. | Consistent with the target's position. | |
| 7.6 | **If A2 says Test meridian flip = Yes:** let the target cross the meridian past your **Flip if HA >** setting while tracking. | Mount flips, resumes tracking, and the target is re-centred. `N/A` if No. | |

## Section 8 — Test exposure and preview

| ID | Action | Expected | Result |
|---|---|---|---|
| 8.1 ⛔ | **Imaging:** Type **Light**, exposure = the A3 test exposure, Quantity 1, your filter, Bin 1. **Capture**. | Progress and countdown run; window stays responsive; frame appears auto-stretched. | |
| 8.2 | Read the statistics line. | Mean, median, min, max, star count, HFR populated. | |
| 8.3 | Pan, zoom, change **Stretch level**, toggle **Debayer** (colour cameras). | Preview responds; statistics and saved files are unaffected by Debayer. | |
| 8.4 | Check the histogram. | Matches the frame. | |
| 8.5 | Quantity 3, **Capture**, then **Stop** after the first frame. | Run stops after the exposure in progress; frames already taken remain. | |
| 8.6 | **Save Frame…**, accept the pre-filled name. | Name contains your target. File opens in a FITS viewer with correct headers. | |
| 8.7 | With **Auto-Save to Library** on, capture one frame. | It appears in **Library > Images** filed under your target. | |
| 8.8 | Untick Auto-Save, capture, re-tick. | No new Library entry for that frame. | |
| 8.9 | Tick **Live Stack**, capture 4 frames. | Stack appears after the third and improves. **Save Stack…** offers Library or File. | |
| 8.11 | Disconnect the camera and **Capture**. | "No camera connected"; no crash. Reconnect. | |
| 8.12 | **Filter wheel only:** change filter in the Filter drop-down and capture. | Wheel moves first; status bar confirms; capture waits. | |

## Section 9 — Plate solve and centre (opt, needs a mount and a solver)

| ID | Action | Expected | Result |
|---|---|---|---|
| 9.1 | **Solve**, *Solver Action* = **Nothing**, **Capture & Solve**. | RA/Dec, FOV, pixel scale, rotation, pointing error and solve time appear. Mount does not move. | |
| 9.2 | Compare pixel scale with A3. | Within a few percent. | |
| 9.3 | Set *Solver Action* = **Sync**, solve. | Sync reported; later solves show a small pointing error. | |
| 9.4 | Set **Slew to Target**, set **Accuracy**, solve. | Mount slews, re-solves, repeats until within Accuracy. | |
| 9.5 | **Load & Slew…** with an existing FITS file of your **secondary target**. | Solves; no motion unless the action says so. | |
| 9.6 | Back on **Imaging**, capture and **Annotate**. | Your target is labelled at or near centre. | |
| 9.7 | Solve a frame that cannot solve (very short exposure). | Clean failure message; mount does not move. | |

## Section 10 — Focus (needs a focuser)

| ID | Action | Expected | Result |
|---|---|---|---|
| 10.1 | **Focus:** set **Step size**, **Points**, **Backlash**, **Exp** from A3. | Accepted. | |
| 10.2 | On a star field (not a dense target core), click **Auto Focus**. | Frames taken at each point; star count, HFR, FWHM update; V-curve plots with its fit. | |
| 10.3 | Note the final position and HFR. | Focuser moves to the best position; HFR lower than at start. | |
| 10.4 | **Auto Focus**, then **Stop** midway. | Run ends; focuser returns to where it started. | |
| 10.5 | Move the focuser manually. | Position updates; HFR responds. | |
| 10.6 | **Filter wheel only:** measure a **Filter offset**. | Saves. | |

## Section 11 — Guiding (opt, needs PHD2)

| ID | Action | Expected | Result |
|---|---|---|---|
| 11.1 | Start PHD2, enter its host and port in **Guiding**, connect. | State Connected; guide-star image appears. | |
| 11.2 | **Connect Equipment**, then **Loop**. | PHD2 loops. | |
| 11.3 | **Auto Star**, then **Guide**. | Calibrates if needed, then Guiding; graph, drift plot and statistics update. | |
| 11.4 | **Dither**. | Visible step; guiding recovers. | |
| 11.5 | **Stop**. | Guiding stops. | |
| 11.6 | Quit PHD2 while connected. | Galileo reports it cleanly; no crash. | |

## Section 12 — Build your imaging session

| ID | Action | Expected | Result |
|---|---|---|---|
| 12.1 ⛔ | **Planning > Sessions.** From your target's tile click **Add to Session**. | A session starts with a **Slew To** block for your target. | |
| 12.2 | Add blocks in this order (skip any your gear cannot do): **Unpark Mount**, **Dome Open**, **Cool Camera**, **Autofocus**, **Plate Solve**, **Guide Start**, **FOR Filter** with an **Image** block indented inside, **Guide Stop**, **Warm Camera**, **Park Mount**, **Dome Close**, **Notification**. | Blocks appear in order; Image is indented under the loop. | |
| 12.3 | Right-click **Image**: set the exposure, count, frame type, gain/offset from A3. In the loop list your filters (or no loop for no filter wheel). | Saves. | |
| 12.4 | Move **Plate Solve** above **Slew To**. | Session flagged invalid (needs a preceding Slew To). Move it back. | |
| 12.5 | In the Slew To block type your target in **Name**. | Catalog search lists it; picking fills name, RA, Dec. | |
| 12.6 | Reorder, unindent and move a whole loop. | Works; the loop and its body move together. | |
| 12.7 | **Save as Template…**, then **Add Session from Template**. | A copy appears. Delete the copy. | |
| 12.8 | **If A2 says Mosaic = Yes:** give the Image block your mosaic via its Framing / Mosaic dialog. | Block shows the pane count; frame total multiplies accordingly. | |
| 12.9 | Check the session's total duration or frame count. | Matches your exposure × count × filters (plus overheads). | |

## Section 13 — Dry run and live run

| ID | Action | Expected | Result |
|---|---|---|---|
| 13.1 ⛔ | Disconnect the camera and click **Run**. | Galileo lists the missing equipment instead of starting. Reconnect. | |
| 13.2 ⛔ | With everything connected, click **Run**. | Card shows the block and frame in progress; blocks execute in order. | |
| 13.3 | **Pause**, wait, **Resume**. | Pauses after the current step, then continues. | |
| 13.4 | Open **Imaging** during the run. | Frames appear in the preview and the Library as they are taken. | |
| 13.5 | Open **Planning > History** while running. | The running session is listed; HFR, star count and guide RMS update. | |
| 13.6 | Cause a bad frame (briefly disconnect the camera or cap the telescope). | The frame is logged and skipped; the session continues. | |
| 13.7 | Cause a failed slew or solve (e.g. disconnect the mount mid-session). | Session ends, equipment left safe, log says why. | |
| 13.8 | **Stop** a running session. | Stops promptly with equipment safe. | |
| 13.9 | Run the full session to completion. | Shutdown blocks (warm, park, dome close) run; a **Notification** arrives. | |

## Section 14 — Safety (needs a weather or safety device, or a simulator)

| ID | Action | Expected | Result |
|---|---|---|---|
| 14.1 | While imaging, make conditions **unsafe** (change a threshold on the Safety page, or the device's own value). | Imaging stops; only shutdown blocks run; status reads UNSAFE with the reason. | |
| 14.2 | Restore safe conditions. | A scheduled session resumes by itself; a session started with Run does not. | |
| 14.3 | With UNSAFE showing, try to open the dome. | Refused with a reason. | |

## Section 15 — Schedule

| ID | Action | Expected | Result |
|---|---|---|---|
| 15.1 | In **Sessions**, click **Schedule** on your session. | It appears in **Planning > Schedule** in the Unscheduled area. | |
| 15.2 | Drag it onto tonight's column at a time inside your target's window (A2). | Snaps to 15 minutes. Columns are shaded by twilight; Moon phase shows. | |
| 15.3 | Right-click: **Edit…** priority/constraints/frames required; **Show Trajectory…**. | Saves. The altitude chart matches the Star Atlas. | |
| 15.4 | Remove it from the grid. | Returns to Unscheduled (not deleted). Delete from there with confirmation. | |
| 15.5 | Re-add and **Autoschedule**. | Preview offers a slot where the target is high, clear of horizon and Moon, in darkness. Confirm. | |
| 15.6 | Right-click empty space: **Add Pier Operation** (e.g. Park Scope after the session). | Appears in the grid. | |
| 15.7 | Confirm the scheduled session is locked. | Outlined in red; edits blocked until descheduled. | |
| 15.8 | Set the start a few minutes ahead and leave Galileo running. | It starts by itself; block goes yellow, then green (success) or red (errors). | |
| 15.9 | Click a completed block. | Its run log opens. | |

## Section 16 — Review the night

| ID | Action | Expected | Result |
|---|---|---|---|
| 16.1 | **Planning > History**, select the session. | Summary, an HFR/star-count chart by frame number, and a frame table. | |
| 16.2 | Read the trends. | A drop in star count matches any cloud or dew. | |
| 16.3 | **Export CSV…** | CSV with one row per frame opens in a spreadsheet. | |
| 16.4 | **Delete Session**; check the images remain in the Library. | History removed; images untouched. | |
| 16.5 | Restart Galileo; revisit History. | Remaining sessions persist. | |
| 16.6 | **Multiple Piers only:** open **Dashboard**. | One row per Pier with equipment, sequence and scheduler state; double-click opens that Pier. | |

## Section 17 — Calibration frames

| ID | Action | Expected | Result |
|---|---|---|---|
| 17.1 | **Imaging > Darks…**: enter your A3 dark lengths, cover the telescope, **Start**. | A dark per length, saved to the Library. | |
| 17.2 | **Flats…**: choose Sky Flats, Flat Panel or Observatory Panel (whichever you have); exposure **Calculate**; filter **All**. | A flat set per filter, saved to the Library. | |
| 17.3 | Capture **Bias** (Type = Bias, shortest exposure, Quantity 20). | Filed in the Library. | |
| 17.4 | Check **Options > Library > Calibration** thresholds and the Library for masters. | Master bias, dark and flat appear once enough frames exist. | |

## Section 18 — Library and processing

| ID | Action | Expected | Result |
|---|---|---|---|
| 18.1 | **Library > Images.** | Tree lists frames by object; your target shows the session's frames. **Search** finds it. | |
| 18.2 | Change **Sort by**; set **Show** to Light, then Calibration frames. | View updates each time. | |
| 18.3 | Put FITS files from another night or target in Incoming and click **Load New**. | Catalogued, moved to the Repository and renamed from their metadata. | |
| 18.4 | Delete a frame; tick **Show Deleted**. | Disappears, reappears with Show Deleted; file remains on disk. | |
| 18.5 | **Library > Sessions**, select your night. | Lights listed with matching calibration. | |
| 18.6 | Right-click the session: **Calibrate**. | Lights calibrated with the matching masters; output files appear. | |
| 18.7 | **Stack** (or **Stack (photometric)**). | A stack is produced and opens in your viewer; your target is visible. | |
| 18.8 | **Regenerate Thumbnail**. | Session picture updates. | |
| 18.9 | **Check out** to a folder. | Files linked or copied for PixInsight/Siril. | |
| 18.10 | **Dedup**, **Mappings**, **Merge Objects**: merge a duplicate object name into the right one. | Each page opens; merge combines the entries. | |
| 18.11 | **Cloud**: **Analyze**, then **Sync** (opt). | Cloud matched to the local catalog; sync follows the profile. | |
| 18.12 | **Regenerate** the catalog from the Repository. | Rebuilt from FITS headers with no loss. | |

## Section 19 — Shut down for the night

| ID | Action | Expected | Result |
|---|---|---|---|
| 19.1 | **Equipment > Mount**: **Park**. | Mount parks; Parked is true. | |
| 19.2 | Warm the camera (cooled cameras), or confirm the session did. | Cooler ramps to ambient. | |
| 19.3 | Close the dome or roof. | Shutter reads closed. | |
| 19.4 | Close Galileo while idle. | Exits cleanly; no crash report. | |
| 19.5 | Start Galileo again. | Observatory, Pier, equipment, optics, Options, sessions, templates and History are intact; your frames are still in the Library. | |

## Section 20 — Robustness and usability

| ID | Action | Expected | Result |
|---|---|---|---|
| 20.1 | Stop and restart your device server (or unplug the network) while idle. | Lost device reported in log and status bar; Galileo stays responsive; reconnect works. | |
| 20.2 | Resize the window small. | Controls reachable; no clipped dialogs. | |
| 20.3 | Hover random controls on each screen. | Each has a tooltip or help entry. | |
| 20.4 | Click any control greyed out with "Not implemented yet". | Tooltip says so; nothing else happens. | |
| 20.5 | Review the log after the run. | No unexpected tracebacks; every `ERROR` is explained by your deliberate fault injection. | |
| 20.6 | Check `reports/crash`. | Nothing from this run apart from deliberate crashes. | |

---

## Sign-off

| Outcome | Rule |
|---|---|
| **Accepted** | No ⛔ step failed; no more than 5% of the steps that applied to your equipment failed; every failure has a ticket. |
| **Accepted with conditions** | No ⛔ step failed, but failures in Sections 7–15 (the live imaging path) need a fix before release. |
| **Rejected** | A ⛔ step failed, or the app crashed in the live imaging path. |

| | |
|---|---|
| Steps run / passed / failed / N/A | |
| Failures raised (ticket links) | |
| Equipment and target actually used (summary of Part A) | |
| Decision | |
| Tester signature and date | |
