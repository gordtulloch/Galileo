<!-- order: 72 -->
# Library Sessions

A **session** is a set of frames of one object taken on one night with one setup (telescope, camera, filter). The Library builds sessions automatically from the frames in the catalog, and links each light session to the bias, dark and flat sessions that can calibrate it. The tree lists objects, and under each its sessions, with a thumbnail of the latest stack, the date, telescope, camera, filter, the number of frames, and *Resources* — how much calibration data it has.

Sessions are updated automatically after you load or download images. **Right-click** one for the actions below. **Double-click** a session's thumbnail to open its stacked image in your viewer.

## Regenerate

Rebuilds the sessions. You choose **All Sessions** (clear every session and recreate them from all the files) or **New Only** (only add sessions for files that do not belong to one yet). The steps are: update light sessions, update calibration sessions, link calibration to lights.

## Resources

How much calibration data this session has available (bias, dark and flat). On an object's row it is a summary — for example 3/4 (75%) of its light sessions have calibration resources; hover for details.

## Copy Session ID

Right-click menu: copies the selected session's ID (or IDs) to the clipboard.

## Check out

Right-click menu: makes the session's files available in a folder you choose, as symbolic links so nothing is copied, for use by a stacking program. A dialog asks for the **Target directory** and has options: *Copy Files, Don't Link (Slower)*, *Decompress* and *Masters Only*. With several light sessions selected it checks them all out.

## Calibrate

Right-click menu: calibrates this session's light frames using the master bias, dark and flat frames that match it.

## Stack

Right-click menu: stacks the session's light frames and opens the result in your FITS viewer. If the session is not already calibrated, it is calibrated first.

## Stack (photometric)

Right-click menu: makes a stack suitable for measuring star brightness — registered and averaged, with no sigma clipping, which would distort photometry — and opens it in your viewer.

## Regenerate Thumbnail

Right-click menu: recreates the session's thumbnail from the most recent stack file.

## View Master

Right-click menu on a calibration session: opens its master frame in your FITS viewer.
