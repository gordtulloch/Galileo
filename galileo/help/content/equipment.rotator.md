<!-- order: 33 -->
# Rotator

The Rotator page controls a camera rotator, which turns the camera so that your framing stays as planned, and can *derotate*: on an alt-azimuth mount the sky field rotates as the target moves, and a rotator can cancel that turn continuously.

The left panel is the rotator itself — its position, direction, backlash and derotation trim. The right panel is the derotation calculation: where you are, what you are pointing at, and the rate needed.

Set-up: choose the **Driver**, **Server**, press **Scan**, pick the rotator, **Connect**, then **Save**.

## Backlash

Mechanical slack in the rotator's gears, in steps (0 to 100). If the driver supports it, the slider sets how many steps the rotator overshoots and returns on a move, so it always arrives from the same direction. Greyed out when the driver has no backlash setting. Move the slider and press **OK** to apply it.

## Backlash OK

Applies the backlash value chosen on the slider to the rotator.

## Virtual Mechanical Position

The rotator's current position in degrees, in large type, with the mechanical and sky angles beneath. "Mechanical" is where the rotator hardware is; "sky" is the position angle on the sky after your zero point and reversal are applied.

## Goto position

The angle, 0–359.99°, to turn the rotator to. Type it and press **Goto**.

## Goto

Turns the rotator to the angle entered beside it. It is locked while derotation is running, because derotation owns the rotator then.

## Reverse

Reverses the rotator's direction of travel. While derotating it also flips the derotation direction, so a reversed rotator still compensates the field the right way.

## Set Current Position as Zero

Declares the rotator's present physical position to be 0°. Use it once the camera is square to the sky (for example, after aligning with a known star-field orientation), so angles you enter mean something. Not available while derotating, or for rotators that cannot be synced.

## Derotation Rate Correction

A fine trim, −100% to +100%, applied to the computed derotation rate. If stars still slowly rotate during long exposures, nudge this a little and watch the next frames. Move the slider and press **OK**.

## Correction OK

Applies the correction percentage chosen on the slider.

## Start Derotation

Starts continuously turning the rotator to cancel field rotation for the target below. The button then reads **Stop Derotation**; press it to finish. It needs a connected rotator, the site latitude and longitude, and a target that is above the horizon.

## Derotation

The calculation behind derotation: the local date and time, the site, the target, and the resulting rate.

## Latitude

The site latitude in degrees (north positive). It fills in from the selected Observatory when it has one; correct it here if not.

## Longitude

The site longitude in degrees (east positive). Filled from the selected Observatory when it has one.

## Target

Where the telescope is pointing, which determines the derotation rate. Type the coordinates in, or take them from a FITS file.

## Sync from FITS

The folder of FITS frames to take pointing from. Press **Sync** to read the position recorded in the newest file there.

## Browse Folder

Choose the folder of FITS frames to sync from.

## Sync

Uses the pointing recorded in the newest FITS file in the chosen folder as the target coordinates.

## RA

The target's right ascension in hours, minutes and seconds.

## DEC

The target's declination: choose + or −, then degrees, arcminutes and arcseconds.

## Altitude

The target's current altitude above the horizon, worked out from the site, time and target. Field rotation is fastest when the target is high in the sky (near the zenith of an alt-az mount).

## Azimuth

The target's current compass direction.

## Derotation Rate — Degrees/Minute

The rate at which the rotator must turn, in degrees per minute, to hold the field steady. It changes continuously as the target moves; with derotation running the rotator follows it.
