<!-- order: 34 -->
# Focuser

The Focuser page connects Galileo to the motorised focuser (or focusers) on your telescope and shows its live state. It is where you set the device up; focusing itself — autofocus runs, V-curves and filter offsets — is on the **Focus** screen.

The first row (Driver, Server, Port, Scan) is shared by every focuser panel. Below it each focuser has its own panel with its own Device, Connect button and readouts, which refresh every two seconds while connected.

Typical set-up: choose the **Driver**, enter the **Server**, press **Scan**, pick your focuser in **Device**, press **Connect**, then **Save**.

## Is Moving

**Yes** while the focuser is travelling to a new position. Autofocus and sequences wait for this to return to No before taking the next exposure.

## Is Settling

**Yes** for a short time after a move finishes, while the driver lets vibration die away. Exposures should not start until this is No.

## Max Increment

The largest single move, in steps, the focuser will accept in one command. Galileo's moves are kept within this; it is reported by the driver and cannot be changed here.

## Max Step

The highest position the focuser can reach — the end of its travel. Positions run from 0 to this value.

## Position (current)

Where the focuser is right now, in steps, as reported by the device.

## Position (target)

The position, in steps, you want the focuser to go to. It follows the current position until you start typing. Press **Move** to go there.

## Move

Sends the focuser to **Position (target)**. Connect the focuser first. The move is logged, and **Is Moving** shows progress.

## Temperature Compensation

Turns the focuser's own temperature compensation on or off, for devices that support it: the focuser adjusts its position automatically as the tube cools through the night, using the coefficient set in its driver. Leave it off if you use Galileo's autofocus on temperature or filter changes, so the two do not both correct the same drift.

## Temperature

The focuser's own temperature probe reading, in °C. Shows — if the device has no sensor.

## Add another device

Adds another focuser panel for a telescope that exposes more than one focuser (for example a coarse and a fine focuser). The panels share the Driver / Server / Port above. The first is the *Primary Focuser*, which the Focus screen drives.
