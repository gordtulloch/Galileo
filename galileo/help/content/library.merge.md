<!-- order: 75 -->
# Merge Objects

The same object is often saved under different names — "M31", "M 31", "Andromeda Galaxy", "NGC 224". Merge Objects changes every file of one object name to another so they appear together. If the "To" name does not exist yet, it is created. Optionally the files on disk are renamed and moved, and their FITS headers updated, to match.

Enter the names, press **Preview Changes** to see exactly what would happen, then **Execute Merge**.

## From Object

The object name to change *from*. Every file with this name is changed.

## To Object

The object name to change *to*.

## Change/Move filenames on disk

When ticked (the default), the files themselves are renamed and moved to the new object's folder, and their FITS headers updated. Untick to change only the database.

## Preview Changes

Shows what a merge would do — how many files have each name — without changing anything.

## Execute Merge

Carries out the merge. The Images and Sessions screens refresh afterwards.

## Clear Fields

Clears both names and the results area.

## Results

Messages, previews and the outcome of the merge appear here.
