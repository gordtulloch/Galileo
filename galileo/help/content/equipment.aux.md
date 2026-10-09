<!-- order: 38 -->
# Aux

The Aux page controls any other device that does not have a page of its own: dew heaters, power boxes, lens covers, USB hubs and so on. Unlike the other Equipment pages there is no fixed layout. Once an INDI device or an Alpaca Switch device is connected, Galileo builds a panel from whatever switches, numbers and text fields its driver offers, grouped into tabs the way the driver groups them.

Set-up: choose the **Driver**, **Server**, press **Scan**, pick the device, **Connect**, then **Save**.

## Device panel

Each tab holds the driver's own controls. A coloured dot beside a group shows the driver's state for it: grey idle, green OK, yellow busy, red alert (Alpaca devices always show grey). Buttons are switches — click to turn one on or off; some groups allow only one choice at a time. Read-only items cannot be changed.

## Set

Sends the value typed in the field, or set on the slider, beside it to the device.
