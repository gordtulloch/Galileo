# Episode 2: Installation and Equipment Setup

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: Title card, then a desktop with the Galileo icon.

Welcome back. In this episode we install Galileo, get an INDI server or an Alpaca bridge running, install ASTAP and PHD 2, describe your observatory, and connect every kind of device Galileo supports. By the end you'll have taken your first frame.

If you already have Galileo installed, skip ahead to the section on observatories and piers.

## 2. Choosing how to install

> SCREEN: The GitHub Releases page.

There are two ways to install, and you only need one.

The first is a prebuilt installer. It's one download, and you don't need Python or Git. This is the right choice for most people. To update, you download the newer installer and run it over the old one.

The second is installing from source with a small script. It copies the project to your computer, sets up its own Python environment, and checks for updates every time you start it. This suits developers, testers who want the very latest changes, and platforms without a prebuilt installer.

> PAUSE: 5

## 3. Prebuilt installers

> SCREEN: Highlight each download on the Releases page in turn.

On the Releases page you'll find an installer for 64-bit Windows 10 and 11, a disk image for Apple Silicon Macs, an AppImage for Linux on Intel or AMD processors, and an AppImage for 64-bit ARM, which is the one for a Raspberry Pi 5. There is no prebuilt installer for Intel Macs, so use the source script there.

> PAUSE: 8

On Windows, double-click the installer and follow the wizard. Because the installer isn't code-signed yet, Windows may say it protected your PC. Choose More info, then Run anyway.

> SCREEN: Windows installer wizard.

> PAUSE: 8

On a Mac, open the disk image and drag Galileo to Applications. Until the builds are notarised, macOS may say the developer cannot be verified. Right-click Galileo in Applications, choose Open, and confirm. You only do that once.

On Linux, make the AppImage executable and run it. If it won't start, your system may be missing the FUSE 2 library, which you can install with your package manager. A Raspberry Pi needs a 64-bit operating system, such as Raspberry Pi OS Bookworm 64-bit.

> SCREEN: Terminal showing chmod and launch of the AppImage.

> PAUSE: 8

Plugins are not bundled with any installer. You add them from inside Galileo.

## 4. Installing from source

> SCREEN: The wiki Installation article, scrolled to the one-file installers.

For a source install, there's a one-file installer for each system. On Windows you download a batch file and double-click it. It finds or installs Git and Python 3.11, downloads Galileo into your user folder, and puts a shortcut on your desktop. No administrator rights are needed.

On a Mac you download a shell script and run it in Terminal. It offers to install the developer command line tools, Homebrew and Python if you don't have them, and leaves an application on your desktop.

On Debian, Ubuntu and Raspberry Pi OS there's a Linux script. It uses your package manager for system packages, which needs your password, and installs everything else into your home folder.

> PAUSE: 8

You can also do it by hand: clone the repository, create a virtual environment with Python 3.11 or later, and install the requirements. The first install downloads a good number of scientific libraries, so give it a few minutes.

## 5. First start

> SCREEN: Launch Galileo. Let the splash screen play in full.

When Galileo starts, a splash screen lists what it's doing: opening the database, loading plugins and building each screen. The database is created on first launch. There's nothing to configure beforehand.

> PAUSE: 9

## 6. Setting up an INDI server

> SCREEN: Diagram: telescope devices plugged into a Raspberry Pi running indiserver; Galileo on a laptop.

Galileo controls hardware through INDI or Alpaca, so you need at least one of them running.

INDI does not run natively on Windows. If your equipment has INDI drivers, put it on a Raspberry Pi or a small Linux computer at the telescope, and let Galileo talk to it over the network.

The easiest way to get there is a ready-made image. StellarMate is a commercial system, sold as software and as an appliance. Astroberry is a free, community-maintained image. Both include INDI and a web page for starting your drivers.

> PAUSE: 6

If you'd rather build it yourself, on Ubuntu-based systems the INDI project provides a package archive. Install the full set of drivers, or just the ones you need to save space. Then either start the INDI server from the command line, naming your drivers, or use INDI Web Manager, which runs as a service and saves driver profiles. On macOS you can install INDI with Homebrew or MacPorts.

> SCREEN: INDI Web Manager with a driver profile running.

