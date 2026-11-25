# Episode 7: Using the Library

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: A messy folder of files with names like Light_001.fits, then the Library tree.

Welcome back. After a few seasons, most imagers have thousands of files in folders named by whatever mood they were in that night. The Library is Galileo's answer. It's built from AstroFiler, a tool by the same author, and it files your images, remembers what every one of them is, links your calibration frames to your lights, calibrates, stacks, finds duplicates and backs up to the cloud.

In this episode we'll set it up, import existing images, browse them, work with imaging sessions, tidy up inconsistent names, and back up.

## 2. How the Library works

> SCREEN: Diagram: incoming folder, repository, database.

There are three things to understand. The incoming folder is where new files wait to be imported. The repository is where the Library keeps your organised images, in a folder structure it creates. And the database records what each file is: object, filter, exposure, date, telescope and camera, read from its FITS header.

Galileo works in FITS. It can import XISF files, converting them to FITS as they come in.

> PAUSE: 9

Frames you capture in Galileo with Auto-Save to Library go straight in. Everything else arrives by importing or downloading.

## 3. Setting up

> SCREEN: Options, Library, General tab.

Open Options, Library. There are four tabs.

On General, set the Source Path, which is your incoming folder, and the Repository Path. Out of the box they're folders named REPOSITORY dot incoming and REPOSITORY in your home folder, so everything works without setup. If you have a large drive for astronomy data, point the repository there now, before you import anything.

> SCREEN: Browse to a repository folder and Save.

> PAUSE: 19

Compression is lossless FITS compression, off by default. Turn it on to save disk space, and leave verification on so every compressed file is checked against the original. Test that the other software you use can read compressed files before committing your whole archive.

> SCREEN: Show compression options.

> PAUSE: 12

You can choose the external viewer that opens when you double-click a frame. Save Modified Headers writes changes back into the files themselves, not only the database. And you can suppress delete warnings, though I wouldn't.

On the Calibration tab, set how many frames are needed before a master calibration frame is built. Anything from three to ten is sensible, and more is better.

Press Save.

> PAUSE: 12

## 4. Importing new images

> SCREEN: Library, Images. Copy files into the incoming folder, press Load New.

Open Library, Images. To import, copy your files into the incoming folder and press Load New. Galileo warns you first, because this moves files. It converts any XISF, reads each header, builds the folders, then moves and renames each file.

If you're nervous, copy rather than move your originals into the incoming folder the first time, so you can compare.

> SCREEN: Show progress, then the populated tree, then the repository folder structure.

> PAUSE: 35

## 5. Adopting an existing collection

> SCREEN: Highlight the Regenerate button.

If your files are already in the repository folder, use Regenerate. It clears the database, scans the repository, and records what it finds. It does not move or rename anything. This is also how AstroFiler users bring their collection across by rebuilding from headers, and how you recover if the database and the disk disagree. Afterwards, regenerate the imaging sessions too, which we'll see shortly.

Notice that Regenerate clears the catalog first, so anything recorded only in the database should be considered before you press it.

> PAUSE: 16

## 6. Downloading from smart and remote telescopes

> SCREEN: Options, Library, Smart Telescopes tab.

The Download button fetches files from other places and imports them. It works with smart telescopes on your network, such as a Seestar, a DWARF or a Celestron Origin, with the iTelescope remote observatory service, and with any SFTP server, such as a computer at a remote site.

Set accounts and addresses on the Smart Telescopes tab. Passwords are kept in your operating system's credential store, not in a settings file. For SFTP you can use a key file instead of a password, and for servers reached over the internet, turn on the option to connect only to hosts you already trust.

> PAUSE: 16

> SCREEN: Press Download on the Images screen and choose a source.

> PAUSE: 23

## 7. Browsing

> SCREEN: Images tree. Change Sort by and Show.

The Images view is a tree. Each object expands to show its frames, with type, date, exposure, filter, telescope, camera, sensor temperature, whether it's held locally and in the cloud, and the file name.

Sort by object, date or filter. Show light frames only, which is the default, calibration frames only, or everything. Search by object name, and press Clear to see it all again.

> SCREEN: Sort by date, then filter, then search for M 31.

> PAUSE: 28

Double-click a frame to open it in your viewer.

## 8. Deleting safely

> SCREEN: Shift-select several frames, right-click, Delete. Then tick Show Deleted.

Right-click gives you View and Delete. Select several with Shift or Control and delete them together.

Delete in the Library hides a frame. The file stays on disk. Show Deleted brings them back into view. That's forgiving, but remember it also means deleting here does not free disk space.

> PAUSE: 23

The right-click menu on a light frame also offers Add Variable Star, which marks the object for the variable-star plugin.

## 9. Frames on another computer

> SCREEN: Local column showing disk and computer icons.

If you use NodeConnect, a computer at the telescope can send its images to a main computer, called the Master, and optionally remove its local copies to save space. The catalog entry and thumbnail stay. The Local column then shows a computer icon, and double-clicking the frame, or choosing Retrieve, fetches it back over the encrypted link and checks it's exactly the same file. NodeConnect is an early feature; see episode nine.

