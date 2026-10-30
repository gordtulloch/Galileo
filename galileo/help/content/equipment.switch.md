<!-- order: 39 -->
# Switches

The Switches page controls a power box or relay board: switch its USB and DC ports, run dew heaters, set a regulated output, and read its voltage and current. It works the same whether the box is reached over INDI or Alpaca.

Set-up: choose the **Driver**, **Server** and **Port**, press **Scan**, pick the **Device**, press **Connect**, then **Save** to remember it for this Pier. Panels contributed by plugins (for example a Kasa smart plug) sit above this section.

INDI power boxes that follow INDI's standard power interface (Pegasus Pocket Powerbox Micro and Advanced, Ultimate Powerbox V3, Terrans PowerBoxGo V2 and PowerBoxPro V2, and others) need nothing extra. A box whose driver does not follow the standard, such as the Wanderer Astro boxes, needs its plugin installed; without it the device is listed under **Other** exactly as its driver defines it, and is also available on the Aux page.

## Scan

Queries the server and lists the switch devices it offers in the **Device** box. A device a plugin knows how to map is listed even when its driver does not call itself a power device.

## Connect

Connects the device named in **Device** and builds its control panel. The panel then refreshes itself every couple of seconds, so changes made at the box or by another program appear here. A coloured dot beside a control shows the driver's state for it: grey idle, green OK, yellow busy, red alert.

## Save

Remembers the driver, server, port and device for the selected Observatory and Pier, so the device connects again when that Pier is opened.

## Ports and groups

Each group of ports (DC, USB, dew heaters, adjustable outputs) has its own section. Each port has an **On** / **Off** button. A port the hardware cannot switch (a 12 V output wired straight to the supply, for example) is shown as *not switchable* with no button. A control the driver is not offering right now is greyed out, with the reason as a tooltip: a dew heater's duty, for instance, is unavailable while the heater is in an automatic mode.

Port names are the driver's own, or the box's vendor names where a plugin supplies them. A device that groups several ports behind one switch (the Wanderer Plus V3's USB ports, for instance) shows that one switch.

Switching a port off while a session is running on this Pier asks you to confirm first, naming the port. Switching it on never asks. Actions a session performs itself are not asked about.

## Dew heaters

Shows the heater's duty as a percentage from 0 to 100, whatever scale the driver uses, with the heater's current where the box measures it. Type a percentage and press **Set**; the **On** / **Off** button switches it fully on or off. A heater driven by the box's own automatic mode (dew-point difference or constant temperature) is set from the **Other** section.

## Adjustable outputs

A regulated output has an **On** / **Off** button and a voltage. Type the voltage and press **Set**; it is held within the range the device declares.

## Set

Sends the value in the field beside it — a duty, a voltage, or a number — to the device. For a device reached over Alpaca, a numeric channel is shown with exactly the range the device declares and no unit, because Alpaca does not say what the number means.

## Run

Runs a momentary action the device offers, such as cycling the power of every port.

## Readings

Voltage, current, power, temperatures and humidity as the device reports them. A dash means the device has no reading — for a temperature probe, that no probe is plugged in.

## Other

Every control the device's driver offers that has no place in the sections above, laid out as the driver defines it: mode selectors, setpoints, calibration, reboot, and so on. Nothing the driver offers is hidden. If a device is not recognised as a power device, all of its controls are listed here.