> PAUSE: 9

INDI normally listens on port 7624. Remember the address of the computer it's on.

## 7. Using ASCOM Alpaca

> SCREEN: ASCOM Remote configuration page in a browser.

Use Alpaca when your device already speaks it, as a Seestar does, or when it only has a Windows ASCOM driver.

For the Windows driver case, you need three things on the Windows computer. First, the ASCOM Platform. Second, the manufacturer's driver for your device, which you should check works on its own before going further. Third, ASCOM Remote, which publishes those drivers on your network.

In ASCOM Remote, add each device, note its type and device number, check the address and port, and allow it through the Windows firewall on private networks.

> PAUSE: 11

To check the bridge, open its setup page from another computer on the network. If that page loads, the bridge is reachable. If device scanning later finds nothing, remember that Alpaca's automatic discovery only works within one network segment, so type the address in directly.

## 8. Installing ASTAP for plate solving

> SCREEN: The ASTAP page at hnsky.org, showing the downloads.

Two companion programs are worth installing now. The first is ASTAP, which does plate solving: it works out where your telescope is pointing from the stars in a picture. It's free, it runs on your own computer, and it needs no internet once installed. Install it on the same computer as Galileo.

You need two things from its website, at h n sky dot org: the program, and a star database. The program alone can't solve anything.

> PAUSE: 5

On Windows, download the setup program and run it. Windows may warn about an unknown publisher. Choose More info, then Run anyway. Then download and run the star database installer the same way. Keep the default folder, in Program Files.

> SCREEN: Run the ASTAP installer, then the database installer.

> PAUSE: 8

On a Mac, there are separate packages for Apple silicon and for Intel, so take the one that matches. macOS may block it until you allow it under System Settings, Privacy and Security. The ASTAP page also gives a one-time signing command for Apple silicon, and you should run it exactly as shown there.

> SCREEN: The macOS downloads and the signing command on the ASTAP page.

> PAUSE: 5

On Linux, download the Debian package for your processor. There's one for ordinary Intel and AMD computers, and one for 64-bit ARM, which is what a Raspberry Pi 5 uses. Install it with apt, giving the path to the downloaded file, then install a database package the same way.

> SCREEN: Terminal: sudo apt install ./astap package, then the database.

> PAUSE: 8

Which database? You only need one. D 50 is a good choice for most telescopes. The larger D 80 helps with very small fields of view and takes more disk space. The smaller ones save space for fields of about half a degree or more. For very wide camera lenses, check the ASTAP page for its wide-field options.

> PAUSE: 4

Before involving Galileo, open ASTAP, load one of your own images or any star field, and press solve. If it works there, you know the program and database are good. Galileo looks for ASTAP in its usual install folders and on your system path. If you put it somewhere else, set the location under Options, Solve.

> SCREEN: Solve an image in ASTAP, then show the ASTAP executable setting in Galileo.

> PAUSE: 10

## 9. Installing PHD 2 for guiding

> SCREEN: The downloads page at openphdguiding.org.

The second program is PHD 2, which does the autoguiding. Galileo controls it over the network, so PHD 2 can run on the same computer as Galileo, or on the computer at the telescope. You only need it if you have a guide camera.

On Windows, download the installer from open P H D guiding dot org and run it. You can install a newer version over an older one. Be aware that uninstalling removes your profiles and settings.

> PAUSE: 6

On a Mac, the downloads are zip files, with one for macOS Sonoma and newer, and another for Ventura and older. Unzip it and move PHD 2 to Applications.

> PAUSE: 4

On Ubuntu and systems based on it, the project's downloads page points to packages on Launchpad. Add that package source, update, and install P H D 2. On other Linux systems the project provides instructions for building from source. If you use StellarMate or Astroberry, check whether PHD 2 is already there before installing anything.

> SCREEN: Terminal: sudo add-apt-repository ppa:pch/phd2, sudo apt update, sudo apt install phd2.

> PAUSE: 10

Now set it up. Start PHD 2 and use its profile wizard to choose your guide camera and mount, and to enter the guide scope's focal length. Then, in the Tools menu, make sure Enable Server is ticked. That's how Galileo talks to it, normally on port 4400. Allow it through your firewall if asked, particularly if PHD 2 and Galileo are on different computers.

