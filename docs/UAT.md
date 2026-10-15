# Galileo — User Acceptance Test Script: Imaging M13 End to End

| | |
|---|---|
| **Scenario** | A user sets Galileo up from scratch and images the Hercules Globular Cluster (**M13**, NGC 6205) through a full night: plan, connect, point, focus, guide, capture, review, and process. |
| **Audience** | A tester who has not read the design documents. Follow the steps in order. |
| **Related** | Overview of each screen: the [wiki](https://github.com/gordtulloch/Galileo/wiki). Per-control detail: the in-app help (**F1**). Intent: [`SRS.md`](SRS.md). Automated tests: `tests/`. |

## How to use this script

1. Work through the sections **in order**. Each section depends on the ones before it (you cannot capture before a camera is saved, or review a session that never ran).
2. For each step, do the **Action**, compare what happens with **Expected**, and mark the **Result** column `P` (pass), `F` (fail), `B` (blocked by an earlier failure) or `N/A` (not applicable to this rig, with the reason).
3. For every `F`, record the step ID, what you saw, and attach the log file (see [Where Galileo keeps its files](https://github.com/gordtulloch/Galileo/wiki/01.-Getting-Started-Guide#where-galileo-keeps-its-files)) and any crash report from `reports/crash`.
4. A **blocker** failure (marked ⛔) stops the run: later sections depend on it. Raise it, fix it, and restart from that section.
5. Steps marked **(SIM)** need the INDI simulators from the equipment setup below. Steps marked **(opt)** need an optional external tool (ASTAP, PHD2, a notification channel) — mark `N/A` if it is not installed.

### Test environment

Record this before starting.

| Item | Value |
|---|---|
| Galileo version / commit | |
| OS and version | |
| Install method (installer / source) | |
| Python (source installs) | |
| Device protocol | INDI (all devices on one `indiserver`, see [Equipment setup](#equipment-setup-indi-simulators)) |
| INDI version and host running `indiserver` | |
| Simulator drivers actually loaded | |
| ASTAP + star database installed? | |
| PHD2 installed? | |
| Tester / date | |

### Why M13, and what it needs

| Property | Value |
|---|---|
| Position (J2000) | RA 16h 41m 41s, Dec +36° 27′ 37″ |
| Type / magnitude / size | Globular cluster, mag ≈ 5.8, ≈ 20′ across |
| Best season | Northern-hemisphere summer. It transits high (≈ +88° altitude at latitude 52° N) around local midnight in June. |
| Visible from | Roughly latitude −60° to +90°. It never gets usefully high for southern observers in the far south. |

**Choose a site and date where M13 is above 30° for at least two hours.** If you are testing out of season, set the **Observing date** in Planning to a June–August night and use a Latitude in the northern hemisphere in step 2.1. Where a step says "tonight" it means the observing date you chose.

### Equipment setup: INDI simulators

All devices in this script are the **INDI simulator drivers** served by one `indiserver`, so no real hardware is needed. **(SIM)** in a step means "needs the simulators running".

Start the server on the test machine (or any machine Galileo can reach; see [Installing INDI](https://github.com/gordtulloch/Galileo/wiki/02.-Installing-INDI)):

```bash
indiserver -v indi_simulator_telescope indi_simulator_ccd indi_simulator_guide \
           indi_simulator_wheel indi_simulator_focus indi_simulator_rotator \
           indi_simulator_dome indi_simulator_gps indi_simulator_weather \
           indi_simulator_dsp
```

Notes:

- Run `ls /usr/bin/indi_simulator_*` (or your platform's equivalent) and load **every** simulator that exists. Drop any name above your install does not have, and record what was loaded in the environment table. Steps for a device with no simulator are `N/A`.
- INDI has separate **CCD Simulator** (the imaging camera) and **Guide Simulator** (the guide camera) drivers, so each is started once. Use the CCD Simulator as the camera in step 4.2.
- Default **Server** is `localhost`, **Port** `7624`. If `indiserver` runs elsewhere, use its host name or IP address.
- The CCD simulator draws a synthetic star field centred on wherever the simulated telescope points, so **Auto Focus** (Section 10), **Capture & Solve** (Section 9) and **Guiding** (Section 11) have stars to work with. If your INDI install lacks the star catalogue for the simulator, frames are blank: record that and mark the star-dependent steps `N/A`, or `B` (blocked) if you cannot proceed.
- Solving needs ASTAP plus a star database. The simulator's star field is not a real image of M13, so a *blind* solve may fail; the solver action steps are written to tolerate that (see Section 9).
- PHD2 (Section 11) can use the same INDI server for its own camera and mount (profile with INDI Camera = Guide Simulator, Mount = Telescope Simulator).

The Star Atlas, Planning, Framing, Schedule, History and Library sections work with no devices connected.

---

## Section 1 — Installation and first launch

| ID | Action | Expected | Result |
|---|---|---|---|
| 1.1 ⛔ | Install Galileo using the method in the Getting Started Guide. | Installer completes without error. A shortcut or launcher exists. | |
| 1.2 ⛔ | Start Galileo. | A splash screen shows a progress bar and a list of operations (database, plugins, each screen). The main window opens maximised. No error dialog. | |
| 1.3 | Look at the sidebar. | Icons for Star Atlas, Planning, Imaging, Guiding, Focus, Solve, Library, Science, then Equipment and Options at the bottom. Dashboard is present if more than one Pier exists. | |
| 1.4 | Click the theme button at the bottom of the sidebar three times. | Cycles light → dark → red night-vision → light. All text stays readable in each theme; red mode shows no white or blue areas. | |
| 1.5 | Click the **Help** button, then the **?** beside a screen title, then press **F1** with the cursor in a control. | Help opens for the screen, then for the control. Hovering a control shows a tooltip. | |
| 1.6 | Click **About**. | The About box shows the version and licence. | |
| 1.7 | Confirm the database was created (see Getting Started for the path). | `galileo.db` exists. Log file for this run exists in the logs folder. | |

## Section 2 — Observatory and Pier

| ID | Action | Expected | Result |
|---|---|---|---|
| 2.1 ⛔ | In the top bar open **Observatory** and choose **New Observatory…**. Enter a name, your real **Latitude/Longitude**, an IANA **Timezone** (e.g. `America/Toronto`), then **OK**. | Observatory is created and selected. Out-of-range latitude (e.g. 95) or longitude is rejected with a message. A blank name is rejected. | |
| 2.2 ⛔ | Open **Pier** and choose **New Pier…**, name it "Pier 1". | Pier is created and selected. Status bar shows no error. | |
| 2.3 | Click the pencil beside Pier, rename it to "Main", then rename it back. | Name changes in the selector each time. | |
| 2.4 | Click the pencil beside Observatory and correct a value (e.g. change owner). | Change saves. | |
| 2.5 | Restart Galileo. | Observatory and Pier are still present and selected. | |

## Section 3 — Options (before you need them)

| ID | Action | Expected | Result |
|---|---|---|---|
| 3.1 | Open **Options > Library**. Set the **Repository** folder (new empty folder) and **Incoming** folder. Save. | Folders are accepted. A non-existent or unwritable path is rejected with a clear message. | |
| 3.2 | Open **Options > Star Atlas**. Upload a horizon file (`.hrz` or text altitude/azimuth profile), if you have one. | Horizon is accepted and saved per Observatory. | |
| 3.3 | Open **Options > Planning**. Set a minimum altitude (e.g. 30°) and tick the option that refuses slews into the horizon, if present. | Settings save. | |
| 3.4 | Open **Options > Imaging**, **Focus**, **Solve** and **Guiding**. Review defaults; set the ASTAP path on **Solve** if it is not auto-detected (opt). | Pages open without error and settings persist after leaving and returning. | |
| 3.5 | Open **Options > Notifications**. Configure one channel and use the test button (opt). | A test message arrives, or a clear error explains why not. | |
| 3.6 | Open **Options > Plugins**. | Plugin list shows, including the first-party VSTarget plugin. Nothing errors. | |
| 3.7 | Restart Galileo and revisit step 3.1 and 3.3. | All Options values survived the restart (they live in the database). | |

## Section 4 — Equipment (SIM)

Do these with the Pier from Section 2 selected. Settings are saved per Pier. Use **Driver = INDI**, **Server** and **Port** as in the equipment setup for every device.

| ID | Action | Expected | Result |
|---|---|---|---|
| 4.1 ⛔ | **Equipment > Camera.** Set **Driver** = INDI, **Server** = `localhost`, **Port** = `7624`. Click **Scan**. | Status bar reports how many devices were found. The log pane lists them and the **Device** drop-down fills. Switching Driver to Alpaca changes the Port default to 32323 and back to INDI restores 7624; switch back to INDI before continuing. | |
| 4.2 ⛔ | Pick **CCD Simulator** as the camera, click **Download Info**, set **Bayer pattern** if one-shot colour, then **Save**. | Pixel size and sensor size fill in. Save confirms. | |
| 4.3 | Click **Scan** with a wrong server address. | A clear failure message appears in the status bar and log. Galileo does not hang or crash. | |
| 4.4 ⛔ | Re-select the Pier (switch away and back). | Status bar shows "Connected to primary camera '…'". | |
| 4.5 | **Equipment > Mount.** Scan, pick **Telescope Simulator**, **Save**, **Connect**. | Status panel shows RA/Dec, Alt/Az, sidereal time, pier side, tracking and parked state. | |
| 4.6 | Check the mount's clock and site. | Mount date/time and latitude/longitude match your Observatory (Galileo syncs these on connect). | |
| 4.7 | On the Mount page set **Flip if HA >** and altitude limits appropriate for M13 (e.g. minimum altitude 20°). Save. | Settings persist. | |
| 4.8 | **Equipment > Filter Wheel.** Scan, pick **Filter Simulator**, Save, Connect. Choose a filter and press **Change**. | Wheel moves and the current filter updates. Filter names are listed. | |
| 4.9 | **Equipment > Focuser.** Scan, pick **Focuser Simulator**, Save, Connect. Enter a position and press **Move**. | Position updates and "moving" clears. | |
| 4.10 | Connect the **Rotator Simulator**, **Dome Simulator** and **Weather Simulator** on their pages (Rotator, Dome, Safety). Flat Panel and Switches have no standard simulator: `N/A` unless you loaded one. | Each page follows the same Driver/Server/Port/Scan/Save pattern and shows live state. | |
| 4.11 | **Equipment > Safety**: with the Weather Simulator saved, check the banner. | Banner reads SAFE or UNSAFE and shows reasons. | |
| 4.12 ⛔ | **Equipment > Optics.** Click **+**, enter a Name, **Focal length**, **Aperture**, **Optical design**. Click **+** beside **Associated** and attach camera, filter wheel and focuser. **Save**. | Only devices saved in 4.2–4.9 are offered. Tube appears in the top-bar **Optics** selector, with focal length and f-ratio. | |
| 4.13 | Restart Galileo. | Devices reconnect automatically (camera, focuser; the INDI server must still be running) and manually-connected devices keep their saved settings. | |

## Section 5 — Find and choose M13

This section works without any hardware.

| ID | Action | Expected | Result |
|---|---|---|---|
| 5.1 | Open **Star Atlas**. | Sky renders for your location and time. Drag pans, scroll zooms. Horizon overlay shows (if uploaded). | |
| 5.2 | Search for **M13**. | The view centres on M13. Name, type, magnitude and size are shown. Aliases (NGC 6205, Hercules Cluster) also find it. | |
| 5.3 | Turn on **Telescope FOV overlay** in Options and zoom in on M13. | The rectangle for your Optics and Camera appears and is plausibly sized (a 400 mm scope with a small sensor frames M13 with room to spare). | |
| 5.4 | Select M13 as the target. | Top bar shows "Current object: M 13" on every screen you visit. | |
| 5.5 | Open **Planning > What's Up Tonight**. Set **Observing date** (a summer night), **Min altitude**, and include globular clusters. Click **Run**. | A ranked list of up to 50 tiles. M13 appears for a summer date. Each tile shows type, magnitude, a mini altitude chart and rise/transit/set times. | |
| 5.6 | Change the **Observing date** to a winter date and **Run** again. | M13 is absent or ranked low (it is below the horizon or short-lived). | |
| 5.7 | Open **Planning > Targets**. Search **Name/ID** = `M13`, then try **Object type** = globular cluster and a **Constellation** of `Her`. | M13 is found each way. Results are capped at 200. | |
| 5.8 | On M13's tile, click **Select**. | "Current object: M 13" is set. | |
| 5.9 | Compare the rise/transit/set for M13 with a trusted source (e.g. Stellarium). | Times agree within a few minutes. | |

## Section 6 — Frame the target

| ID | Action | Expected | Result |
|---|---|---|---|
| 6.1 | Open **Imaging** and click **Framing…**. | The Framing Assistant opens with your camera and telescope field of view drawn on a sky survey image centred on M13 (needs network). | |
| 6.2 | Set a rotation angle. | The rectangle rotates. | |
| 6.3 | Set a mosaic of 2 columns × 1 row with 20% overlap, then clear it back to a single panel. | Grid draws and clears. | |
| 6.4 | Click **Annotate**. | Stars and deep-sky objects are labelled. | |
| 6.5 | Close without changes. | Dialog closes; no error. | |

## Section 7 — Point the telescope at M13 (SIM)

| ID | Action | Expected | Result |
|---|---|---|---|
| 7.1 ⛔ | In **Star Atlas**, with M13 selected, use the slew action. Alternatively use **Planning > What's Up Tonight** → **Slew To**. | Mount slews, then tracking starts. Mount page RA/Dec converge on M13's coordinates. | |
| 7.2 | Try to slew to a point below your horizon limit (e.g. an object at −10° altitude). | The slew is refused with a message; the mount does not move. | |
| 7.3 | Press **Stop** during a slew to M13. | The mount stops promptly. | |
| 7.4 | **Imaging > Mount Nudge:** nudge N, S, E, W at each rate. | The mount moves in the matching direction for the chosen duration. | |
| 7.5 | **Equipment > Mount**: check **Time to meridian** and **Pier side**. | Values are consistent with M13's position relative to the meridian. | |

## Section 8 — Test exposure and preview (SIM)

| ID | Action | Expected | Result |
|---|---|---|---|
| 8.1 ⛔ | **Imaging:** Type **Light**, Exposure 5 s, Quantity 1, Filter L (or none), Bin 1. Click **Capture**. | Progress bar and countdown run. The window stays responsive. The frame appears auto-stretched. | |
| 8.2 | Read the statistics line. | Mean, median, min, max, star count and HFR are populated. | |
| 8.3 | Pan and zoom the preview; change the **Stretch level**; toggle **Debayer** (colour cameras). | Preview responds; stats and saved files are unaffected by Debayer. | |
| 8.4 | Check the histogram. | Histogram matches the frame. | |
| 8.5 | Set Quantity 3 and **Capture**; press **Stop** after the first. | The run stops after the exposure in progress completes. Frames taken so far remain. | |
| 8.6 | Click **Save Frame…**, accept the pre-filled name. | Name contains the current object (`M_13_…fits`). File opens in an external FITS viewer. FITS header carries object and exposure. | |
| 8.7 | With **Auto-Save to Library** ticked, capture one frame. | Frame appears under **Library > Images** (after a refresh) filed under M13. | |
| 8.8 | Untick **Auto-Save to Library**, capture, re-tick. | No new Library entry for the untick capture. | |
| 8.9 | Tick **Live Stack**, capture 4 frames. | After the third frame a stack appears and improves. **Save Stack…** offers *Save to Library* and *Save to File…*. | |
| 8.10 | Open **View > Panels…** and hide the Log panel; click **Reset Layout**. | Panel hides and returns. | |
| 8.11 | Capture with no camera connected (disconnect it first). | Message "No camera connected". No crash. | |

## Section 9 — Plate solve and centre on M13 (opt)

| ID | Action | Expected | Result |
|---|---|---|---|
| 9.1 | Open **Solve**, set *Solver Action* to **Nothing**, and click **Capture & Solve**. | Exposure is taken, then a solution shows RA/Dec, field of view, pixel scale, rotation, pointing error and solve time. Mount does not move. | |
| 9.2 | Check pixel scale. | Within a few percent of the expected scale for your optics. | |
| 9.3 | Set *Solver Action* to **Sync** and solve. | Mount reports a sync; later solves show a small pointing error. | |
| 9.4 | If 9.1 solved: set *Solver Action* to **Slew to Target** (M13 is the current object), set **Accuracy**, and solve. | The mount slews, re-solves and repeats until M13 is within Accuracy. Final pointing error is below Accuracy. | |
| 9.5 | Use **Load & Slew…** on an existing FITS file of a different object. | File solves; no mount motion unless the action says so. | |
| 9.6 | Return to **Imaging**, take a frame and click **Annotate**. | M13 is labelled at the frame centre. | |
| 9.7 | Run a solve that cannot succeed (e.g. very short exposure). | Solve fails gracefully with a clear message, and the mount does not move. | |
| 9.8 | If the simulator frames never solve, record that and mark 9.2–9.6 `N/A`. | The failure is clean (message, no hang) each time. | |

## Section 10 — Focus (SIM)

| ID | Action | Expected | Result |
|---|---|---|---|
| 10.1 | Open **Focus**. Set **Step size**, **Points**, **Backlash**, **Exp** for your scope. | Values accepted. | |
| 10.2 | On a bright star field near M13 (not on the cluster core), click **Auto Focus**. | Frames are taken at each point, star count, HFR and FWHM update, and the V-curve plots with its fit. | |
| 10.3 | Note the final focuser position and HFR. | Focuser moves to the best position; HFR is lower than at the start. | |
| 10.4 | Click **Auto Focus**, then **Stop** midway. | Run ends and the focuser returns to where it started. | |
| 10.5 | In the manual focuser controls, move in and out by a few steps. | Position updates; HFR reading responds. | |
| 10.6 | If you have a filter wheel, measure a **Filter offset** for one filter. | Offset saves. | |

## Section 11 — Guiding (SIM, opt)

| ID | Action | Expected | Result |
|---|---|---|---|
| 11.1 | Start PHD2 and, in **Guiding**, enter its host and port, then connect. | State shows Connected. Guide-star image appears. | |
| 11.2 | Click **Connect Equipment** (PHD2 side), then **Loop**. | PHD2 begins looping. | |
| 11.3 | Click **Auto Star**, then **Guide**. | PHD2 calibrates (if needed), then State shows Guiding. Guide graph, drift plot and statistics (RMS RA/Dec, total RMS, SNR) update. | |
| 11.4 | Click **Dither**. | A visible step appears in the graph and guiding recovers. | |
| 11.5 | Click **Stop**. | Guiding stops. | |
| 11.6 | Quit PHD2 while connected. | Galileo reports the loss cleanly and does not crash. | |

## Section 12 — Build the M13 imaging session

| ID | Action | Expected | Result |
|---|---|---|---|
| 12.1 ⛔ | Open **Planning > Sessions**. From M13's tile in What's Up Tonight or Targets click **Add to Session**. | A session is created and starts with a **Slew To** block for M13. | |
| 12.2 | Drag blocks from the palette in this order: **Cool Camera**, **Autofocus**, **Plate Solve**, **Guide Start**, **FOR Filter**, then **Image** inside it, then **Guide Stop**, **Warm Camera**, **Park Mount**, **Notification**. | Blocks appear in order; the Image block is indented under FOR Filter. | |
| 12.3 | Right-click the **Image** block and set Exposure 120 s, Count 10, Frame type Light, Gain/Offset as appropriate. | Settings save. The FOR Filter loop lists the filters you want (e.g. L, R, G, B). | |
| 12.4 | Move **Plate Solve** above **Slew To**. | The session is flagged invalid because Plate Solve needs a preceding Slew To. Move it back. | |
| 12.5 | Open the Slew To block's **Name** field and type `M13`. | The catalog search lists M13; picking it fills name, RA and Dec. | |
| 12.6 | Drag blocks to reorder; drag a block to unindent it; drag the loop and its body together. | Reorder works; the loop and its body move as one. | |
| 12.7 | **Save as Template…**, name it "Globular LRGB", then **Add Session from Template** and choose it. | A second session appears with the same blocks. Delete the second session. | |
| 12.8 | Estimate: check the session's total duration or frame count. | Matches 4 filters × 10 × 120 s plus overheads. | |

## Section 13 — Dry run and live run (SIM)

| ID | Action | Expected | Result |
|---|---|---|---|
| 13.1 ⛔ | Disconnect the camera and click **Run** on the session. | Galileo lists the missing equipment instead of starting. Reconnect afterwards. | |
| 13.2 ⛔ | With everything connected, click **Run**. | The card shows the block and frame in progress. Slew, cool, autofocus, solve, guide start and imaging execute in order. | |
| 13.3 | Click **Pause**, wait, then **Resume**. | The session pauses after the current step, then continues. | |
| 13.4 | Watch the first frames. Open **Imaging** during the run. | Frames appear in the preview and in the Library as they are taken. The run is not disturbed by changing screens. | |
| 13.5 | Open **Planning > History** while running. | The running session is listed; HFR, star count and guide RMS update every few seconds. | |
| 13.6 | Introduce a bad frame (stop `indiserver` or disconnect the camera for one exposure, then restore it). | The bad frame is logged and skipped; the session continues. | |
| 13.7 | Trigger a failed slew or solve (e.g. disconnect the Telescope Simulator mid-session). | The session ends, the equipment is left safe, and the log explains why. | |
| 13.8 | Click **Stop** on a running session. | The session stops promptly with equipment in a safe state. | |
| 13.9 | Run the full session to completion. | Warm camera, park, and notification all execute. A **Notification** arrives on the channel from step 3.5. | |

## Section 14 — Safety (SIM)

| ID | Action | Expected | Result |
|---|---|---|---|
| 14.1 | While a session is imaging, make the Weather Simulator report unsafe (change a weather property in its INDI control panel, or lower a threshold on the Safety page). | Imaging stops. Only shutdown blocks (park, dome close, guide stop, warm) run. Status reads UNSAFE with reason. | |
| 14.2 | Restore the safe state. | A scheduled session resumes by itself. A session started with Run does not auto-resume. | |
| 14.3 | With the Safety page UNSAFE, try to open the dome. | Refused with a reason. | |

## Section 15 — Schedule a multi-night plan

| ID | Action | Expected | Result |
|---|---|---|---|
| 15.1 | Return to **Planning > Sessions**, click **Schedule** on the M13 session. | It appears in **Planning > Schedule** in the Unscheduled area. | |
| 15.2 | Drag it onto tonight's column at a start time inside darkness. | It snaps to a 15-minute grid. Columns are shaded by twilight depth, the Moon phase icon shows. | |
| 15.3 | Right-click the block: **Edit…** priority, constraints and frames required; then **Show Trajectory…**. | Editing saves. The altitude chart for M13 matches the Star Atlas. | |
| 15.4 | Remove the block from the grid. | It returns to the Unscheduled area (not deleted). Delete it from there with confirmation. | |
| 15.5 | Re-add it and click **Autoschedule**. | A preview offers a slot where M13 is high, clear of the horizon and Moon, and in darkness. Confirm it. | |
| 15.6 | Right-click empty space and add a **Pier Operation** (Open Dome before and Park Scope after). | The operations appear in the grid. | |
| 15.7 | Confirm the session is locked once scheduled. | Outlined in red; edits are blocked until descheduled. | |
| 15.8 | Set the start time a few minutes ahead and leave Galileo running. | The session starts by itself at the time. The block turns yellow, then green on success or red on errors. | |
| 15.9 | Click a completed block. | Its run log opens. | |

## Section 16 — Review the night

| ID | Action | Expected | Result |
|---|---|---|---|
| 16.1 | Open **Planning > History** and select the M13 session. | Summary, an HFR/star-count chart against frame number, and a table of frames show. | |
| 16.2 | Spot the trend in HFR and star count. | A drop in star count matches any cloud or dew you saw. | |
| 16.3 | **Export CSV…** | A CSV file with one row per frame opens in a spreadsheet. | |
| 16.4 | **Delete Session**, then confirm images remain in the Library. | History record removed; images untouched. | |
| 16.5 | Restart Galileo and revisit History. | Sessions that were not deleted are still there. | |
| 16.6 | If you have more than one Pier, open **Dashboard**. | One row per Pier showing equipment, sequence and scheduler state. Double-click opens that Pier. | |

## Section 17 — Calibration frames

| ID | Action | Expected | Result |
|---|---|---|---|
| 17.1 | In **Imaging**, click **Darks…**. Enter exposure lengths matching your lights (`120`), **Start** (the simulator needs no cover). | A dark is captured at each length and saved to the Library. | |
| 17.2 | Click **Flats…**, choose **Flat Panel** (or Sky Flats at twilight). Leave exposure on **Calculate**; filter **All**. | A flat set is taken for each filter and saved to the Library. | |
| 17.3 | Capture **Bias** frames (Type = Bias, 0.001 s, Quantity 20). | Bias frames are filed in the Library. | |
| 17.4 | After enough calibration frames, check whether masters are built automatically (see Options > Library > Calibration). | Master bias, dark and flat appear. | |

## Section 18 — Library and processing

| ID | Action | Expected | Result |
|---|---|---|---|
| 18.1 | Open **Library > Images**. | The tree lists frames by object. M13 shows the session's frames. **Search** for `M13` works. | |
| 18.2 | Change **Sort by** to date and filter; set **Show** to *Light frames only*, then *Calibration frames*. | The view updates each time. | |
| 18.3 | Place FITS files from another night in the Incoming folder and click **Load New**. | They are catalogued and moved into the Repository, renamed from their metadata. | |
| 18.4 | Delete a frame; tick **Show Deleted**. | The frame disappears, reappears with Show Deleted, and the file remains on disk. | |
| 18.5 | Open **Library > Sessions** and select the M13 night. | The session lists lights with their matching calibration. | |
| 18.6 | Right-click the session: **Calibrate**. | Lights are calibrated with the matching masters. A progress indicator runs; output files appear. | |
| 18.7 | Right-click: **Stack** (or **Stack (photometric)**). | A stack is produced and opens in the configured viewer. M13 resolves into stars. | |
| 18.8 | Right-click: **Regenerate Thumbnail**. | The session's picture updates to the latest stack. | |
| 18.9 | Right-click: **Check out**, choose a folder. | Files are linked or copied there ready for PixInsight or Siril. | |
| 18.10 | Open **Dedup**, **Mappings** and **Merge Objects**. Merge a duplicate name (e.g. "Messier 13") into "M 13". | Each page opens; the merge combines the entries. | |
| 18.11 | Open **Cloud** and, if configured, **Analyze** then **Sync** (opt). | Cloud contents are matched with the local catalog; sync moves files according to the profile. | |
| 18.12 | Regenerate the catalog from the Repository (**Regenerate**). | The catalog is rebuilt from the FITS headers with no loss. | |

## Section 19 — Shut down for the night

| ID | Action | Expected | Result |
|---|---|---|---|
| 19.1 | **Equipment > Mount**: press **Park**. | Mount parks; Parked shows true. | |
| 19.2 | Warm the camera (or confirm the session did). | Cooler ramps to ambient. | |
| 19.3 | Close the dome (if any). | Shutter state reads closed. | |
| 19.4 | Close Galileo while a session is idle. | Exits cleanly with no crash report. | |
| 19.5 | Start Galileo again. | Observatory, Pier, equipment, optics, Options, saved sessions, templates and History are all intact. The M13 frames are still in the Library. | |

## Section 20 — Robustness and usability sweep

| ID | Action | Expected | Result |
|---|---|---|---|
| 20.1 | Stop and restart `indiserver` during an idle period. | Galileo reports the lost device in the log and status bar and stays responsive. Reconnecting works. | |
| 20.2 | Resize the window to a small size. | Controls remain reachable; no clipped dialogs. | |
| 20.3 | Hover several random controls on each screen. | Every control has a tooltip or help entry. | |
| 20.4 | Click any button greyed out with "Not implemented yet". | Tooltip says so; nothing else happens. | |
| 20.5 | Review the log file after the whole run. | No unexpected tracebacks. Any `ERROR` lines are accounted for by your deliberate fault injection. | |
| 20.6 | Check for crash reports in `reports/crash`. | None from this run, apart from deliberate crashes. | |

---

## Sign-off

| Outcome | Rule |
|---|---|
| **Accepted** | No ⛔ blocker failed; no more than 5% of other steps failed; every failure has a ticket. |
| **Accepted with conditions** | No blocker failed, but failures in Sections 7–15 (the live imaging path) need a fix before release. |
| **Rejected** | Any ⛔ blocker failed, or the app crashed in the live imaging path. |

| | |
|---|---|
| Steps run / passed / failed / N/A | |
| Failures raised (ticket links) | |
| Decision | |
| Tester signature and date | |
