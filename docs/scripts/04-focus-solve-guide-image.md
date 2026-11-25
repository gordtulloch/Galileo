# Episode 4: Focusing, Solving, Guiding and Imaging

Target running time: 60 minutes. Lines beginning with `>` are production directions and are not narrated.

Parts: 1 Preparation, 2 Focusing, 3 Plate solving, 4 Polar alignment, 5 Guiding, 6 Imaging, 7 Calibration frames, 8 Putting it together, 9 Troubleshooting and good habits.

## Part 1: Preparation

> SCREEN: Telescope at dusk, then the Galileo window.

Welcome back. This is the hour where we make pictures. We'll focus the telescope, work out exactly where it's pointing, polar align the mount, set up guiding, and then capture light, dark and flat frames. Use the chapter markers to jump to what you need.

The order I'll follow is the order I'd suggest on a real night. Connect and cool. Polar align. Focus. Slew and centre. Guide. Image.

Polar alignment appears after plate solving in this video, because it uses plate solving, and you need to understand one before the other. On the night itself, do it early, and do a rough focus first so there are sharp enough stars to solve.

> PAUSE: 11

### Connect and check

> SCREEN: Top bar: choose Observatory, Pier, Optics, Camera. Press Connect.

Start at the top bar. Choose the Observatory, the Pier, the optics and the camera. These choices tell the Focus, Solve and Imaging screens which devices to use. Press Connect to bring up everything configured on the Pier.

> PAUSE: 19

If you have a cooled camera, open Imaging and find the Camera Cooling box. It shows the sensor temperature live, with cooler power if the camera reports it. Type a target temperature and tick Cooler on. Step down gradually rather than demanding a big drop at once, and pick a temperature your camera can hold with some power to spare, because your dark frames will need to match it.

> SCREEN: Set a target and tick Cooler on. Show the temperature falling.

> PAUSE: 19

Then pick a target in the Star Atlas, so it's the current object, and slew to somewhere with plenty of stars. If your mount has never been synced, don't worry yet. Plate solving will fix that.

> PAUSE: 11

## Part 2: Focusing

### The idea

> SCREEN: Focus screen, empty.

Open Focus. In a perfectly focused image, each star's light is concentrated into the smallest possible spot. As you move away from focus, the spot grows. Galileo measures that size as half-flux radius: the radius containing half of a star's light. Smaller is sharper.

If you plot half-flux radius against focuser position, you get a V shape. Autofocus samples points along the V, fits a curve, and moves to the bottom.

> SCREEN: Diagram of a V-curve with the minimum marked.

> PAUSE: 16

### The screen

> SCREEN: Highlight left panel, frame, statistics, V-curve, status line.

On the left are the focuser, camera and manual controls. On the right are the frame being measured, its star statistics, and the V-curve. The status line says what's happening.

The screen names the focuser belonging to your chosen optics, with its live position and temperature, and the camera from the top bar. Gain and offset start from the camera's defaults. Changing them here affects only focusing.

> PAUSE: 13

Choose an exposure long enough to show plenty of stars above the noise, but not so long that bright stars saturate. A saturated star's measured size stops responding to focus, which confuses everything.

### Rough focus by hand

> SCREEN: Manual Focus box. Press Loop.

Autofocus needs to start roughly in focus, because the sweep is centred on wherever the focuser is now. So first, focus by hand.

In the Manual Focus box, press Loop. Galileo takes one exposure after another and measures each. Move the focuser, either by typing a position and pressing Move, or with its hand controller, and watch the radius number. Chase it downwards. When stars are small and round, press the Manual Focus stop button.

> SCREEN: Loop running. Step the focuser until the stars sharpen.

> PAUSE: 54

The statistics line shows star count, median half-flux radius and an equivalent full width at half maximum. A value of minus one means no stars were found: lengthen the exposure, check the cover is off, and check you're not wildly out of focus.

### Setting up the sweep

> SCREEN: Highlight Step size, Points, Backlash, Exp.

Four settings control autofocus.

Step size is how far the focuser moves between samples. Points is how many samples, from three to forty-one, centred on where you are. Your total travel is roughly step size times one less than the number of points.

