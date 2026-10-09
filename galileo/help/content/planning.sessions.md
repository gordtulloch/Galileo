<!-- order: 15 -->
# Sessions

A session is a plan for a stretch of imaging, built from **blocks** laid out in order: slew to a target, change filter, autofocus, take 40 frames, park. You build sessions here, then **Run** them now or **Schedule** them for later. Sessions belong to a Pier and each Pier has its own list.

**To build one:** press **Add Session** (or use *Add to Session* on a target in the Star Atlas or Targets), then drag blocks from the palette on the right into the session. Drag a block within the session to reorder it. To change a block's settings, right-click it. To remove it, drag it out or use its right-click menu.

**Loops:** the *FOR Filter* and *FOR Object* blocks repeat everything indented beneath them — once per filter or once per object. A block dropped under a loop joins its body; drag it right to indent it or left to unindent it. A loop moves with its body.

**Running:** Galileo first checks the equipment each block needs is connected and the order is valid, and lists any problems rather than starting. While it runs, the card shows the block and frame in progress and a green ▶ on the executing block; it is locked against edits. A bad frame is logged and skipped (three in a row abandon that Image block); a failed slew, plate solve, park or dome-open ends the session so the equipment is not left in a bad state. If the safety monitor reports unsafe, only shutdown blocks (park, dome close, guide stop, warm) still run.

A scheduled session is outlined in red and read-only until it is descheduled.

## Add Session

Adds a new empty session to this Pier's list.

## Palette

The blocks you can add. Drag one into a session. A block that needs a Target before it (Plate Solve) can only be dropped below one.

## Save

Saves this session to disk so you can keep it and reuse it later.

## Save as Template

Saves this session's blocks under a name you give it, to reuse in other sessions. A template captures a repeatable procedure, not a particular framing, so mosaic settings are not included.

## Load from Template

Fills this session from a saved template. The session must already start with a real Target block: the template's first Target is stored as a generic placeholder, and your target takes its place. Templates are listed by name.

## Schedule

Puts this session on the Schedule calendar (Planning › Schedule) so it can be given a start time and run by itself. The card is then outlined in red and read-only. The button becomes **Deschedule**.

## Deschedule

Takes the session off the Schedule so it can be edited again.

## Run

Executes the session now, and places it on the Schedule starting now. If it overlaps something already planned, you are warned (not stopped).

## Pause

Holds the session before the next block or frame. The button then reads **Resume**.

## Resume

Carries on after a pause.

## Stop

Stops the running session and abandons the current exposure or slew.

## Delete

Removes this session from the list.

## Target

Slews the mount to a target and starts tracking. The name and coordinates are filled from a catalog search or from the object you added the session from. Plate Solve needs one earlier in the session.

## Image

Takes frames: exposure length, how many, which filter, binning, gain, offset and frame type. Frames are saved to the Library. It can also carry a mosaic definition, set under *Framing / Mosaic…* in its dialog; a mosaic block captures each pane in turn.

## Filter Change

Moves the filter wheel to a named filter. Any saved focus offset for that filter (from Focus › Filter Offsets) is applied too, so no full autofocus is needed.

## Cool Camera

Cools the camera's sensor to a set temperature before imaging.

## Warm Camera

Warms the sensor back up at the end of the night, using the camera's own warm-up routine, so it is not left cooled.

## Autofocus

Runs an autofocus sweep, using the settings in Options › Focus, optionally on a named filter.

## Plate Solve

Plate-solves an image and corrects the mount so the target is centred. Needs a Target block earlier in the session and a solver configured in Options › Solve.

## Guide Start

Starts autoguiding, optionally calibrating first. Needs PHD2 connected (Guiding screen).

## Guide Stop

Stops autoguiding.

## Dither

Nudges the guided position slightly between frames so noise and hot pixels do not line up.

## Flat Capture

Captures flat frames the way the Flats Assistant does: flat method, exposure (or calculate it), number of frames, filter, ADU method and exposure increment.

## Dark Capture

Captures dark frames the way the Darks Assistant does: one dark at each exposure length, optionally selecting a filter first.

## Park Mount

Parks the mount. Typically the last step of a night.

## Unpark Mount

Unparks the mount so it can slew and track.

## Meridian Flip

Flips the mount across the meridian. This block can still be loaded from older sessions but is no longer in the palette.

## Dome Open

Opens the dome shutter. Refused if the safety monitor says conditions are unsafe.

## Dome Close

Closes the dome shutter.

## Dome Sync

Moves the dome slit to line up with the telescope.

## FOR Filter

Repeats the blocks indented beneath it once for each filter you choose. Right-click to pick filters from the active filter wheel, plus any others you type in.

## FOR Object

Repeats the blocks indented beneath it once for each object in its list. Right-click, search the catalog and pick results to add; each is saved with its coordinates so it can be slewed to without another lookup.

## Notification

Sends your message to the notification channels you have set up (e.g. email or text) when it is reached. Good for "imaging finished" or "target done".

## Name

The target's name.

## RA

The target's right ascension in degrees.

## Dec

The target's declination in degrees.

## Exposure

Length of each exposure in seconds. In a Flat Capture, leave it at Calculate to work it out from the camera's Max Well Depth.

## Count

How many frames to take with this block.

## Filter

The filter for this block. In an Image or Filter Change block the list comes from the active filter wheel; you can type one if no wheel is connected.

## Binning

Combines pixels in blocks (1×1 to 4×4) for more sensitivity at lower resolution.

## Gain

The camera gain for these frames. "(camera default)" leaves it as the camera is configured.

## Offset

The camera offset for these frames. "(camera default)" leaves it as the camera is configured.

## Frame type

Light, Dark, Flat or Bias.

## Framing / Mosaic

Opens a small dialog to define a mosaic for this Image block: the centre, and the number of columns and rows of panes with their overlap.

## Centre RA

The mosaic's centre right ascension in degrees.

## Centre Dec

The mosaic's centre declination in degrees.

## Mosaic cols

Number of panes across.

## Mosaic rows

Number of panes down.

## Overlap

How much neighbouring panes overlap, as a percentage.

## Setpoint

The sensor temperature to cool to, in °C.

## Focus on the current filter

Tick to autofocus with whichever filter is in place. Untick to name a filter to switch to first.

## Calibrate before guiding

Runs a guider calibration before guiding starts. Needed after changing the optics or rotating the camera; otherwise skip to save time.

## Flat Method

Sky Flats, Observatory Panel or Flat Panel — where the flat-field light comes from.

## Number of Frames

How many flats to take per filter.

## Method

How flat brightness is measured: Average or Median of the pixels.

## Exposure Increment

The smallest exposure step, in seconds, used while hunting for the right flat exposure.

## Exposures (s)

A comma-separated list of dark exposure lengths in seconds, one dark taken at each. For example 10,20,30,60.

## Message

The text to send in a Notification block.