> PAUSE: 12

## 10. Imaging sessions

> SCREEN: Library, Sessions tree.

Now the most useful part. Open Library, Sessions. Don't confuse these with Planning sessions. A Planning session is a list of instructions. A Library session is a record: the frames of one object, taken on one night, with one setup.

> PAUSE: 9

The Library builds these automatically, and links each light session to the bias, dark and flat sessions that can calibrate it. Flat darks, which are darks taken at your flats' exposure, are recognised and linked to their flats. A dark or flat dark links only when the exposure matches and the sensor temperature is within five degrees.

> SCREEN: Expand an object and point at the Resources column.

> PAUSE: 19

The Resources column tells you what calibration data each session has. On an object's row it summarises, for example three of four sessions having what they need. This is your to-do list. A session missing flats is a session you'll want to fix before the optical train changes.

Regenerate rebuilds sessions, either all of them or only for new files.

> SCREEN: Press Regenerate, choose New Only.

> PAUSE: 14

## 11. Checking out files

> SCREEN: Right-click a session, Check out. Show the dialog options.

If you process in PixInsight, Siril or something else, right-click a session and choose Check out. Choose a target folder and Galileo gathers the session's files and calibration there. By default it makes links, so no space is used and your originals aren't duplicated. You can copy instead, decompress, or take only the master frames. Select several light sessions to check them all out together.

> PAUSE: 28

On Windows, creating links can need particular permissions, so if it fails, use the copy option.

## 12. Master frames and calibration

> SCREEN: Diagram: darks combine into a master dark; flats into a master flat; applied to lights.

A master frame is many calibration frames combined into one clean one. The Library builds masters when there are enough frames, using the minimum you set earlier. View Master, on a calibration session, opens the result so you can inspect it. Look at your masters. A flat with a star trail in it, or a dark with a light leak, will damage everything it touches.

> SCREEN: Right-click a flat session, View Master.

> PAUSE: 21

To calibrate, right-click a light session and choose Calibrate. Galileo applies the matching master bias, dark and flat, and the flat's own dark master when there is one.

> SCREEN: Calibrate a session and show progress.

> PAUSE: 28

Your raw frames are your record. Keep them.

The same dark masters are used elsewhere too: the Subtract dark options on the Imaging, Focus and Solve screens look for a master with the same telescope, camera and binning, at nearly the same exposure.

## 13. Stacking

> SCREEN: Right-click a session, Stack. Show the result opening in a viewer.

Stack combines a session's lights and opens the result in your viewer, calibrating first if needed. It's a quick look at what a night produced. It is not meant to replace careful processing.

> PAUSE: 28

Stack photometric registers and averages without sigma clipping. Sigma clipping throws away unusual pixel values, which is great for removing satellite trails and bad for measuring the brightness of a star that really did change. Use this version for photometry.

Double-click a session's thumbnail to open its latest stack, and use Regenerate Thumbnail to refresh the picture. Copy Session ID puts the identifier on your clipboard.

> SCREEN: Show thumbnails in the tree.

> PAUSE: 12

## 14. Mappings

> SCREEN: Library, Mappings.

Different programs write the same thing differently. One camera might appear under three names, and the Library would treat them as three cameras, and your darks would fail to match your lights.

Mappings fix this. Each row says: for this header card, where the value is this, use that instead. Cards include telescope, instrument, observer, notes, filter and object. An empty current value fills in blanks.

> SCREEN: Add a mapping for INSTRUME.

> PAUSE: 23

Three tick boxes decide how far the change goes: update the database, rewrite the headers on disk, and reorganise the repository folders. If you're unsure, change only the database first. The tick on a row applies just that mapping, and Save applies them all. Revert discards unsaved edits. Removing a mapping does not undo what it already changed.

> PAUSE: 16

## 15. Merging objects

> SCREEN: Library, Merge Objects. Preview Changes.

M31, M space 31, NGC 224 and Andromeda Galaxy are one thing. Merge Objects combines names. Enter the From name and the To name, then press Preview Changes to see exactly which files would be affected. When you're satisfied, press Execute Merge. The option to rename and move files on disk is ticked by default, so untick it if you only want the catalog changed.

> SCREEN: Preview, then execute.

> PAUSE: 28

## 16. Duplicates

> SCREEN: Library, Dedup. Refresh Duplicates.

Dedup finds files with identical contents, however they're named, such as a card copied twice. Duplicates waste space and, worse, count the same photons twice in a stack. Press Refresh Duplicates, review the groups, then Delete Duplicate Files. It keeps one of each and asks you to confirm. Unlike hiding a frame, this removes files, so look before you agree.

> PAUSE: 28

## 17. Cloud backup

> SCREEN: Options, Library, Cloud Sync tab.

Your images represent many cold nights. Back them up.

The Library supports Google Cloud Storage. In Google's console, create a storage bucket, create a service account with the storage object administrator role, and download its key file. On the Cloud Sync tab, enter the bucket name and point to the key file. Treat that key like a password. Cloud storage costs money, so check Google's pricing for the amount of data you have.