The sweep needs to reach clearly out of focus on both sides. If the step is too small, the curve is nearly flat and the fit is meaningless. If it's too large, most samples are blurred blobs and few are near the bottom. A good first try is to find the step that makes the stars visibly about three times larger at each end of the sweep.

> PAUSE: 13

Backlash is slack in the focuser's gears. If it's above zero, each move overshoots and comes back, so the gears always load from the same side. Set it to roughly the number of steps the focuser takes before the image starts to change after reversing direction. Zero turns it off.

And Exp is the exposure for each sample.

These are remembered, and sessions use them too. You can also set them per Pier under Options, Focus.

### Running autofocus

> SCREEN: Press Auto Focus. Let the whole run play, uncut or lightly sped up.

Press Auto Focus. The focuser moves to one end, takes an exposure, steps, takes another, and so on. Watch the frame, the progress bar, and the points appearing on the V-curve.

> PAUSE: 80

Blue points are measurements. The orange line is the fit, and the green marker is the best position it found. The focuser then moves there.

> SCREEN: Zoom on the finished curve.

> PAUSE: 16

A good result is a clear, symmetrical V with the marker at the bottom. A flat or ragged curve means something needs changing: the step size, the exposure, or the seeing is just bad tonight. If a point has very few stars and a suspiciously small radius, which is usually a hot pixel and not a sharp star, Galileo leaves it out of the fit and says so in the log. If it can't find a sensible minimum, it returns the focuser to where it started. Press stop at any time and it also goes back.

> PAUSE: 11

### Emergency focus

> SCREEN: Press Set Emergency, then move away, then Go to Emergency.

Once you have good focus, press Set Emergency. Galileo remembers that position, even across restarts. If a failed run, a bumped knob or a changed camera leaves you hopelessly out of focus, Go to Emergency brings you back to something close. Your focuser settings need to be saved on the Equipment page for this to be kept.

> PAUSE: 21

### Filter offsets

> SCREEN: Open Filter Offsets.

Filters focus at slightly different positions. Rather than running autofocus after every filter change, open Filter Offsets, choose a primary filter, and measure each other filter's best focus relative to it. From then on, when a session changes filter, Galileo moves the focuser by the stored amount.

> SCREEN: Measure offsets for three filters, sped up.

> PAUSE: 40

Offsets handle the filter. They don't handle temperature. As the night cools, your focus drifts, so watch the focuser temperature and the radius, and refocus when they move. An Autofocus block inside a session loop does this for you.

### Layout and darks

> SCREEN: Tick Subtract dark. Then tick Choose layout manually.

Subtract dark removes a matching dark master from the picture shown here, which tidies up hot pixels. The measurements always use the raw frame. Like Imaging and Solve, this screen switches to a portrait layout for tall frames, and you can override that with Choose layout manually.

> PAUSE: 16

## Part 3: Plate solving

### The idea

> SCREEN: A star field, then lines matching patterns to a catalog.

Plate solving matches the pattern of stars in your picture against a star catalog, and works out precisely where the centre of the frame is, how it's rotated, and its scale. With that, the telescope no longer has to be pointed accurately. It only has to be pointed well enough, and then corrected.

### Choosing a solver

> SCREEN: Options, Solve.

Under Options, Solve, choose your solver. The settings are saved for each Pier.

ASTAP is the usual choice: local, fast and offline. Install it and a star database.

Astrometry dot net can be installed locally with its index files, mainly on Linux and macOS.

Tetra3, from the European Space Agency, is built in and runs offline. Its bundled database covers fields from ten to thirty degrees, which is much wider than most telescopes, so press Generate tetra3 databases and Galileo builds one to suit your optics. The first build downloads a star catalog, and a narrow field can take hours, so do it in daylight.

Nova is the astrometry dot net web service. It needs an internet connection and your own key, and your frame is uploaded to it.

A plugin adds Skyshot, an experimental blind solver.

> PAUSE: 21

For ASTAP, you can set the program location, a field of view hint, the search radius, downsampling and extra command-line options. If ASTAP solves a picture by itself but not through Galileo, set downsample to automatic and clear the field of view hint.

> SCREEN: Highlight the ASTAP settings.

> PAUSE: 16

