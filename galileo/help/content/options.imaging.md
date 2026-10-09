<!-- order: 93 -->
# Imaging settings

Settings for how the Imaging screen saves frames.

## Desired BITPIX

The pixel format frames are written in when you use Save Frame, Auto-Save to Library or Save Stack on the Imaging screen. **Auto (recommended)** picks the smallest format that holds each frame without losing data. A fixed choice — 8, 16 or 32-bit integer, or −32 floating point — writes every frame in that one format, for downstream software that expects it; values outside its range are clipped and floats are rounded to whole numbers. Galileo never writes 64-bit FITS, because ASTAP and Tenmon refuse it.

It does not affect frames taken for plate solving, which always use whichever format suits the solver. It applies at once.
