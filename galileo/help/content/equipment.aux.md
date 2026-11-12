<!-- order: 38 -->
# Control Panel

The Control Panel page is Galileo's version of the INDI Control Panel in EKOS. Point it at an INDI server and it shows every device the server reports, with every property the driver offers, so you can inspect and change anything — including drivers that have no page of their own: dew heaters, power boxes, lens covers, USB hubs.

Set-up: enter the **Server** and **Port** (7624 unless you changed it), press **Connect**, then **Save** so the Pier reconnects to the same server next time.

**Connect** opens the server, not one device. Each device appears as a tab; inside it, a tab per property group (Main Control, Options, Image Settings and so on). Galileo never connects a device's hardware for you — use the **Connection** switch on that device's Main Control tab. The log at the bottom shows Galileo's own log.

This page is for INDI only. ASCOM Alpaca Switch devices are controlled from the Switches page.

## Device panel

Each tab holds the driver's own controls. A coloured dot beside a property shows the driver's state for it: grey idle, green OK, yellow busy, red alert. Buttons are switches — click to turn one on or off; some properties allow only one choice at a time. Read-only items cannot be changed. The panel refreshes every two seconds without losing the tab you have open or a value you are typing.

## Set

Sends the value typed in the field, or set on the slider, beside it to the device.
