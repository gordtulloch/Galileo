<!-- order: 72 -->
# Masters

Masters lists the master calibration frames (bias, dark, flat and flat-dark) in the Library. Select one to see its file, the session it was built from and how many of that session's frames are still on disk. You can open it, build it again or delete it.

Masters are made on the **Calibration** screen, or registered when you import master files.

## Type

Show all masters, or only one type.

## Refresh

Reads the list again from the Library.

## View

Opens the selected master in your FITS viewer (set under Options > Library). Double-clicking a row does the same. It is greyed out if the file is missing; the list then shows **(missing)** after the file name.

## Recreate

Stacks the selected master again from the frames of the session it was built from, after you confirm. The new file replaces the old one, and sessions that use this master go on using it. If stacking fails, the master's record is left as it was.

It is greyed out for an imported master, which has no source session, and when fewer than two of the source frames are still on disk. The reason is shown under the list.

## Delete

Permanently deletes the selected master's file and its Library entry, after you confirm, and removes it from the sessions that used it. The frames it was built from are not changed. You can make the master again with **Create masters** on the Calibration screen.
