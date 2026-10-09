<!-- order: 31 -->
# Mount

The Mount page connects Galileo to your telescope mount and shows where it is pointing, with manual controls for slewing, tracking, jogging, parking and safety limits.

Set-up: choose the **Driver**, enter the **Server**, press **Scan**, pick the mount in **Device**, press **Connect**, then **Save**. Once connected the readouts refresh continuously.

The left side is status and safety (what the mount reports, meridian flip, limits); the right side is control (coordinates to slew to, tracking, and the N/S/E/W pad).

## Name

The mount's name as reported by its driver.

## Description

The driver's own description of the mount.

## Site latitude

The latitude the mount believes it is at, in degrees (north positive). Pointing and meridian calculations depend on it, so check that it matches your observatory.

## Site longitude

The longitude the mount believes it is at, in degrees (east positive).

## Site elevation

The site height above sea level, in metres, as configured in the mount.

## Sidereal time

The local sidereal time at the mount's site — the right ascension currently on your meridian. An object whose RA equals this is due south (north in the southern hemisphere).

## Epoch

The coordinate system the mount reports in (for example J2000 or "local topocentric"). Coordinates you type are interpreted by the driver in this system.

## Meridian in

How long until the mount's current right ascension crosses the meridian, as hours:minutes:seconds. While it counts down the target is still east of the meridian; once it has passed, the target is west and a meridian flip may be due.

## Right Ascension

Where the mount is pointing in right ascension, in hours, minutes and seconds.

## Declination

Where the mount is pointing in declination, in degrees, minutes and seconds.

## Altitude

How high the mount is pointing above the horizon, in degrees.

## Azimuth

The compass direction the mount is pointing, in degrees from north through east.

## Side of pier

Which side of the pier the telescope is on (East or West), and which way it is pointing. A meridian flip changes the pier side.

## Tracking

Whether the mount is currently tracking the sky, and at what rate.

## Meridian Flip

When a telescope on a German equatorial mount tracks past the meridian, it must swing over to the other side of the pier. This group controls whether Galileo does that for you. The line beneath shows whether the flip is inactive, armed or done, and the pier side.

## Flip if HA >

Tick to let Galileo flip the mount. While the mount is tracking and still on the west side of the pier, Galileo flips it once the hour angle passes the number of degrees in the box beside it (5° is a common choice: it lets the telescope track a little past the meridian first), then resumes tracking. Make sure the cables and the telescope can clear the pier before relying on this. A flip the mount did not perform is not retried for 10 minutes.

## Limits

Safety limits that stop the mount if it points somewhere it should not. They apply on every page and while sequences run. Slew commands whose target is outside the limits are refused with a message in the status bar.

## Enable Alt limits

Turns on the minimum and maximum altitude limits below. If the mount is tracking or slewing outside them, Galileo stops it and says which limit was hit.

## Tracking only

Only enforce the altitude limits while the mount is tracking; a slew in progress is not interrupted. A slew whose target is outside the limits is still refused.

## Min. Alt

The lowest altitude, in degrees, the mount may point at — keeps the telescope away from the horizon, trees or a wall.

## Max. Alt

The highest altitude, in degrees, the mount may point at — useful when the telescope would hit the pier or a dome near the zenith.

## Enable HA limits

Turns on the hour-angle limit: the mount is stopped if it tracks further than the limit from the meridian.

## Max. HA (hours)

How far from the meridian, in hours, the mount may track before being stopped. Set it to protect against the telescope hitting the pier, or a cable wrap.

## Manual Coordinates

Slew the mount to a position typed in. Enter hours/minutes/seconds for right ascension and degrees/minutes/seconds for the others, then press the **Slew** button on that row.

## Target RA

The right ascension to slew to, in hours, minutes and seconds (0–23 h). Press **Slew** on this row or the Target Dec row; both slew to the RA and Dec together.

## Target Dec

The declination to slew to, in degrees, minutes and seconds. A negative degrees value means south; the minutes and seconds are added in that direction.

## Target Alt

The altitude to slew to, in degrees, minutes and seconds. Press **Slew** on this row or the Target Az row.

## Target Az

The azimuth to slew to, in degrees from north through east. Press **Slew** on this row or the Target Alt row.

## Slew

Moves the mount to the coordinates in this row (together with its partner row). Tracking starts automatically when the slew ends. The mount must be connected and unparked; if the target is outside a limit, or blocked, Galileo says so in the status bar instead of moving.

## Manual control

Direct control of tracking, the jog pad, and parking.

## Set tracking rate

Applies the rate chosen in the box beside it to the mount.

## Tracking rate

How fast the mount tracks: **Sidereal** for stars, **Lunar** for the Moon, **Solar** for the Sun, **King** for sidereal corrected for atmospheric refraction. Press **Set tracking rate** to apply it.

## Tracking On

Starts the mount tracking at the chosen rate.

## Tracking Off

Stops the mount's tracking; the sky then drifts across the field. Use it for balancing, or when you do not want the mount following the sky.

## Rate

How fast the N/S/E/W buttons move the mount: **Fine**, **Medium** or **Coarse**, shown with the speed in degrees per second. The same speeds are used by the Imaging page's Mount Nudge.

## N S E W

Start the mount moving north, south, east or west at the chosen **Rate**. The mount keeps moving until you press **Stop**. Directions can be flipped with the *reversed* options below.

## Stop

Stops all jog movement and abandons any slew in progress.

## Home

Sends the mount to its home position, if the driver supports finding it.

## Park

Moves the mount to its park position and, where the driver supports it, stops tracking. A parked mount refuses slews until it is unparked.

## Unpark

Releases the mount from its parked state so it can slew and track again.

## Park status

Whether the mount is parked.

## Primary reversed

Reverses the east/west buttons. Tick this if pressing E moves the image the wrong way for your optical set-up (for example with a mirror in the light path).

## Secondary reversed

Reverses the north/south buttons, for the same reason as **Primary reversed**.

## Settings

Mount-specific driver settings. None are available for this mount.
