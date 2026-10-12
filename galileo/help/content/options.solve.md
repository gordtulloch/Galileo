<!-- order: 95 -->
# Solve settings

How Galileo runs the plate solver on the current Pier. Plate solving works out exactly where an image is pointing by matching its stars against a catalog. Galileo can use ASTAP, a local astrometry.net, or the nova.astrometry.net web service. These are saved per Pier; press **Save** to keep them. They apply to solves from the Solve screen, the Imaging screen's Annotate, and sequences.

## Solver

Which solver Galileo uses by default: **ASTAP** (local, fast, needs its star database), **astrometry.net (local solve-field)** (local, needs the program and its index files; mainly Linux and macOS) or **nova.astrometry.net (web)** (needs internet and an API key; the frame is uploaded, and it is slower). The Solve screen's *Solver Mode* can override it for a single run.

## ASTAP executable

The path to the ASTAP program. Leave blank to have Galileo find it on your PATH or in its usual install folder. Set it if ASTAP is somewhere unusual or you have more than one version.

## Browse

Choose the ASTAP program with a file dialog.

## solve-field executable

The path to astrometry.net's `solve-field` program. Leave blank to find it on your PATH. Used only when the solver above is the local astrometry.net.

## nova.astrometry.net API key

Your personal key from your profile on nova.astrometry.net. Used only when the solver above is the web service; it is stored with the Pier's other settings.

## Field-of-view hint

How wide a field the solver should expect, in degrees. Leave at **Auto (from optical train)** to have Galileo work it out from the selected optics' focal length and the camera's pixel size; set a number to override it.

## Search radius

How far from the hinted position, in degrees, the solver searches. A small radius solves quickly when you know roughly where you are pointing; a large one finds the answer when you do not. 

## Downsample

Shrinks the image by this factor before solving. Faster, slightly less precise; **Off** solves at full resolution. Useful for large sensors, where a factor of 2 or 4 speeds the solve a great deal.
