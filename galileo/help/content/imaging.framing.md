<!-- order: 23 -->
# Framing Assistant

The Framing Assistant shows what your camera and telescope will see — a rectangle on a real sky survey image — so you can compose a shot before you take it, and define a mosaic of several panes when the target is bigger than one field. Open it from the Imaging screen's **Framing…** button, or from a session's Image block.

Set the target, adjust the rotation and the mosaic grid, and press **OK** to apply it.

## Name

The target's name, as it will be recorded.

## RA

The target's right ascension in degrees (0–360).

## Dec

The target's declination in degrees (−90 to +90).

## Rotation

The camera's rotation on the sky in degrees. It is filled in from a connected rotator, or the last plate solve, when either is known. With a rotator connected, **OK** turns the rotator to this angle. With no rotator, a rotation other than 0 is captured as a mosaic of panes that covers the tilted field.

## Mosaic cols

The number of panes across in a mosaic. 1 is a single frame.

## Mosaic rows

The number of panes down in a mosaic. 1 is a single frame.

## Overlap

How much neighbouring panes overlap, as a percentage. Overlap lets the panes be stitched together later; 10–20% is common. Shared with a session's Image block Framing control.

## Show mosaic overlay

Preview only: hides the pane grid and draws just a single frame rectangle. It does not change what is captured — a covering mosaic is still used whenever one is needed.

## Determine Rotation

Plate-solves the Imaging screen's current frame to read the camera's actual rotation. Only needed when the rotation is not already known from a rotator or an earlier solve. You need a captured frame first.

## Field of view

The size of one frame on the sky, in degrees, worked out from the optics and camera. Shown beneath the form; with a mosaic it also shows the footprint of the whole grid.
