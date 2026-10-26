<!-- order: 34 -->
# Focuser

The Focuser page connects Galileo to the motorised focuser (or focusers) on your telescope and shows its live state. It is where you set the device up; focusing itself — autofocus runs, V-curves and filter offsets — is on the **Focus** screen.

The first row (Driver, Server, Port, Scan) is shared by every focuser panel. Below it each focuser has its own panel with its own Device, Connect button and readouts, which refresh every two seconds while connected.

Typical set-up: choose the **Driver**, enter the **Server**, press **Scan**, pick your focuser in **Device**, press **Connect**, then **Save**.

## Mode

How Galileo moves this focuser. **Absolute** (the default) is for focusers whose driver reports and accepts positions — nearly all of them. **Pulse** is for simple focusers that can only be told to run their motor for a number of milliseconds (INDI's `FOCUS_TIMER`) and cannot say where they are; Galileo then keeps the position itself, counting each completed pulse as one step per millisecond on a 0–50000 scale. Pulse needs an **INDI** driver and is not offered for Alpaca. Press **Save** to keep the mode.

In Pulse mode, "step size" anywhere in Galileo (autofocus, the Focus screen's In/Out buttons) means milliseconds of motor run time, and pulses shorter than 32 ms are not sent.

## Pulse set-up

Shown only in Pulse mode. A pulse focuser has no idea where it is, so Galileo needs you to tell it once: move the focuser to the middle of its travel, then press **Reset to middle**. From then on Galileo remembers the position, including across restarts, so you only repeat this if the focuser has been moved by hand or has slipped.

## Reset to middle

Shown only in Pulse mode. After you confirm that the focuser is physically at the middle of its travel, sets Galileo's position to 25000 (the middle of the 0–50000 pulse range) and remembers it. Because the old origin is gone, set **Minimum Travel** and **Maximum Travel** again afterwards. With no position remembered, a pulse focuser is assumed to be at 25000.

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

## Minimum Travel

The lowest position moves are allowed to reach, or — if none is set. It protects the focuser from running into its physical stop: autofocus, sequences and the Move button are all held to it, in Absolute and Pulse modes alike. Move the focuser to the safe end of its travel and press **Set Min**. Kept with the focuser; the value is also applied straight away when the focuser is connected.

## Set Min

Remembers the focuser's current position as **Minimum Travel**. Connect the focuser first. It must stay below **Maximum Travel**. Press **Save** the first time so the limit is kept with the focuser's settings; until then it only lasts for this session.

## Maximum Travel

The highest position moves are allowed to reach, or — if none is set. The counterpart of **Minimum Travel**: move the focuser to the safe far end of its travel and press **Set Max**.

## Set Max

Remembers the focuser's current position as **Maximum Travel**. Connect the focuser first. It must stay above **Minimum Travel**.

## Clear

Removes both travel limits, so moves are limited only by the focuser's own range.

## Emergency Focus

This focuser's saved emergency focus position, or — if none is set. Each focuser keeps its own. Press **Set** when focus is good to remember where the focuser is now (connect it first, and **Save** the focuser's settings at least once); press **Move** to send it back there if you are ever wildly out of focus.

## Temperature Compensation

Turns the focuser's own temperature compensation on or off, for devices that support it: the focuser adjusts its position automatically as the tube cools through the night, using the coefficient set in its driver. Leave it off if you use Galileo's autofocus on temperature or filter changes, so the two do not both correct the same drift.

## Temperature

The focuser's own temperature probe reading, in °C. Shows — if the device has no sensor.

## Add another device

Adds another focuser panel for a telescope that exposes more than one focuser (for example a coarse and a fine focuser). The panels share the Driver / Server / Port above. The first is the *Primary Focuser*, which the Focus screen drives.
