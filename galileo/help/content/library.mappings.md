<!-- order: 73 -->
# Mappings

Different cameras, telescopes and programs write the same thing differently into FITS headers — "ASI294MC", "ZWO ASI294MC Pro" and "asi294mc" may all be one camera, and the Library would treat them as three. Mappings let you say "wherever you see *this* value in this header field, treat it as *that*", so your catalog, sessions and file names stay consistent.

Each mapping is a row: pick the header **Card**, the **Current** value as it appears in your data, and the **Replace** value you want. Add rows, then press **Save** to apply them all. The three tick boxes at the bottom control what saving does.

## Add Mapping

Adds a new row at the end of the list.

## Card

Which FITS header field this mapping is about: TELESCOP (telescope), INSTRUME (camera or instrument), OBSERVER, NOTES, FILTER or OBJECT.

## Current

The value currently found in your files for that card. The list is filled from the Library, so you can pick one; you can also type a value.

## Replace

The value to use instead. A mapping to an empty "Current" applies to files where the card is blank.

## Apply mapping

The ✓ button on a row: applies just that mapping right away, after asking you to confirm. A progress bar shows the work.

## Delete mapping

The bin button on a row: removes the row. It does not undo a mapping that was already applied.

## Update FITS headers on disk

When ticked, the changes are also written into the headers of the actual FITS files on disk, not only the database. Leave unticked to change the Library only.

## Apply mappings to database

When ticked, the Library database records are updated to the new values.

## Reorganize repository folders

When ticked, files are moved to the right folder in the repository when the telescope or instrument changes (the folder structure is based on them).

## Save

Saves the mappings and applies them as set by the three tick boxes above. The Images and Sessions screens refresh afterwards.

## Revert

Discards edits you have not saved and reloads the stored mappings.
