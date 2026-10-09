<!-- order: 50 -->
# Guiding

Guiding keeps the telescope locked precisely on its target during long exposures by watching a star and correcting the mount. Galileo does not do the guiding itself: it controls **PHD2**, the free guiding program, over a network connection and shows what PHD2 is doing — the guide star, a live graph of tracking error, and calibration.

Before you start: run PHD2 (on this computer or another), then enter its address below and press **Connect**. PHD2 handles its own camera and mount; use **Connect Equipment** to tell it to connect them.

**Left:** controls, scope information and guide statistics. **Right:** the guide star image, the error graph, and the drift and calibration plots. **Bottom:** PHD2's event log.

## PHD2 host

The name or IP address of the computer running PHD2, for example `localhost` (this computer) or `192.168.1.50`.

## Port

PHD2's event-server port: 4400 for the first PHD2 running, 4401 for a second, and so on.

## Connect

Connects Galileo to PHD2 at the host and port above. If PHD2 is not running, start it first. The status line beside it says whether Galileo is connected.

## Disconnect

Disconnects Galileo from PHD2. PHD2 itself keeps running, and keeps guiding if it was.

## Save

Saves this host and port under the selected Observatory and Pier, so Galileo reconnects to the same PHD2 next time.

## Optic

Which optical train's information is shown under *Scope / Lens Info*. Guide scale and field of view are worked out from its focal length and the guide camera's pixel size.

## Control

The main guiding commands.

## Loop

Starts PHD2 taking repeating guide exposures without guiding, so you can see the star and adjust focus or exposure. Press **Stop** to end.

## Guide

Starts guiding on the selected star. If **Recalibrate on Guide** is ticked, PHD2 calibrates first. Press **Stop** to end.

## Stop

Stops looping or guiding.

## Auto Star

Asks PHD2 to pick the best guide star in the field automatically.

## Dither

Asks PHD2 to shift the guide position slightly in a random direction, then settle. Sessions do this between frames to avoid noise patterns. Needs guiding in progress.

## Exp

The guide exposure time. Short exposures react faster; long ones average out atmospheric seeing. The list comes from PHD2.

## Dec guide mode

Which declination corrections PHD2 may send the mount: **Off**, **Auto** (both directions), or **North** or **South** only. Use North or South only if your mount has Dec backlash.

## Recalibrate on Guide

When ticked, PHD2 recalibrates (measures how the mount responds) each time you press **Guide**. Untick to reuse the existing calibration, which is normally fine unless you changed the equipment or moved a long way across the sky.

## Clear Calibration

Throws away PHD2's calibration so it must be redone before the next guide start. Use after changing guide scope, camera angle or mount.

## Connect Equipment

Tells PHD2 to connect its own camera and mount (the ones chosen in PHD2's own settings).

## Disconnect Equipment

Tells PHD2 to disconnect its camera and mount.

## Scope / Lens Info

Details of the guide optics, worked out from the selected optical train.

## Focal length

The guide scope or lens's focal length, in millimetres.

## Aperture

Its aperture, in millimetres.

## Focal ratio

Focal length divided by aperture (the f-number).

## Guide scale

How much sky one guide-camera pixel covers, in arcseconds per pixel. Guiding errors in the graph are in the same units.

## Guide FOV

The width and height of the guide camera's field of view.

## Guide Info

Live statistics from PHD2, with right ascension (RA) and declination (DEC) columns.

## Guiding delta

The latest distance of the guide star from its locked position, in pixels or arcseconds, split into RA and Dec.

## Pulse length (ms)

How long the last correction pulse was, in milliseconds. Long pulses mean the mount is working hard to keep up.

## RMS (RA/DEC)

The root-mean-square tracking error in each axis since guiding started. Lower is better; compare with your image scale — an RMS well under your pixel scale gives round stars.

## Total RMS

The combined RA and Dec RMS error.

## Guide SNR

The guide star's signal-to-noise ratio. Below about 10, guiding becomes unreliable; choose a brighter star or lengthen the exposure.

## Star mass / HFD

The guide star's total brightness ("mass") and its half-flux diameter, a measure of how sharp it is.

## Idle

The status lamp: lit green while PHD2 is idle and not exposing.

## Prep

Lit yellow while PHD2 is preparing: looping, calibrating, a star picked or lost, or settling after a dither.

## Run

Lit red while PHD2 is actively guiding.

## Guiding state

Text from PHD2 describing what it is doing now (calibrating, guiding, settling, star lost…).

## Guide star

PHD2's picture of the guide star, with the lock position marked. Use Fit and 1:1 above it to change the zoom.

## Guide graph

Tracking error over time. The horizontal axis is time, the vertical axis is error in arcseconds. Choose which lines are drawn with the tick boxes beneath it.

## RA

The error or correction in right ascension. Tick it to draw it on the graph; it is also the label of the RA column of the statistics.

## DEC

The error or correction in declination. Tick it to draw it; also the label of the DEC column of the statistics.

## SNR

Draws the guide star's signal-to-noise ratio on the graph.

## Corr RA

Draws the correction pulses sent in right ascension.

## Corr DEC

Draws the correction pulses sent in declination.

## RMS

Draws the running RMS error on the graph.

## Graph zoom in

Narrows the graph's error range so small errors are easier to see.

## Graph zoom out

Widens the graph's error range.

## Trace

How many seconds of history the graph shows (30 to 600).

## Mount Drift

A scatter plot of the guide star's positions. Most points should fall inside the green ring; the yellow and red rings are two and three times its radius.

## Ring

The radius of the green target ring, in arcseconds. The yellow and red rings are 2× and 3× this.

## Calibration Plot

The result of PHD2's last calibration: how the star moved when the mount was pulsed in each direction. Clean, straight, perpendicular lines mean a good calibration.