> SCREEN: Profile wizard, then Tools menu with Enable Server ticked.

> PAUSE: 13

We'll connect Galileo to PHD 2, calibrate and guide in episode four.

## 10. Observatory and Pier

> SCREEN: Galileo, top bar. Observatory drop-down, New Observatory.

Now into Galileo. Do this step first, because everything you save about your equipment is stored under the selected Pier.

Open the Observatory drop-down in the top bar and choose New Observatory. Give it a name. Enter the latitude and longitude in decimal degrees, with north and east positive, and be accurate, because the sky atlas, planning, twilight times and your horizon all depend on it. Enter the time zone, for example America, Toronto. Address and owner are optional.

> SCREEN: Fill in the dialog slowly and click OK.

> PAUSE: 13

Then open the Pier drop-down, choose New Pier, and name it. The pencil buttons edit these later, and the bin buttons delete them.

> PAUSE: 6

## 11. The connection row

> SCREEN: Equipment, Camera page. Highlight Driver, Server, Port, Scan.

Open Equipment. There's a page for Camera, Mount, Filter Wheel, Focuser, Rotator, Switches, Flat Panel, Safety, Dome, a Control Panel and Optics. The device pages share the same connection row, so learn it once.

Driver chooses Alpaca or INDI. Server is the name or network address of the computer running the device or the INDI server. Port is filled with the usual value when you change driver: 7624 for INDI, and 32323 for Alpaca. Alpaca has no single standard port, so use what your device documents. The ASCOM simulators, for instance, commonly use 11111.

> PAUSE: 6

One rule catches people out. Galileo refuses the address localhost, and the numeric loopback address, even when the server is on the same computer. Use the computer's real name or its address on your network. The reason is that a saved address has to mean the same computer from every Galileo installation that shares it.

Then press Scan. Galileo asks the server what it offers and fills the Device list. Choose your device, press Connect, and press Save. Nothing is remembered until you press Save.

> SCREEN: Perform Scan, choose a camera, Connect, Save.

> PAUSE: 11

If Scan finds nothing, check the address and port, check the server is running, check your firewall, and look in View Log, which will name the exact error.

## 12. Camera

> SCREEN: Camera page after connecting.

On the Camera page, press Download Info to read the pixel size and sensor dimensions from the camera. If your driver doesn't report them, type them in from the data sheet. These matter: with the focal length they set your image scale, which plate solving and framing rely on.

For a one-shot colour camera, set the Bayer pattern. Maximum well depth, also from the data sheet, lets the Flats Assistant work out flat exposures. Default gain and offset are what the Imaging screen starts with whenever you pick this camera.

> SCREEN: Highlight each field as it is mentioned.

> PAUSE: 11

If your Pier has a second camera on the same connection, such as the wide and telephoto cameras of a Seestar, press the plus button to add another panel.

## 13. Mount

> SCREEN: Mount page, connected, readouts updating.

The Mount page is split into status on the left and control on the right. You can see right ascension and declination, altitude and azimuth, sidereal time, time to the meridian, side of pier, tracking and park state. Check the site latitude and longitude the mount reports, because its pointing depends on them.

> PAUSE: 8

On the right you can type coordinates and slew, set the tracking rate to sidereal, lunar, solar or King, and move the mount with a direction pad that includes diagonals. Hold a button to move, release to stop. There are nine speeds. If a direction moves the wrong way for your optics, tick the reversed options.

> SCREEN: Hold an arrow, release, change the rate.

> PAUSE: 9

Below that are Park, Unpark, Home, and where the driver supports them, setting the park and home positions. Home is the mount's mechanical reference, and it is not the same as park.

Then the safety settings, which are saved per Pier and worth your time. Flip if hour angle greater than makes Galileo flip a tracking mount a set amount past the meridian. Altitude limits stop the mount if it points too low or too high. The hour angle limit stops it tracking too far past the meridian. These limits apply to every screen and to sessions. Before you trust the automatic flip, watch one in daylight or stand beside the mount, and check your cables clear.

> SCREEN: Enable altitude limits and show the flip setting.

> PAUSE: 11

## 14. Filter wheel, focuser and rotator

