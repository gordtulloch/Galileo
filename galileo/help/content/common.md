# Common controls

Controls that appear on many screens. A screen's own help takes precedence over
this page, so a screen can describe its version of a control in more detail.

## Driver

Which protocol Galileo uses to talk to this device: **Alpaca** (ASCOM Alpaca over HTTP, which is how Windows ASCOM drivers, ASCOM Remote and many smart telescopes such as the Seestar are reached) or **INDI** (an INDI server, typically running on a Raspberry Pi, StellarMate or similar).

Changing the driver also resets **Port** to that protocol's usual value.

## Server

The network name or IP address of the computer running the Alpaca bridge or INDI server, for example `seestar.local` or `192.168.1.50`. Leave it blank (or use `localhost`) when the server runs on this computer.

## Port

The TCP port of the Alpaca or INDI server. INDI almost always uses **7624**. Alpaca has no single standard: 32323 for a Seestar's bridge, 11111 for ASCOM Remote and the ASCOM simulators, or whatever your device's own documentation says. A wrong port shows up as a "connection refused" message in the log.

## Scan

Asks the server at **Server**:**Port** which devices of this type it offers and fills the **Device** list with them. The result (or the reason it failed) is written to the log pane at the bottom of the screen.

## Device

The specific device to use, chosen from the list filled by **Scan**. You can also type a device name directly if you know it. Choosing a device shows its driver details without connecting it.

## Connect

Connects to the selected **Device**. The button only affects this device; the **Connect** button in the top bar connects every device configured for the current Pier at once.

## Disconnect

Closes the connection to this device. The top-bar button disconnects every device on the current Pier.

## Remove

Removes this extra device panel. The saved settings for it are deleted the next time you press **Save**. The first (primary) panel cannot be removed.

## Add another device

Adds another panel for a second device of the same type that shares this page's Driver / Server / Port connection, for example a second focuser on the same INDI server.

## Save

Stores this page's settings under the Observatory and Pier currently selected in the top bar, so they are restored the next time you open Galileo or switch to that Pier. Nothing is remembered until you press Save. If no Pier exists yet, create one from the top bar first.

## Driver info

The description string the driver reports about itself (its manufacturer and model, as far as the driver says). Shown once the device is selected or connected.

## Driver version

The version number the driver reports. Useful when reporting a problem or checking that a driver update took effect.

## Log

The most recent lines of Galileo's log, as they happen: connections, scan results, moves and errors. When something does not work, look here first; the full log is also written to a file in Galileo's log folder.

## Fit

Zooms the picture so the whole frame fits in its window.

## 1:1

Shows the frame at actual size — one image pixel per screen pixel. The best view for judging star shapes and noise.

## Zoom in

Enlarges the picture by 25%. The mouse wheel also zooms.

## Zoom out

Shrinks the picture by 20%.

## Help

Opens this help window on the current screen. **F1** does the same for the control that has focus. For help on any single control, press **Shift+F1** (or "Point at a control…" in this window) and click it. Hovering a control also shows a short description.
