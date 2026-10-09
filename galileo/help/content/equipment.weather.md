<!-- order: 41 -->
# Safety

The Safety page connects Galileo to the devices that tell it whether it is safe to image: a **weather station** (readings such as temperature, wind and rain) and/or a **safety monitor** (a device that simply reports safe or unsafe). You can add several, each in its own tab, with the **+** button.

For each measure you can decide which readings count as unsafe. When anything is unsafe the banner above the table turns to UNSAFE, sequences stop imaging and close up, and the dome refuses to open.

Set-up per tab: choose the **Driver**, **Server**, press **Scan**, pick the device, **Connect**, tick the measures that matter and set their thresholds, then **Save**.

## Poll (s)

How often, in seconds (5–600), Galileo re-reads the weather station. A shorter interval reacts faster; most stations only update every minute or so. It applies at once; **Save** keeps it.

## Add safety device

Adds another weather station or safety monitor in a new tab. The Pier's own weather station (the first tab) cannot be closed.

## Status banner

The overall verdict: SAFE, or UNSAFE with the reasons, or Not connected.

## Measure

One reading the device provides (temperature, humidity, wind speed, cloud cover, rain…), with its unit.

## Current

The latest value of each measure as read from the device. — means the device does not provide it.

## Blocks Dome Opening

Tick a measure to make it part of the safety decision. A ticked measure that breaks its rule makes the observatory UNSAFE; a measure left unticked is shown for information only.

## Unsafe When

How the reading is compared with the threshold: for example *greater than*, so that wind faster than the threshold is unsafe. Only available when the measure is ticked.

## Threshold

The value at which the measure becomes unsafe, in the measure's own unit. For a yes/no reading such as rain, use 0 or 1 as the device does. Only available when the measure is ticked.
