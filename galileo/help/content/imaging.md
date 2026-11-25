<!-- order: 20 -->
# Imaging

The Imaging screen takes pictures through your camera and shows them as they arrive. Use it for framing and test exposures, for taking a run of frames by hand, and for calibration frames (flats and darks). For unattended multi-target nights use Planning › Sessions instead.

**Left:** capture settings, view options, and the **Mount Control** button. **Right:** the live preview, a stretch control and histogram, and progress. **Bottom:** the log.

Before you start: connect a camera (Equipment › Camera) and pick the Optics and Camera in the top bar. Connect a filter wheel to see your filters, and a mount to use Mount Control.

## Capture Settings

The settings used for each exposure when you press **Capture**.

## Exposure

The length of each exposure, in seconds (as short as 0.001 s). Long exposures show fainter detail but trail if guiding is poor and saturate bright stars.

## Object

The name of the object being imaged, written to each frame's OBJECT header card and used in its file name. It follows the selected object (Star Atlas, Targets) and shows **Unknown** when nothing is selected. Type a name and press Enter (or click elsewhere) to make that object the **current object** of the Pier, as if you had picked it in the Star Atlas: it is looked up in the offline catalog, and online (Simbad) if not there. A name that can't be found still names your frames, but the current object stays as it was (it needs coordinates). Selecting a different object replaces what you typed, and clearing the box puts Unknown back without clearing the current object. Dark, flat and bias frames never carry an object.

## Quantity

How many frames **Capture** takes in a row with these settings. With the quantity above 1 you can also build a live stack (see **Live Stack**).

## Gain

The camera's gain for each exposure. Higher gain boosts a faint signal at the cost of more noise and less dynamic range. 0 leaves the camera as it is already configured.

## Offset

The camera's offset (black level) for each exposure — keeps the darkest pixels above zero. 0 leaves the camera as configured.

The saved frame's GAIN and OFFSET header cards are read back from the camera after the exposure, so they show what it really used (a value of 0 is recorded as 0). If a camera can't report a value, what you entered is recorded instead.

## Type

What kind of frame this is: **Light** (the sky), **Dark** (shutter closed), **Flat** (evenly lit) or **Bias** (shortest possible exposure, shutter closed). The type is written into the saved file so the Library can sort and calibrate it. For a dark or bias, cover the telescope yourself — or use the Darks and Flats assistants, which handle that.

## Filter

The filter to use, from the filter wheel associated with the selected optics (connect the wheel on Equipment › Filter Wheel to fill this in). Choosing one turns the wheel. You can also type a name if no wheel is connected, and it is recorded in the frames.

## Camera Temp

The camera's current sensor temperature, refreshed every few seconds, with the cooler power in brackets when the camera reports it. Shows a dash when no camera is connected or it cannot report a temperature.

## Target

The sensor temperature to cool to, in °C. It is sent to the camera when you tick **Cooler on**, and again if you change it while the cooler is on.

## Cooler on

Switches the camera's cooler on (cooling to **Target**) or off. The box follows the camera, so if the cooler is switched elsewhere it updates within a few seconds. Cooling and warming too fast can stress the sensor — step the target gradually.

## Capture

Starts taking the number of frames in **Quantity**. Each frame appears in the preview with its statistics when it arrives, and — if **Auto-Save to Library** is on — is filed in your Library.

## Loop

Like **Capture**, but repeats: as soon as one run of **Quantity** frames finishes, the next starts, until you press **Stop** (or a capture fails).

## Stop

Abandons the exposure in progress and takes no more frames. If **Loop** is running, it ends the loop.

## Clear Mosaic

Appears when a mosaic has been defined in the Framing assistant. Discards the mosaic and goes back to capturing a single frame.

## Mosaic

Shown while a mosaic is active: how many panes the grid has and which one is being captured.

## Save Frame

Saves the displayed frame as a FITS file, with all the header information Galileo knows: the target, optics, filter, gain and so on. Greyed out until a frame has been captured. If **Annotate** is on, saves the annotated view as a PNG instead.

## Save Stack

Saves the live stack (see **Live Stack**) to the Library or to a FITS file. Greyed out until a stack exists.

## Auto-Save to Library

When ticked (the default), every frame is written to a scratch folder and registered in the Library, which files it in your repository — it then appears on Library › Images. Needs the repository folder set in Options › Library. Turn it off for throwaway test exposures.

## View

How the preview is displayed. None of these change what is saved. A one-shot-colour camera's frames are shown in colour automatically (see **Debayer**); statistics, the histogram and **Save Frame** keep the camera's raw data.

## Debayer

Shows the preview in colour by debayering the camera's mosaic. It is ticked automatically when the camera reports a Bayer pattern; tick or untick it yourself to override. If the camera reports no pattern but you tick it, the pattern saved on Equipment › Camera is used (wrong colours mean that pattern is wrong). Only the preview changes — statistics, the histogram and **Save Frame** keep the camera's raw data.

## Subtract dark

Subtracts the Library's dark master from the preview, from the frames added to a Live Stack or mosaic, and from the frame given to the solver (Annotate), when one exists for this camera and optics. A master matches when it was made with the same telescope and camera, at the same binning and an exposure within 1% of the frame's. The newest match is used; the status line says which master was applied, or why none was (no match, a different frame size, or no frame yet). Each frame filed in the Library or saved with **Save Frame** stays raw, as do its statistics and histogram. A stack is different: it is built from dark-subtracted frames, so its statistics, **Save Stack** and saving the stack to the Library carry the subtraction, recorded in its `DARKMAST` header so the Library does not calibrate the dark off a second time. Whether a run's stack subtracts darks is decided when the run starts. The setting lasts for the session.

