<!-- order: 30 -->
# Camera

The Camera page connects Galileo to the camera (or cameras) that take your images and records what Galileo needs to know about its sensor. Imaging, Focus, Plate Solve and the sequencer all use the cameras connected here.

The first row (Driver, Server, Port, Scan) is shared by every camera panel. Below it each camera has its own panel with its own Device and Connect button. A one-shot-colour camera, a mono guide camera, or a telescope with two cameras (such as a Seestar's wide and tele cameras) each get a panel.

Typical set-up: choose the **Driver**, enter the **Server**, press **Scan**, pick the camera in **Device**, press **Connect**, check the sensor details below, then **Save**.

## Pixel size

The size of one sensor pixel, in micrometres. Together with the telescope's focal length it gives the image scale (arcseconds per pixel), which plate solving and framing depend on. **Download Info** fills it in for most cameras; otherwise copy it from the sensor's datasheet.

## Sensor width

The sensor's width in pixels.

## Sensor height

The sensor's height in pixels.

## Sensor name

The sensor model, read-only, when the driver reports it.

## Bayer pattern

The arrangement of the colour filters on a one-shot-colour sensor, read from the top-left 2×2 pixels (RGGB is the most common). The Imaging screen's Debayer option uses it to turn raw frames into colour. If colours look wrong (for example blue where red should be), try another pattern. It is ignored for a monochrome camera.

## Max well depth

The sensor's full-well capacity in electrons, from its datasheet. The Flats Assistant uses it to calculate a safe target brightness (ADU) for flat frames. Leave at — (0) if you do not know it.

## Download Info

Asks the connected camera for its pixel size and sensor dimensions and fills in those fields. Works for Alpaca/ASCOM cameras; for INDI it depends on what the driver reports.

## Add another device

Adds a panel for another camera sharing the same connection, for example a second wide-field camera on a smart telescope. The first panel is the *Primary Camera*.