> PAUSE: 19

Choose a sync profile. Complete Sync keeps everything in both places. Backup Only uploads and never downloads. On Demand downloads files when needed.

There is also an option to clean up local files once they're backed up, which deletes calibration files and uncalibrated lights from your computer. Master frames and stacked results are never deleted. Be very sure you trust your backup before turning that on.

> PAUSE: 12

> SCREEN: Library, Cloud screen. Press Analyze, then Sync.

On the Cloud screen, press Analyze first. It lists what's in the bucket and matches it to your catalog without moving anything. Then Sync moves files according to your profile. Frames held in the cloud show a cloud icon in the Images view. A first sync of a large collection can take a very long time on a home connection.

> PAUSE: 28

## 18. A worked example: from card to stack

> SCREEN: Perform each step as narrated.

Let's follow one night of data all the way through. Suppose you have a folder from a clear evening on the Veil Nebula: lights through two filters, darks, flats and bias frames.

Copy the whole folder into your incoming folder. Open Library, Images, and press Load New.

> PAUSE: 35

Once it finishes, set Show to All Frames and sort by date. Check that the lights are listed as lights, the flats as flats, and that the filter and exposure columns look right. If the object has an odd name, use Merge Objects now, before going further.

> PAUSE: 28

Now open Library, Sessions. Expand the object. You should see a light session for each filter, with resources showing which calibration is linked.

> SCREEN: Expand and examine resources.

> PAUSE: 28

If flats are missing, check the filter names match exactly between flats and lights. If darks are missing, compare exposure and sensor temperature. A mapping may be all it takes. Then regenerate the sessions.

> PAUSE: 19

When resources are complete, calibrate each light session, view the master flat, and stack. Finally, check out the sessions to your processing software for the real work.

> PAUSE: 35

## 19. Getting headers right at the source

> SCREEN: A FITS header viewer showing key cards.

The Library can only be as good as the headers. Galileo writes the object, optics, filter, gain, offset and frame type into what it captures, which is why the equipment pages and the Type and Object fields on the Imaging screen matter.

> PAUSE: 19

Files from other software vary. Import a small batch first, check how they were classified, and only then load the rest. A frame whose type or object is missing will end up filed somewhere you don't expect.

> PAUSE: 12

## 20. Space and backups

> SCREEN: Dashboard node health line showing disk space.

Image data grows fast. Keep an eye on the free space figure on the Dashboard. Compression helps. So does removing frames you'll never use, remembering that hiding one in the Library leaves the file on disk.

> PAUSE: 14

Consider two kinds of copy. A local backup to another drive restores quickly. A cloud copy survives fire and theft. Back up your database file as well as your images. The database holds your catalog, your observatories and your settings. If the worst happens, Regenerate can rebuild the image catalog from the files, but it can't invent your settings.

> PAUSE: 19

## 21. Common questions

> SCREEN: Question cards.

Can I move my repository? Plan it before you import, because the catalog records where files are. If you do move it, change the setting and regenerate.

Can I use my old AstroFiler database? Rebuild the catalog from your files with Regenerate, and then regenerate sessions.

> PAUSE: 12

Do I have to use the Library at all? No. Turn off Auto-Save to Library and use Save Frame. But then calibration linking, dark subtraction and history of what you've collected are no longer working for you.

Are there command line tools? Yes, the Library includes utilities for batch work, which suits people who like to script overnight jobs. See the project documentation.

> PAUSE: 14

## 22. Calibration planning

> SCREEN: Library Sessions, Calibration Frames Only view.

Think of your calibration frames as a small library of their own. For darks, pick the exposure lengths, gain, offset and temperature you use, and take a good set of each. They can serve for weeks if your camera is cooled to the same point. Refresh them now and then, and after any camera change.

> PAUSE: 19

Flats are tied to the optical train. Take them whenever the camera is rotated or removed, the focus changes substantially, or dust moves. Bias frames are quick and change slowly.

Browse with Calibration Frames Only to see what you have. If an uncooled camera's temperature wanders by more than five degrees, expect darks not to link.

> PAUSE: 19

## 23. When the catalog looks wrong

> SCREEN: A session with missing resources; Mappings; Regenerate.

If something looks wrong, work in this order. Check one file's header in your viewer, because the catalog can only repeat what's there. Fix naming with Mappings or Merge Objects. Regenerate sessions. Only if the database and disk truly disagree, regenerate the whole catalog. And look in View Log, which records what happened to each file during an import.

> PAUSE: 28

## 24. Habits that pay off, and wrap-up

> SCREEN: Slow pan down the Images tree.

A few habits make the Library work for you. Set your optics and camera details correctly, so headers are right from the start. Name targets through the catalog rather than typing variations. Take calibration frames before you change the optical train. Check the Resources column after each run. And back up.

That's the Library. Next time: plugins, and the marketplace where you get them. Clear skies.

> PAUSE: 12