### Capture and solve

> SCREEN: Solve screen. Highlight controls, frame, results tabs.

Open Solve. On the left are the controls, the action to take, and the coordinates. On the right are the frame, a results tab and a polar alignment tab.

Under Plate Solve Capture Options, set the exposure, a few seconds usually, binning, gain and filter. Binning two by two makes stars brighter and files smaller, so solving is quicker. Leave the filter on Current to keep the wheel where it is.

> SCREEN: Set exposure and binning.

> PAUSE: 16

Then decide the Solver Action. Nothing just reports the answer and does not touch the mount, and it's the safe default. Sync tells the mount where it really is. Slew to Target moves to the current object, solves again, and repeats until the error is within your accuracy.

Press Capture and Solve. Start with Nothing.

> SCREEN: Capture and Solve with action Nothing.

> PAUSE: 32

You get the solved right ascension and declination, the error from the target, the image scale, the position angle and the field of view.

There are three more numbers worth knowing. R is the solved scale divided by the scale your optics predicted. It should be close to one. FL is the focal length implied by the solve, and the next is the focal ratio. If R is far from one, the focal length or pixel size on your Equipment pages is wrong, and now you know the right focal length.

> SCREEN: Circle R, FL and the focal ratio.

> PAUSE: 19

Check the solver mode buttons too. You can change solver for a run right here.

### Sync and centre

> SCREEN: Choose Sync, Capture and Solve. Then choose Slew to Target.

Now choose Sync and solve again. The mount's idea of its position now matches the sky. Then choose Slew to Target, set an accuracy, thirty arcseconds is fine for most framing, set a settle time so vibrations die away after each move, and press Capture and Solve.

> PAUSE: 54

Watch the error plot. Each attempt is a dot, and the ring is your accuracy. The dots walk in towards the centre until one lands inside, and you're framed.

### Results, auto-centre and load and slew

> SCREEN: Solution Results table. Press Save.

The results table lists every solve, including those from sessions and other screens, with success or failure and the offsets. You can save it to a spreadsheet file.

> PAUSE: 13

Auto-Centre repeats slew to target on a timer, every two minutes by default, to correct slow drift. It skips a pass while a session or an imaging capture is using the camera, and it's disabled while guiding, because moving the mount would wreck the guide.

> SCREEN: Tick Auto-Centre and show the cadence.

> PAUSE: 13

Load and Slew solves a picture you already have, then takes the telescope there. Choose from the Library, where you can sort and search your light frames, or any FITS file on disk. It's the way to return to last week's framing and add more data. Afterwards that position becomes the current object.

> SCREEN: Load and Slew, From the Library, pick a frame.

> PAUSE: 32

### When solving fails

If a solve fails, work through these. Are there stars? Look at the frame. Try a longer exposure or a clearer filter. Is it focused? Is a star database installed? Is the field of view right in your optics? And if the mount is badly wrong, widen the search radius or use a blind solver. The log gives the solver's actual reason.

> PAUSE: 13

## Part 4: Polar alignment

### Why it matters

> SCREEN: Diagram: mount axis offset from the celestial pole.

An equatorial mount tracks by turning about one axis. If that axis doesn't point at the celestial pole, stars drift and the field slowly rotates. Guiding can hide the drift but not the rotation. A few minutes spent here pays off all night.

### What you need

You need a camera, a mount, an Observatory with latitude and longitude, a level mount, and no session or solve already running. Keep away from the meridian, where the mount might flip in the middle of the measurement.

> SCREEN: Solve screen, Polar Alignment tab.

### Choosing how to start

> SCREEN: Highlight Slew from Zenith, Rotate, Direction, Refraction.

There's one decision to make first. With Slew from Zenith unticked, which is the default, nothing moves to begin with. Galileo solves where you're pointing now and measures from there. So point at a clear field away from the pole and the meridian before you start.

With it ticked, Galileo slews to the zenith, solves, syncs if the mount turns out not to have been there, and measures from the zenith. That suits a mount that has never been synced, but it moves a long way, and your focus may differ there.

> PAUSE: 13

Rotate is how far the mount turns in right ascension between measurements, fifteen degrees by default. More is more accurate, but needs more clear sky. Direction says which way, so choose the side with room. Refraction allows for the atmosphere, and is on by default.