> SCREEN: Filter Wheel page.

The Filter Wheel page shows the current filter and the filter names read from the wheel. Pick a filter and press Change to move it. The names come from the wheel's own configuration, and they show up later in Imaging, in sessions and in the Library.

> PAUSE: 6

> SCREEN: Focuser page.

The Focuser page shows position, range, temperature and whether it's moving. Type a position and press Move. Most focusers are absolute, meaning they know where they are. A simple motor that can only be run for a number of milliseconds is a pulse focuser, supported over INDI. For those, move to mid travel by hand and press Reset to middle, and Galileo keeps track of the position from then on.

Set your travel limits. Move to each safe end and press Set Min and Set Max, and Galileo will never command a move beyond them. Some focusers also offer their own temperature compensation, which you can switch here.

> SCREEN: Press Set Min and Set Max.

> PAUSE: 9

> SCREEN: Rotator page.

The Rotator page turns the camera to an angle, sets zero, reverses direction and sets backlash. It can also derotate continuously, which cancels the field rotation you get on an altitude-azimuth mount.

> PAUSE: 6

## 15. Switches and power boxes

> SCREEN: Equipment, Switches page with a connected power box.

The Switches page controls power boxes and relay boards. You get On and Off buttons for each switchable port, percentage settings for dew heaters, voltage for adjustable outputs, and readings such as supply voltage, current and temperature.

Tick Show on imaging next to a port or heater, and it appears in a More menu on the Imaging screen, so you can warm a lens without leaving your picture.

> PAUSE: 9

INDI boxes that follow INDI's standard power interface need nothing extra, and Alpaca switch devices work too. Wanderer Astro boxes, Kasa smart plugs, SwitchBot buttons and network relay boards are added by plugins, which we cover in episode six. Support for several specific power boxes was built from the driver source code and has not yet been tried on real hardware, so test with something harmless plugged in.

## 16. Flat panel and dome

> SCREEN: Flat Panel page.

A flat panel or flip-flat gets Park and Unpark for the cover, light on and off, and brightness. The Flats Assistant uses it automatically.

> PAUSE: 5

> SCREEN: Dome page with Observatory Status box.

The Dome page controls a dome or a roll-off roof: open, close, park and abort. For a rotating dome, turn on slaving and the dome follows the mount while it's tracking. Leave it off if separate slaving software or hardware already does that job. You can also tick the option to open the dome when a session starts and close and park it when the session ends. Before closing, every telescope under the roof is parked and confirmed, and if that can't be done, the roof is left open.

An Observatory Status box sums up the dome and the weather and tells you whether the observatory is ready.

> PAUSE: 9

## 17. Safety: weather and safety monitors

> SCREEN: Equipment, Safety page, measures table with thresholds.

The Safety page is where you tell Galileo what counts as bad weather. Connect a weather station, a safety monitor that simply says safe or unsafe, or several of each, one per tab.

These belong to the Observatory, so you set them up once and every Pier uses them. For each measure, such as wind, humidity, cloud or rain, tick whether it counts, choose how it's compared, and set the threshold. A banner shows safe or unsafe, with the reasons.

> SCREEN: Tick wind speed, set a threshold, show the banner change.

> PAUSE: 13

When conditions turn unsafe, Galileo stops what it's doing, parks your mounts and closes the roof once they confirm they're parked. A banner stays until conditions have been safe for a while and you acknowledge it. Episode six explains in detail. Please test it before you rely on it.

## 18. The Control Panel

> SCREEN: Control Panel page showing INDI device tabs.

For anything that has no page of its own, there's the Control Panel, for INDI only. Enter the server, connect, and every device appears as a tab with all of its driver properties, much like the INDI control panel in other software. It's also the best place to check what a driver really offers.

> PAUSE: 8

## 19. Optics: tying it together

> SCREEN: Equipment, Optics page.

Last, and important, the Optics page. Press plus to add an optical tube. Name it, enter focal length, aperture and design. Then press the plus beside Associated and attach the camera, filter wheel, focuser and rotator that belong to that telescope. Only devices you've already saved appear in the list. Press Save.

> SCREEN: Build a tube and associate devices.

> PAUSE: 16

