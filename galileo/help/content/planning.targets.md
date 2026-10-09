<!-- order: 14 -->
# Targets

Targets searches Galileo's catalogs of stars, galaxies, nebulae and clusters, and shows each result as a tile you can act on. Fill in any of the criteria on the left and press **Search**; blank or "Any" criteria are ignored.

Each result tile shows a thumbnail, the object's name and type, its brightness, size, constellation and coordinates, when it rises, transits and sets, and a small chart of its altitude through tonight. The chart and times need the Observatory's latitude and longitude (top bar). Click the thumbnail for a full-size view.

## Search Criteria

The filters used by **Search**.

## Object name

Search by name, such as M31 or NGC 7000. When a name is entered the search ignores the other criteria and looks the name up (also online, if it is not in the bundled catalog).

## Object type

Only objects of this kind: galaxy, nebula, cluster and so on. **Any** does not filter by type.

## Constellation

Only objects inside this IAU constellation.

## Catalog

Only objects in the ticked catalogs (Messier, Caldwell, NGC). With none ticked, every catalog is searched.

## Max magnitude

Only objects at least this bright. Magnitude gets *larger* for fainter objects, so 10 excludes anything dimmer than 10th magnitude. The default of 99 means no limit.

## Min size

Only objects at least this large on the sky, in arcminutes. Useful to match your field of view.

## Max size

Only objects no larger than this, in arcminutes. **No max** means no limit.

## Visible tonight

Only objects that are up tonight at your observatory, using the next three criteria. Needs the Observatory's latitude and longitude; without them this is ignored and a message says so.

## Reach an altitude of

The altitude, in degrees, an object must reach tonight to count as visible. Used only when **Visible tonight** is ticked.

## for at least

How long, in hours, the object must stay above that altitude *continuously*. **Any moment** needs just a single moment above it.

## Min. Moon separation

Excludes objects closer to the Moon than this many degrees at local midnight tonight. **No minimum** turns it off. Needs the Observatory's latitude and longitude.

## Search

Runs the search and fills the list. A message shows how many objects were found.

## Results

One tile per object found. Use the buttons on the right of a tile: **Select**, **Slew To** or **Add to Session**.

## Select

Makes this the Pier's current object: captured frames are named after it and the Solve screen's Slew to Target slews to it. It is also added to the target list.

## Slew To

Immediately slews the connected mount to this object. Needs a connected mount and the Observatory's location set.

## Add to Session

Creates a new session on Planning › Sessions that already contains a Target block for this object.