### Running it

> SCREEN: Press Start Polar Alignment. Show the three measurement solves.

Press Start Polar Alignment. Galileo solves, turns the mount, solves, turns, and solves a third time. After each move it waits for the mount to stop, then pauses at least five seconds, so stars aren't trailed.

> PAUSE: 60

Three solutions are enough to work out where the axis really points.

### Making the adjustment

> SCREEN: The aiming view with circle and X. Show corrections in words.

Now you see the total error, the correction in words for altitude and for azimuth, and an aiming view. The circle is where your axis points now. The X is the celestial pole. Your job is to bring the X into the circle using the mount's altitude and azimuth adjusters. Not the hand controller. The mechanical adjusters.

Galileo keeps solving, so the picture updates as you turn. Make one small adjustment, wait for the next solve, and look.

> SCREEN: Turn adjusters; the error shrinks; the circle turns green.

> PAUSE: 60

The circle turns green within one arcminute. For most imaging, a few arcminutes is acceptable. Press End Alignment when you're done. Some solvers don't report the geometry needed for the picture; in that case follow the written corrections.

### From your phone

This routine can also be run from the MobileConnect app, and from the WebConnect browser interface, which is ideal when the computer is indoors and you're out at the mount. Those are covered in episodes nine and ten.

Afterwards, solve and sync once more, and recheck focus.

> PAUSE: 13

## Part 5: Guiding

### How Galileo guides

> SCREEN: Diagram: guide camera to PHD2 to mount; Galileo connected to PHD2.

Galileo does not guide by itself. PHD 2 does that, and does it very well. Galileo connects to PHD 2 over the network, controls it, and shows you what it's doing.

So set up PHD 2 first. Create a profile with your guide camera and mount, and in its Tools menu, enable the server. PHD 2 can run on the same computer or another one.

> SCREEN: PHD2 with Enable Server ticked.

> PAUSE: 19

### Connecting

> SCREEN: Guiding screen. Enter host and port, Connect, Save.

Open Guiding. Enter the PHD 2 host, using a real name or address rather than localhost, and the port, 4400 for the first copy of PHD 2. Press Connect, then Save, so this Pier remembers it. Press Connect Equipment to have PHD 2 connect its own camera and mount.

> PAUSE: 27

Under Optic, choose the train you guide through, and Galileo shows its focal length, aperture, focal ratio, guide scale in arcseconds per pixel, and guide field of view.

### Choosing a star

> SCREEN: Press Loop. Show the Star view, then Full frame. Click a star.

Press Loop. PHD 2 takes repeating exposures without guiding. Choose an exposure with the Exp list, usually one to three seconds. Shorter reacts faster, longer averages out poor seeing.

You can press Auto Star and let PHD 2 choose. Or switch the picture to Full frame to see all the candidates and click the one you want. Clicking near it is enough, because PHD 2 picks the best star in a small box around your click. The full frame needs PHD 2 on the same computer as Galileo, or somewhere Galileo can read its saved picture. Otherwise you see the close-up of the star.

> PAUSE: 32

### Calibrating and guiding

> SCREEN: Press Guide. Show the calibration progress text.

Press Guide. If there's no calibration, or Recalibrate on Guide is ticked, PHD 2 first moves the mount in each direction to learn how it responds. Galileo shows the progress, step by step, and says whether it succeeded and why not if it failed. The star moving out of its square during calibration is normal.

> PAUSE: 54

The three lamps show the state: green for idle, yellow while preparing or settling, red while guiding.

Normally leave recalibrate off and reuse the calibration. Clear it after changing the guide scope, the camera angle or the mount.

### Reading the graphs

> SCREEN: Guide graph. Toggle RA, DEC, SNR, corrections, RMS.

The guide graph plots error against time. Tick which lines to draw: right ascension, declination, signal to noise ratio, correction pulses and the running average. Zoom the scale in or out, and set the length of history from thirty seconds to ten minutes.

> PAUSE: 19

The statistics give the latest error, pulse length, the root mean square error in each axis and in total, the guide star's signal to noise, and its mass and size. Compare total error with the image scale of your imaging telescope, not the guide scope. If the error is comfortably smaller than one imaging pixel, your stars will be round.

