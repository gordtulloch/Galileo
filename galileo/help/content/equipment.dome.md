<!-- order: 37 -->
# Dome

The Dome page controls an observatory dome or roll-off roof shutter, shows its state, and reports whether the whole observatory is ready to image. Sessions use it to open the shutter at the start of the night and close it at the end or when conditions turn unsafe.

Set-up: choose the **Driver**, **Server**, press **Scan**, pick the dome, **Connect**, then **Save**.

## Shutter

The shutter's state in large type: Open, Closed, Opening, Closing or Error. — means unknown or not connected.

## Azimuth

Where the dome slit is pointing, in degrees from north through east. A dome that follows the telescope keeps this in step with the mount; a roll-off roof has no azimuth.

## Motion

Opens and closes the shutter.

## Open

Opens the dome shutter. Only do this when the weather is safe; if a safety monitor is connected and reports unsafe, sequences will refuse to open it.

## Close

Closes the dome shutter. Use it when you are done, or whenever rain, wind or cloud threaten.

## Park

Moves the dome to its park position.

## Abort

Stops the dome moving immediately, whatever it was doing.

## Park status

Whether the dome is at its park position.

## Observatory Status

A read-only summary of whether the observatory is safe to open and use.

## Dome

The dome's own status: connected, shutter state and any fault. The coloured square is green when fine, amber when something needs attention, red on a fault.

## Weather

The state of the safety device (weather station or safety monitor). Red means conditions are unsafe, and the dome will not be opened.

## Observatory Ready

An overall verdict: Ready only when the dome is connected and the weather is safe.
