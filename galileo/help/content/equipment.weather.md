<!-- order: 41 -->
# Safety

The Safety page connects Galileo to the devices that tell it whether it is safe to image: a **weather station** (readings such as temperature, wind and rain) and/or a **safety monitor** (a device that simply reports safe or unsafe). You can add several, each in its own tab, with the **+** button. These devices belong to the **Observatory**, not to a Pier: they are shared by all its Piers, stay connected when you select another Pier, and are not touched by the top-bar Pier **Connect**/**Disconnect** — use the tab's own **Connect**/**Disconnect** button.

For each measure you can decide which readings count as unsafe. A weather rule set to **Stop** counts exactly as much as a Safety Monitor. Only **saved** rules count. When conditions turn unsafe Galileo carries out a **protective stop**, whether or not anything is running: it starts nothing new, stops sessions and other activity including the exposure in progress, stops guiding, parks every mount and confirms it, then closes the dome. If a mount cannot be confirmed parked the roof is **left open**, the park is retried and you are alerted repeatedly. Afterwards nothing starts until conditions have been safe for a while and you press **Acknowledge safety stop** in the banner. A saved device that is not connected counts as unsafe. This cannot help if the computer loses power or its network, so keep hardware rain protection.

Set-up per tab (settings are saved under the selected Observatory): choose the **Driver**, **Server**, press **Scan**, pick the device, **Connect**, tick the measures that matter and set their thresholds, then **Save**.

## Poll (s)

How often, in seconds (5–600), Galileo re-reads the weather station. A shorter interval reacts faster; most stations only update every minute or so. It applies at once; **Save** keeps it.

## Add safety device

Adds another weather station or safety monitor in a new tab. The Observatory's own weather station (the first tab) cannot be closed; use **Delete** to remove its device.

## Delete

Removes this tab's device: disconnects it and forgets its saved settings and rules, after asking. An added tab goes with it; the first tab stays, blank. With no safety device left the safety system is off: nothing is blocked, parked or closed because of the weather, and a safety stop in force is cleared.

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

## When breached

**Stop** (the default) makes the Observatory unsafe and starts the protective stop. **Warn** only shows and reports it. Press **Save** to apply a change.

## Park and stop when unsafe

On by default. When off, unsafe conditions still stop anything new from starting and make running sessions skip all but their shutdown blocks, but nothing is stopped, parked or closed. Saved as soon as you change it.

## Close the roof

On by default. Close the dome or roof after the mounts are confirmed parked. Turn off if separate hardware looks after the roof.

## Lost device grace

How long a safety device that had been working may be unreadable before Galileo treats it as grounds for a protective stop (60 s by default). It blocks new starts at once.

## Safe for

How long conditions must stay safe, without a break, before a protective stop can be acknowledged (15 minutes by default, 5 at least).

## Restart scheduled sessions

Off by default. When on, scheduled sessions a protective stop ended become due again once conditions have been safe long enough, without waiting for you, **provided the stop completed**. A restarted session runs from its first block, so frames already taken are repeated. A session you started with Run is never restarted.