A signal to noise below about ten is unreliable. Use a longer exposure or a brighter star.

> PAUSE: 13

### Drift and calibration plots

> SCREEN: Mount Drift plot and Calibration Plot.

The Mount Drift plot scatters recent star positions inside target rings. You want a tight, round cluster in the green ring. A stretched cluster tells you one axis is struggling.

The Calibration Plot shows how the star moved during calibration. Healthy calibration is two straight lines at roughly right angles. Short, bent or skewed lines mean something needs attention: backlash, balance, or a calibration made too close to the pole.

> PAUSE: 27

If oscillation is fast and back and forth, the corrections are too aggressive; if the star wanders slowly, they're too weak. Those settings live in PHD 2. The Dec guide mode here lets you restrict declination to north or south only, which can help a mount with backlash.

### Dithering

> SCREEN: Options, Guiding. Then press Dither on the Guiding screen.

Dithering shifts the telescope a few pixels between frames, so hot pixels and fixed noise don't line up and can be rejected when you stack.

Under Options, Guiding, set the dither distance, whether to dither in right ascension only, and how settled is settled: a tolerance, a time it must hold, and a timeout. Press Dither to try it. In a session, add a Dither block between frames.

> PAUSE: 27

## Part 6: Imaging

### The screen

> SCREEN: Imaging screen. Highlight settings, preview, histogram, progress.

Open Imaging. On the left are capture settings, view options and tools. On the right are the preview, stretch, histogram and progress. This screen is for framing, testing and hands-on capture. For unattended nights, use sessions.

> PAUSE: 11

### Capture settings

> SCREEN: Point to each field.

Exposure, from a thousandth of a second upwards. Object, the name written into each file; it follows your current object, shows Unknown if there is none, and if you type a name it's looked up and becomes the current object. Quantity, how many frames to take. Gain and offset, where zero leaves the camera as it is. Type, which is light, dark, flat or bias, and is recorded in the file so the Library can sort it. And Filter, which turns the wheel; Capture waits for it to arrive.

> PAUSE: 19

The gain and offset recorded in each file are read back from the camera, so the headers show what really happened.

### Taking frames

> SCREEN: Take a test exposure. Zoom to one to one. Use Fit.

Take a test frame of ten or twenty seconds. Scroll to zoom and drag to pan. Fit shows the whole frame and one to one shows real pixels, which is the best way to check star shapes.

> PAUSE: 27

Round stars everywhere is good. Streaks all in one direction mean tracking or guiding. Distorted stars only in the corners point to spacing or tilt in your optical train, which no software setting will fix.

Press Capture for one run, Loop to repeat until you stop, and Stop to end.

### Statistics and histogram

> SCREEN: Highlight statistics and histogram. Take a short and a long exposure to compare.

Under the settings are the mean, median, minimum, maximum, star count and half-flux radius, and the histogram. A pile against the right edge means saturation, so shorten the exposure. A pile jammed against the left means too short, or too little gain to rise above the camera's own noise.

> PAUSE: 32

The stretch slider only changes how the preview looks. Your saved data is never altered by it.

### View options

> SCREEN: Toggle Debayer, Subtract dark, Crosshair.

For a colour camera, Debayer shows the preview in colour. Galileo ticks it automatically when the camera reports its pattern. If the colours look wrong, check the Bayer pattern on the Camera page. The file keeps the raw data.

Subtract dark takes a matching dark master from the preview and from live stacks. A label tells you whether one is available. Individual frames saved to disk stay raw.

Crosshair marks the exact centre.

> SCREEN: Show Annotate on a solved field.

Annotate plate solves the frame and labels the stars and deep-sky objects in it. While it's on, Save Frame writes the labelled picture as an ordinary image file, which is nice for sharing.

> PAUSE: 27

### Mount control, rotator and power

> SCREEN: Press Mount Control and use the floating pad.

Mount Control opens a small floating window with the direction pad and speeds, park, home, tracking on and off, a manual meridian flip that asks for confirmation, and a red Emergency Stop. Emergency Stop halts all motion at once. Learn where it is before you need it. A manual flip does not re-centre or restart guiding, so do that yourself afterwards.

