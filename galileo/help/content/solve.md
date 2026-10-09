<!-- order: 60 -->
# Solve

Plate solving works out exactly where an image is pointing by matching the stars in it against a catalog. Galileo uses it to find out where the telescope really is, to correct the mount's pointing (**Sync**), to put a target dead-centre (**Slew to Target**), and to polar-align the mount.

**Left:** the solve controls, what to do with the answer, and the coordinates. **Right:** the frame, then two tabs — *Solution Results* (every solve) and *Polar Alignment* — and the log.

Before you start: connect a camera and a mount, pick the Optics and Camera in the top bar, and make sure ASTAP is installed (Options › Solve).

## Solver Control

Starts and stops a solve.

## Capture & Solve

Takes an exposure with the selected camera, solves it, and then performs the Solver Action chosen below. The exposure length is set in *Plate Solve Capture Options*.

## Load & Slew

Solves a FITS file from your disk, then slews the mount to where that image points. Useful for returning to a previous night's framing.

## Stop

Stops the solve or the repeating slew-and-solve loop in progress.

## Busy

A moving bar that shows a solve is running.

## Solver Action

What to do once an image has been solved.

## Sync

Tells the mount where it is really pointing, correcting its pointing model. Use this to align the mount to the sky.

## Slew to Target

Slews to the target, then solves, syncs and slews again until the pointing is within the Accuracy set. The target is the Pier's current object (picked in the Star Atlas or Planning); with none, it is wherever the mount was pointing when Capture & Solve began.

## Nothing

Only solves. The mount is not touched.

## Target

What Slew to Target will aim at: the current object's name, or where the mount points when the run starts.

## Telescope Coordinates (JNow)

Where the mount says it is pointing, in the coordinate system of the date ("JNow").

## Telescope RA
<!-- keys: telescope-coordinates-jnow-ra -->
The mount's current right ascension.

## Telescope DE
<!-- keys: telescope-coordinates-jnow-de -->
The mount's current declination.

## Accuracy

How close, in arcseconds, a solution must be to the target for **Slew to Target** to stop repeating. 30″ is fine for most framing; use a smaller number for a small field of view. The error plot's ring shows this size.

## Settle

How long to wait after a slew, in milliseconds, before taking the next frame, so vibrations die away.

## Solution Coordinates (JNow)

What the last solve found, again in coordinates of the date.

## Solution RA
<!-- keys: solution-coordinates-jnow-ra -->
The right ascension of the centre of the solved image.

## Solution DE
<!-- keys: solution-coordinates-jnow-de -->
The declination of the centre of the solved image.

## Err

How far the solved centre is from the target, in arcseconds.

## Pix

The image scale the solve found, in arcseconds per pixel.

## PA

The position angle: which way the image is rotated on the sky, in degrees east of north.

## FOV

The width and height of the solved field of view.

## R

The solved image scale divided by the scale your optics predicted. Close to 1.00 means your focal length and pixel size are right; a value far from 1 suggests the focal length entered on Equipment › Optics is wrong.

## FL

The focal length implied by the solve, in millimetres.

## F/

The focal ratio implied by the solve.

## Plate Solve Capture Options

Settings for the exposure taken by **Capture & Solve** and by polar alignment.

## Exp

The exposure length for solve frames, in seconds. Long enough to show plenty of stars; much longer than needed only slows things down.

## Solver Mode

Which solver to use.

## ASTAP

The local ASTAP solver, which works with no internet connection. Its location and defaults are set in Options › Solve.

## Frame

The frame most recently captured or loaded for solving, with a caption above it describing it. Use the zoom buttons to look closer.

## Solution Results

A table of every solve, from this screen or from elsewhere in Galileo: right ascension, declination, object name, result (success or failure), and the offset from the target in RA and Dec (dRA, dDE). Beside it, a plot shows where each solution fell relative to the target, with a ring of the Accuracy size.

## Error plot

Each solve's miss relative to the target. Points inside the ring are within the Accuracy.

## Clear

Removes every result from the table.

## Remove

Removes the selected results.

## Save

Saves the results to a CSV file.

## Polar Alignment

Helps you point the mount's polar axis exactly at the celestial pole. Point it roughly first, then start. Galileo solves three frames, turning the mount in RA between them, to find where the axis really points, then keeps solving so the error updates live as you turn the altitude and azimuth adjusters. The mount must be level and not near the meridian, where it would flip. It needs a camera, a mount, and the Observatory's latitude and longitude.

## Start Polar Alignment

Begins the procedure (the exposure is the one under Plate Solve Capture Options). It then reads **Stop**; press that to end. It refuses a rotation that would carry the mount across the meridian.

## Rotate

How far the mount turns in RA between the three measuring frames, 10–90°. A bigger turn is more accurate but needs more clear sky. Beside it you choose the direction.

## Direction

Which way the RA axis turns, **East** or **West**. Choose the side with clear sky and room before a mount limit.

## Refraction

Allows for the atmosphere lifting stars, so the mount is aimed where it must point to see them. On by default. The target stays the geometric pole.

## Polar alignment status

What the procedure is doing now, or why it stopped.

## Total error

How far the polar axis is from the pole, in arcminutes and arcseconds. Aim for under a few arcminutes.

## Altitude correction

Which way and how much to move the mount's altitude adjuster, in words (for example "Lower the polar axis by 12′00″").

## Azimuth correction

Which way and how much to move the mount's azimuth adjuster, in words.