This is how Galileo knows which camera and focuser go together, what your field of view is, and which filters to offer.

## 20. Connecting automatically, and your first frame

> SCREEN: Switch Pier to show the splash with connection results.

Saved cameras and focusers connect by themselves when you select a Pier and at start-up. The Connect button in the top bar connects everything else on that Pier.

Now set up the Library folders under Options, Library, or accept the defaults in your home folder. Open Imaging, choose a short exposure, and press Capture.

> SCREEN: Imaging screen, Capture, frame appears with histogram.

> PAUSE: 11

There's your first frame, with its statistics and histogram.

## 21. Practising with simulators

> SCREEN: ASCOM Alpaca simulators and the INDI simulator drivers running; Galileo scanning them.

If your equipment isn't here, or you'd rather learn without risk, use simulators. INDI includes simulated camera, telescope, focuser and filter wheel drivers, which you can start from INDI Web Manager or the command line. The ASCOM Alpaca Simulators provide the same kind of thing over Alpaca. Connect to them exactly as you would to real hardware, using their computer's name and port.

> PAUSE: 16

Simulators are the right place to learn what a button does, build your first session and try the safety settings. They won't teach you about cable snags or focus drift, so go on to real hardware carefully.

## 22. Several telescopes, and several cameras

> SCREEN: Add a second optical tube and a second Pier.

Some setups have two telescopes on one mount. Add a second optical tube on the Optics page, with its own camera. You then choose Optics and Camera in the top bar, and the screens follow your choice.

> PAUSE: 13

A second mount is a second Pier. Create it, select it, and set up its equipment. Each Pier keeps its own connections when you switch to another, so you can connect them all and leave them working. Switching shows a progress screen listing each device as it connects.

> PAUSE: 16

Remember that Focus and Solve settings are per Pier, the horizon belongs to the Observatory, and Imaging, Planning, Library and plugin settings apply everywhere.

## 23. If a device will not connect

> SCREEN: View Log showing a connection error.

Work from the cable inwards. Is the device powered? Does it work with its maker's tool, or in the INDI control panel? Is the server running? Can another computer reach it? Is the port right? Try a numeric network address in place of a name.

> PAUSE: 9

On Linux, a camera that's detected but won't open often needs permission rules installed with its driver. USB hubs and long cables cause a surprising number of dropouts, as does a power supply that sags when the mount slews and the cooler runs at once.

> PAUSE: 9

If automatic connection fails, Galileo shows a notice with the reason, and the log has the detail. A saved address marked in red is one using localhost, which needs replacing.

## 24. Smart telescopes

> SCREEN: A Seestar and the Alpaca connection settings.

Smart telescopes deserve a mention, because many people will start with one. A smart telescope that offers Alpaca appears to Galileo as ordinary devices: a mount, one or more cameras, a focuser and a filter wheel. Use the telescope's name or address, with the Alpaca port its documentation gives, commonly 32323 for a Seestar. Scan on each equipment page, connect and save.

> PAUSE: 9

A model with wide and telephoto cameras gets two camera panels and two optical tubes. For darks, the Seestar's own dark filter does the job of a cover. What a smart telescope exposes depends on its firmware, so if something is missing, check what the device actually reports before assuming Galileo has lost it.

## 25. A pre-flight checklist

> SCREEN: Checklist graphic, ticked off one line at a time.

Before your first night, go down this list. Observatory latitude, longitude and time zone are correct. Each device connects and is saved. Pixel size and focal length are entered. Your optical tube has its devices associated. Mount limits are set. Focuser travel limits are set. The Library repository is on a drive with plenty of space. The computer is set not to sleep. And its clock is right, because pointing depends on time.

> PAUSE: 23

## 26. A few settings worth knowing, and wrap-up

> SCREEN: Options, Equipment, then Options, Notifications.

Under Options, Equipment, you can turn on the watchdog, which parks the mount, closes the dome and alerts you if Galileo stops responding. Under Options, Notifications, set up phone alerts through the free ntfy app, with e-mail as a backup, and press Send test alert to prove it works.

> PAUSE: 9

That's installation and equipment. In the next episode we put the telescope to work, finding targets in the Star Atlas and planning the night. Clear skies.

> PAUSE: 6