> PAUSE: 32

The Rotator panel turns the camera to an angle. And the More button shows the power and dew channels you marked Show on imaging, so you can turn up a dew heater without leaving the frame.

> SCREEN: Set a rotation, then open More and adjust a dew heater.

> PAUSE: 21

### Saving

> SCREEN: Highlight Auto-Save to Library and Save Frame.

There are two independent ways to keep a frame.

Auto-Save to Library, ticked by default, files every frame into your repository, renamed and catalogued. It needs the repository folder set under Options, Library.

Save Frame writes one FITS file wherever you choose, and Galileo doesn't track it.

Turn Auto-Save off for throwaway tests, so your Library doesn't fill with them.

Under Options, Imaging, you can fix the pixel format of saved files. Leave it on automatic unless other software insists.

> PAUSE: 16

### Live stacking

> SCREEN: Tick Live Stack, Quantity 20, Capture. Show the image improving.

Tick Live Stack, set a quantity of several frames, and press Capture. Each new frame is aligned to the first and averaged in, so the picture on screen gets smoother and deeper as you watch. It's wonderful for checking whether a faint target is worth the night, and for showing visitors.

> PAUSE: 60

The individual frames still go to the Library. The stack is not saved automatically. Press Save Stack and choose the Library or a file, before you start another run or close Galileo.

### Framing and mosaic capture

> SCREEN: Framing button; set up a 2 by 2 mosaic; OK.

Open Framing to compose on a survey image, set rotation and define a mosaic. Press OK, and the Imaging screen shows which pane it's on, with a Clear Mosaic button to go back to single frames.

> PAUSE: 27

Capture then moves to each pane, waits for the mount to settle, five seconds by default, and exposes. With Live Stack on, the mosaic assembles on screen. Galileo plate solves the first frame of each pane and places it where it really is on the sky, so a pane that landed slightly off, or turned over after a meridian flip, still lines up.

> SCREEN: Mosaic building up pane by pane, sped up.

> PAUSE: 54

If the first frame of each pane is smeared, raise the settle time under Options, Imaging. The overlap setting is there as well.

## Part 7: Calibration frames

### What they are

> SCREEN: Examples of a dark, a flat and a bias frame.

Calibration frames remove the faults of your camera and optics. Darks record thermal signal and hot pixels. Flats record vignetting and dust shadows. Bias frames record the camera's baseline.

Darks must match your lights in exposure, gain, offset, temperature and binning. Flats must be taken with the same focus, camera angle and filter as your lights.

> PAUSE: 13

### The Darks Assistant

> SCREEN: Imaging, Darks button.

Cover the telescope. Open Darks. Type a list of exposure lengths, such as 60, 120, 180, and the number of darks at each. Tick Park Flat Panel if your flip-flat can act as the cover. Press Start.

> SCREEN: Run the assistant with short exposures.

> PAUSE: 40

Each dark appears in the preview, so you can confirm it really is dark. A light leak shows up as a gradient. Everything is saved to the Library.

### The Flats Assistant

> SCREEN: Imaging, Flats button.

Open Flats and pick a method. Sky Flats waits for twilight, points at a patch of sky with few stars, and adjusts each exposure as the sky changes. Flat Panel drives a connected panel. Observatory Panel uses a fixed light source that you've already pointed at.

Set the number of frames and filter, where All repeats for every filter. Leave exposure on Calculate. Calculation needs the camera's maximum well depth, entered on the Camera page, and Start refuses without it.

> PAUSE: 19

Press Start. If the target brightness can't be reached, the run stops and tells you why.

> SCREEN: Flat run in progress; press Hide, then reopen from the toolbar.

> PAUSE: 40

Both assistants let you press Hide and carry on working. The button on the toolbar reads running until it's finished.

## Part 8: Putting it together

### A manual night

> SCREEN: Montage following each step.

Here's a complete evening by hand.

Select your Pier and connect. Start cooling. Do a rough focus with Loop. Polar align. Run autofocus and set your emergency position. Choose a target and use Goto and Centre. Frame it with the Framing Assistant. Connect PHD 2, pick a star and start guiding. Take one test frame and examine it at one to one. Then set your quantity and capture. When you're done, take flats before you move the focuser or camera, then darks, warm the camera and park.

