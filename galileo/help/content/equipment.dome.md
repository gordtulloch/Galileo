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

## Slaving

Makes the dome follow the telescope. Once a dome and a mount are both connected, the dome is slewed to the mount's azimuth whenever the mount is tracking and the dome has fallen more than a couple of degrees behind. Nothing moves while the mount is parked, slewing or not tracking.

## Slave dome to mount

Turns azimuth slaving on or off for this Pier. Leave it off for a dome run by independent third-party slaving hardware or software, so the two never fight over the dome.

## Open/close dome with sessions

When ticked, a session opens the shutter as it starts and closes the shutter and parks the dome as it ends (even if it was stopped or failed). The shutter also stays open through a meridian flip, and the dome re-follows the mount afterwards. Off by default; the Dome Open / Close / Sync blocks work either way.

## Slaving status

Whether slaving is off, waiting for a mount or for the mount to start tracking, or the azimuth the dome was last sent to.

## Sync to mount

Slews the dome to the mount's current azimuth once, even if slaving is off. The same thing the Dome Sync session block does.

## Observatory Status

A read-only summary of whether the observatory is safe to open and use.

## Dome

The dome's own status: connected, shutter state and any fault. The coloured square is green when fine, amber when something needs attention, red on a fault.

## Weather

The state of the safety device (weather station or safety monitor). Red means conditions are unsafe, and the dome will not be opened.

## Observatory Ready

An overall verdict: Ready only when the dome is connected and the weather is safe.
