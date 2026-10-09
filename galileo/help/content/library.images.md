<!-- order: 71 -->
# Images

Images lists every file in the Library as a tree: a row for each object (or date, or filter) which expands to show its frames, with the type, date, exposure, filter, telescope, camera, sensor temperature, whether the file is held locally and in the cloud, and the file name.

**Double-click** a frame to open it in your FITS viewer (set the viewer in Options › Library; otherwise the system default is used). **Right-click** a frame or object for more actions.

## Regenerate

Rebuilds the Library database from the files already in your repository. It clears the current database, scans the repository, and records what it finds. It does *not* move or rename any file. Use it if the database and the files on disk have drifted apart. You are asked to confirm first.

## Load New

Imports new FITS (and XISF) files from your incoming folder: it converts XISF to FITS, creates the folder structure, and moves and renames each file according to its metadata. You are warned before it starts because it moves files.

## Download

Fetches images from a smart telescope (for example a Seestar) over the network and imports them. Sessions are updated afterwards.

## Search

Type part of an object's name and press Enter or this button to show only matching objects.

## Clear

Clears the search and shows everything again.

## Sort by

How the tree is organised: by **Object**, **Date** or **Filter**.

## Show

Which kinds of frame appear: **Light Frames Only** (the default), **All Frames** (including darks, flats and bias), or **Calibration Frames Only**.

## Show Deleted

Reveals frames you have deleted. Deleting only hides a frame: the file stays on disk, so it can be shown again here.

## Add Variable Star

Right-click menu: adds the object to your list of variable-star targets, used by the variable-star photometry tools. Not offered for darks, flats and bias.

## View

Right-click menu on a frame: opens it in the external viewer, as double-click does.

## Delete

Right-click menu on a frame: marks the frame as deleted and hides it. The file is kept on disk. You are asked to confirm unless you ticked "Do not ask again".