The label beside it reads **Dark available** or **No dark available** for the optics and camera selected at the top of the window and the **Exposure** set above (at the capture's binning, 1x1 unless set otherwise); hold the pointer over it to see which master matches. The box is ticked for you when one is available and unticked when none is. You can override it either way, and your choice is kept for that combination of optics, camera, exposure and binning until Galileo is closed.

## Live Stack

Builds the frames of one **Capture** into a single image instead of each replacing the last: each frame is aligned to the first and added to a running mean, so the preview, statistics and histogram improve as the run goes on. Needs a run of several frames. Each frame still goes to the Library on its own; use **Save Stack** for the stacked image.

## Choose layout manually

By default the screen arranges itself to suit the frame: a portrait frame gets the whole right side, with the histogram and log moved to the left. Tick this to pick the arrangement yourself with **Layout**.

## Layout

**Landscape** or **Portrait** arrangement of the screen. Available only when **Choose layout manually** is ticked.

## Tools

A group for extra tools that plugins add. Hidden when none are installed.

## Mount Control

Opens the mount nudge pad in a small window that stays in front of the Imaging screen without blocking it, so you can nudge while watching the preview. It closes itself when you leave the Imaging screen; press the button again to bring it back. Below the nudge pad it also holds the mount's Park / Unpark, Home, Track On, Track Off and Do Meridian Flip buttons.

## Park

Parks the mount at its park position (set on Equipment › Mount). Same command as the Mount screen's Park. This button reads **Park** while the mount is unparked and **Unpark** while it is parked, and follows the mount's own status while the window is open.

## Unpark

Unparks the mount so it can slew and track again. Shown in place of **Park** while the mount is parked.

## Home

Sends the mount to its home position (the driver's Find Home).

## Track On

Turns mount tracking on.

## Track Off

Turns mount tracking off.

## EMERGENCY STOP

The red button under the meridian-flip button: stops all mount motion at once — it abandons a slew in progress and halts both axes, including any nudge still held. Tracking is left as it is. Use it the moment something looks wrong.

## Do Meridian Flip

Flips the mount to the other side of the pier, after you confirm: it slews to where it is pointing now (so the mount chooses the other side) and resumes tracking when the slew ends. Use it once the target has crossed the meridian and the cables are clear; it does not re-centre or restart guiding.

## Mount Nudge

Nudges the telescope while you are looking at the preview — to centre a star, say. Uses the mount connected on Equipment › Mount, with the same directions as its jog pad.

## N S E W

Hold an arrow button to move the mount north (↑), south (↓), east (→) or west (←), or diagonally (↖ ↗ ↙ ↘, which drive both axes) at the chosen **Speed**; it stops the moment you release the button (or if the window loses focus).

## Mount Nudge Stop

The red centre button. Stops both axes immediately, in case a button was not released cleanly.

## Mount Nudge Speed

How fast the mount moves while a button is held: from **1** (slowest) to **9** (fastest), with the speed in degrees per second. The levels are the same as the Mount page's Rate.

## Rotator

Sets the camera rotation without leaving the preview. Uses the rotator connected on Equipment › Rotator.

## Rotation

The angle, in degrees (0 – 359.99), to turn the rotator to. Nothing moves until you press **Set**.

## Rotation Set

Moves the connected rotator to the **Rotation** angle. If no rotator is connected, the status bar says so.

## Annotate

Labels catalogued stars and deep-sky objects on the preview. It plate-solves the displayed frame and overlays a circle and name at each object found, using Galileo's bundled catalogs. Needs a solver configured in Options › Solve. While on, **Save Frame** and **Save Stack** write the annotated view as a PNG instead of the raw FITS, and annotated frames are never added to the Library. Press again to turn it off.

## Crosshair

Overlays a red diagonal crosshair, with a target circle at the point where the lines cross, on the preview so you can see the exact centre of the frame — handy for centring a target. Display only: saved frames and stacks are not changed. Press again to turn it off.

## More

A menu of the power and dew channels you ticked **Show on imaging** on Equipment > Switches, so you can change them without leaving the frame you are taking. Each channel has an **On** / **Off** button; a dew heater also has a percentage (0 to 100) with a **Set** button. The menu stays open while you work and shows the device's present state each time it opens. It says so when no switch device is connected or no channel is ticked. Switching a channel off while a session runs asks you to confirm first. The same channels appear on the web and mobile Imaging screens.

## Framing

Opens the Framing Assistant: shows the field of view of the selected optics on the sky, and lets you set up a mosaic grid to capture directly from this screen.

## Flats

Opens the Flats Assistant, which captures a set of flat frames for you — automatically from the twilight sky, or using a flat panel.

## Darks

Opens the Darks Assistant, which captures one dark frame at each exposure length you list.

## Stretch

How hard the preview is stretched to show faint detail. Higher makes the preview brighter and higher-contrast (and more washed-out); lower keeps more of the original range. Only the preview changes — the raw frame, its statistics, the histogram and any saved file are unaffected.

## Histogram

The distribution of pixel brightness in the frame, dark on the left to bright on the right. A spike pressed against the right edge means saturation — shorten the exposure; a spike hugging the left edge means the exposure is too short or the gain too low to rise above the noise.

## Preview

The most recent frame, auto-stretched so faint detail is visible. Scroll to zoom, drag to pan. Use Fit and 1:1 above the picture to reset the zoom.

## Progress

What is happening now — exposing, downloading, frame number of the run — with a bar showing progress through the current exposure. While a session is running on the selected Pier it shows the session's progress instead — its name, block number, frame count and what it is doing — and returns to Idle when the session ends.