> PAUSE: 40

### The same night as a session

> SCREEN: Planning, Sessions: the finished session running.

Or build it once as a session: unpark, cool, slew, solve, guide, loop over filters with focus, images and dithers, then stop, warm and park. Save it as a template and use it again on your next target. Watch the Dashboard to see it progress.

> SCREEN: Dashboard with the running session.

> PAUSE: 32

### The meridian

> SCREEN: Mount page flip settings.

One last warning. On a German equatorial mount, a long run will reach the meridian. Set the flip option and limits on the Mount page, make sure cables clear, and supervise the first few flips. Check your framing and guiding afterwards.

> PAUSE: 13

## Part 9: Troubleshooting and good habits

### Reading your stars

> SCREEN: Examples of five kinds of bad star shapes.

Most problems show up in the shape of the stars, so learn to read them. Round but fat everywhere means focus or poor seeing. Small doughnuts mean you're well out of focus on a reflector. All stars stretched the same way means tracking, guiding, wind or a dragging cable. Stretched only in the corners means spacing, tilt or collimation. Double stars where there should be single ones mean the mount jumped during the exposure.

> PAUSE: 40

### Exposure choices

> SCREEN: Histograms of short, good and saturated exposures.

How long should an exposure be? Long enough that the sky background lifts clearly off the left of the histogram, and short enough that you don't clip too many bright stars. Under a bright suburban sky that point arrives quickly. Under a dark sky, or through a narrowband filter, it takes much longer.

> PAUSE: 32

Many shorter frames lose less when a plane or gust spoils one. Fewer, longer frames mean fewer files and overcome camera noise better. Pick a small set of standard exposures, which also keeps your dark library manageable.

> PAUSE: 13

### Autofocus problems

> SCREEN: A flat curve, a one-sided curve, a ragged curve.

A flat curve means the steps are too small. A curve with only one side means you started too far from focus, so focus by hand first. A ragged curve means too few stars, too short an exposure, wind or poor seeing. If the best position jumps between runs, look at backlash and at whether the focuser or camera is sagging.

> PAUSE: 40

### Solving problems

> SCREEN: A failed solve in the results table and the log.

If solving suddenly stops working after you changed a telescope, camera or reducer, check the focal length on the Optics page. If it works at one binning and not another, adjust downsampling. If it fails near the horizon, you may simply be looking at a tree. And if the solve succeeds but the mount still misses, repeat Slew to Target and check the settle time.

> PAUSE: 27

### Guiding problems

> SCREEN: Guide graph showing drift, oscillation and spikes.

A steady drift in declination usually points to polar alignment. A slow wave in right ascension is the mount's periodic error. Sharp spikes in both are wind, a snagged cable or someone walking nearby. A lost star may be cloud or dew. Check the physical things first: balance, cables, tight saddle bolts. No setting makes up for a loose guide scope.

> PAUSE: 40

### Camera and download problems

> SCREEN: View Log during a failed capture.

If captures fail or arrive slowly, look at the USB connection and power, and at whether the INDI or Alpaca server is on a weak wireless link. Large frames over poor Wi-Fi take a long time. A wired connection at the telescope is worth the effort. The log shows the exact error.

> PAUSE: 27

### Several Piers

> SCREEN: Switch Pier while another captures; show the Dashboard.

Everything in this episode is per Pier. You can start a capture, a focus run or a solve on one Pier, switch to another and keep working. The Flats and Darks assistants carry on in the background too. The Dashboard shows who's doing what.

> PAUSE: 40

### Habits worth keeping

> SCREEN: End-of-night checklist.

Take a test frame after any change. Refocus when the temperature moves. Take flats before touching the camera or focuser. Note anything odd while you remember it. Warm the camera before you disconnect, and watch the mount park. And before you go to bed, check there's disk space for tomorrow.

> PAUSE: 32

## Wrap-up

That's the heart of Galileo: focus, solve, align, guide and capture. Next we hand the whole routine to Galileo, with sessions and scheduling. Clear skies.

> PAUSE: 11
