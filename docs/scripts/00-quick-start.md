# Quick Start: First Light in Ten Minutes

Target running time: 10 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: Telescope at dusk, then the Galileo window.

This is the short version. In ten minutes we'll go from nothing to a picture of a real object. Galileo is astrophotography software for Windows, macOS, Linux and Raspberry Pi. It's alpha software, so stay with your equipment while you try it.

> PAUSE: 8

## 2. Before you begin

> SCREEN: Checklist: computer, equipment, INDI server or Alpaca device, ASTAP.

You need a computer, and equipment that Galileo can reach through an INDI server or an ASCOM Alpaca device. INDI often runs on a Raspberry Pi at the telescope. Many smart telescopes speak Alpaca. Galileo doesn't use Windows ASCOM drivers directly. For plate solving, install ASTAP and one of its star databases.

> PAUSE: 12

## 3. Install

> SCREEN: Releases page, then the installer.

Download the installer for your system from the project's Releases page and run it. Windows or macOS may warn that it comes from an unidentified developer. The installation guide shows how to allow it. Start Galileo, and wait for the splash screen to finish.

> PAUSE: 18

## 4. Say where you are

> SCREEN: New Observatory dialog, then New Pier.

In the top bar, open Observatory and choose New Observatory. Enter a name, your latitude and longitude, with west negative, and your time zone. Then open Pier, choose New Pier, and name it. A Pier is one mount and what rides on it.

> PAUSE: 23

## 5. Connect

> SCREEN: Equipment, Camera: Driver, Server, Port, Scan, Connect, Save.

Open Equipment, Camera. Choose Alpaca or INDI. Enter the server's name or network address, not localhost, and check the port. Press Scan, pick your camera, press Connect, then Save. Press Download Info to fill in the sensor details.

> PAUSE: 30

Do the same for the mount, and for a focuser or filter wheel if you have them. Then on the Optics page, add your telescope, enter its focal length and aperture, attach the devices, and save.

> PAUSE: 30

On the Mount page, check the site location the mount reports, and set sensible altitude limits.

> PAUSE: 12

## 6. Pick a target

> SCREEN: Star Atlas, search, select, Goto.

Open the Star Atlas. Type a bright showpiece in Find, such as M 13 or M 42, whichever is up. Click it and choose it as your target. Make sure the mount is unparked and the way is clear, then press Goto. Watch the telescope.

> PAUSE: 30

If it's not sure what's up tonight, open Planning, What's Up Tonight, and let Galileo suggest.

## 7. Focus

> SCREEN: Focus screen, Loop, then Auto Focus.

Open Focus. Press Loop under Manual Focus and adjust until stars are small, then stop. With a motor focuser, press Auto Focus and let it find the best position. Without one, focus by hand while watching the star size number fall.

> PAUSE: 45

## 8. Centre it

> SCREEN: Solve screen, Slew to Target, Capture and Solve.

Open Solve. Choose Slew to Target and press Capture and Solve. Galileo works out from the stars where you're really pointing, corrects, and repeats until your object is centred.

> PAUSE: 45

## 9. Take the picture

> SCREEN: Imaging screen: exposure, quantity, Capture.

Open Imaging. Set an exposure of ten to thirty seconds, which is short enough to work without guiding on many setups. Press Capture. Zoom in and check your stars.

> PAUSE: 30

Happy? Tick Live Stack, set the quantity to twenty, and capture again. Watch the object grow out of the noise.

> SCREEN: Live stack building.

> PAUSE: 68

Press Save Stack to keep it. Your individual frames are already in the Library.

## 10. Pack up, and what next

> SCREEN: Park button; camera warming.

When you're done, warm the camera if you cooled it, and park the mount. Watch it park.

> PAUSE: 23

Every screen has help: hover over a control, press F 1, or click the question mark. The full series covers setup, planning, guiding and imaging, automation, safety, the Library, plugins and remote control. Join the community if you get stuck. Clear skies.

> PAUSE: 15
