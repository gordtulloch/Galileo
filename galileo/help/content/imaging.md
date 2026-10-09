<!-- order: 20 -->
# Imaging

The Imaging screen takes pictures through your camera and shows them as they arrive. Use it for framing and test exposures, for taking a run of frames by hand, and for calibration frames (flats and darks). For unattended multi-target nights use Planning › Sessions instead.

**Left:** capture settings, view options, and the mount nudge pad. **Right:** the live preview, a stretch control and histogram, and progress. **Bottom:** the log.

Before you start: connect a camera (Equipment › Camera) and pick the Optics and Camera in the top bar. Connect a filter wheel to see your filters, and a mount to use Mount Nudge.

## Capture Settings

The settings used for each exposure when you press **Capture**.

## Exposure

The length of each exposure, in seconds (as short as 0.001 s). Long exposures show fainter detail but trail if guiding is poor and saturate bright stars.

## Quantity

How many frames **Capture** takes in a row with these settings. With the quantity above 1 you can also build a live stack (see **Live Stack**).

## Gain

The camera's gain for each exposure. Higher gain boosts a faint signal at the cost of more noise and less dynamic range. 0 leaves the camera as it is already configured.

## Offset

The camera's offset (black level) for each exposure — keeps the darkest pixels above zero. 0 leaves the camera as configured.

## Type

What kind of frame this is: **Light** (the sky), **Dark** (shutter closed), **Flat** (evenly lit) or **Bias** (shortest possible exposure, shutter closed). The type is written into the saved file so the Library can sort and calibrate it. For a dark or bias, cover the telescope yourself — or use the Darks and Flats assistants, which handle that.

## Filter

The filter to use, from the filter wheel associated with the selected optics (connect the wheel on Equipment › Filter Wheel to fill this in). Choosing one turns the wheel. You can also type a name if no wheel is connected, and it is recorded in the frames.

## Capture

Starts taking the number of frames in **Quantity**. Each frame appears in the preview with its statistics when it arrives, and — if **Auto-Save to Library** is on — is filed in your Library.

## Stop

Abandons the exposure in progress and takes no more frames.

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

How the preview is displayed. None of these change what is saved.

## Debayer

Shows a one-shot-colour camera's frame in colour, using the Bayer pattern set for the camera on Equipment › Camera (RGGB by default). Only the preview changes: statistics, the histogram and **Save Frame** keep the camera's raw data. Leave off for a monochrome camera.

## Live Stack

Builds the frames of one **Capture** into a single image instead of each replacing the last: each frame is aligned to the first and added to a running mean, so the preview, statistics and histogram improve as the run goes on. Needs a run of several frames. Each frame still goes to the Library on its own; use **Save Stack** for the stacked image.

## Choose layout manually

By default the screen arranges itself to suit the frame: a portrait frame gets the whole right side, with the histogram and log moved to the left. Tick this to pick the arrangement yourself with **Layout**.

## Layout

**Landscape** or **Portrait** arrangement of the screen. Available only when **Choose layout manually** is ticked.

## Tools

A group for extra tools that plugins add. Hidden when none are installed.

## Mount Nudge

Nudges the telescope while you are looking at the preview — to centre a star, say. Uses the mount connected on Equipment › Mount, with the same directions as its jog pad.

## N S E W

Moves the mount north, south, east or west for the **Duration** set below, at the chosen **Speed**, then stops.

## Mount Nudge Stop

Stops the mount immediately, if you want to end a nudge early.

## Mount Nudge Speed

How fast the mount moves during a nudge: **Fine**, **Medium** or **Coarse**, with the speed in degrees per second.

## Mount Nudge Duration

How long the mount moves for each press, in seconds (0.1–10).

## Annotate

Labels catalogued stars and deep-sky objects on the preview. It plate-solves the displayed frame and overlays a circle and name at each object found, using Galileo's bundled catalogs. Needs a solver configured in Options › Solve. While on, **Save Frame** and **Save Stack** write the annotated view as a PNG instead of the raw FITS, and annotated frames are never added to the Library. Press again to turn it off.

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

What is happening now — exposing, downloading, frame number of the run — with a bar showing progress through the current exposure.
