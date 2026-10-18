<!-- order: 95 -->
# Solve settings

How Galileo runs the plate solver on the current Pier. Plate solving works out exactly where an image is pointing by matching its stars against a catalog. Galileo can use ASTAP, a local astrometry.net, the nova.astrometry.net web service, or ESA's tetra3. These are saved per Pier; press **Save** to keep them. They apply to solves from the Solve screen, the Imaging screen's Annotate, and sequences.

## Solver

Which solver Galileo uses by default: **ASTAP** (local, fast, needs its star database), **astrometry.net (local solve-field)** (local, needs the program and its index files; mainly Linux and macOS) or **nova.astrometry.net (web)** (needs internet and an API key; the frame is uploaded, and it is slower). **tetra3 (ESA, local)** (fast and offline, run inside Galileo; needs a star-pattern database matching your field of view (the bundled one is for 10–30° fields); it ignores the position hint and the search radius and relies on the field-of-view hint instead). The Solve screen's *Solver Mode* can override it for a single run.

## ASTAP executable

The path to the ASTAP program. Leave blank to have Galileo find it on your PATH or in its usual install folder. Set it if ASTAP is somewhere unusual or you have more than one version.

## Browse

Choose the ASTAP program with a file dialog.

## solve-field executable

The path to astrometry.net's `solve-field` program. Leave blank to find it on your PATH. Used only when the solver above is the local astrometry.net.

## tetra3 database

The path to a tetra3 star-pattern database (a `.npz` file) built for your field of view. Leave blank to use the database that comes with tetra3. Used only when the solver above is tetra3; tetra3 comes with Galileo. Its bundled database covers fields of 10–30° only, so for a narrower field build one for your field of view (see the tetra3 repository) and set it here.

## Generate for

Which Piers **Generate tetra3 databases** builds for: **Current Pier**, or **All Piers in all Observatories**. A Pier's database is sized to the field of view its optical tubes and cameras give (focal length, pixel size and sensor width); Piers whose fields work out the same share one. A Pier with several tube-and-camera combinations gets one database covering the whole range, and a Pier whose optics are incomplete is skipped and listed.

## Generate tetra3 databases

Builds the tetra3 star databases for the Piers chosen above and selects each one as its Pier's **tetra3 database**. It asks you to confirm first, listing what will be built. The first build downloads a star catalogue (about 51 MB for fields of 3° and wider, about 354 MB for narrower ones); it is kept for later builds. Building runs in the background and a narrow field can take hours, but Galileo stays usable. A database that already exists is reused rather than rebuilt.

## Cancel build

Stops the build in progress. Databases that were already finished are kept and selected; the one being built is discarded.

## nova.astrometry.net API key

Your personal key from your profile on nova.astrometry.net. Used only when the solver above is the web service; it is stored with the Pier's other settings.

## Field-of-view hint

How wide a field the solver should expect, in degrees. Leave at **Auto (from optical train)** to have Galileo work it out from the selected optics' focal length and the camera's pixel size; set a number to override it.

## Search radius

How far from the hinted position, in degrees, the solver searches. A small radius solves quickly when you know roughly where you are pointing; a large one finds the answer when you do not. 

## Downsample

Shrinks the image by this factor before solving. Faster, slightly less precise; **Off** solves at full resolution. Useful for large sensors, where a factor of 2 or 4 speeds the solve a great deal.
