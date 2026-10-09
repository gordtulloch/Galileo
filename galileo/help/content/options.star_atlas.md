<!-- order: 91 -->
# Star Atlas settings

The horizon of your observatory: the trees, buildings and hills that block the sky. Galileo shades them on the Star Atlas (turn on **Horizon** there) and, if you choose in Options › Planning, refuses to slew the mount into them.

Describe the horizon as a list of points. Each point is an *azimuth* (compass direction in degrees from north through east, 0–360) and the *altitude* (0–90°) of the obstruction in that direction — the sky below that altitude is blocked. Points are joined by straight lines and wrap through north. The horizon belongs to the Observatory selected in the top bar.

You can upload a file with one "azimuth altitude" pair per line, or edit the table directly.

## Upload horizon file

Loads a text file (.txt, .csv, .hzn or .dat) with one azimuth/altitude pair per line, replacing this Observatory's horizon. An invalid file is refused with an explanation.

## Clear

Deletes this Observatory's horizon, so the whole sky is considered open.

## Add Point

Adds a new row to the table at azimuth 0, altitude 0, ready to edit. Double-click a cell to change a value.

## Remove Selected

Removes the selected row(s) from the table. Press **Save Changes** to keep the change.

## Save Changes

Saves the table as it now stands. Rows are checked first: azimuth must be 0–360 and altitude 0–90, both numbers.
