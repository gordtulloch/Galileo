<!-- order: 40 -->
# Focus

The Focus screen finds best focus. It takes a series of short exposures while moving the focuser in equal steps, measures how large the stars are in each (their **HFR**, half-flux radius — smaller is sharper), fits a V-shaped curve through the results, and moves the focuser to the bottom of the V.

The screen *shows* a run; it does not own one. A run started by a sequence's autofocus trigger or block appears here too, in exactly the same way, and the last run's picture and curve stay on screen until the next run starts or you press **Clear**.

**Left:** the focuser and camera settings and the buttons that start things. **Right:** the frame being measured, its star statistics, and the V-curve. **Bottom:** the log.

Before you start: connect a focuser (Equipment › Focuser) and a camera, and put the telescope on a star field that is roughly in focus — the sweep is centred on wherever the focuser is now.

## Status

A one-line summary of what the screen is doing: idle, which exposure of the sweep is being taken, or the result of the last run.

## Focuser

The settings for an automatic focus run, and the live focuser readout. Changes to Step size, Points, Backlash and Exp are remembered and used by sequences too.

## Focuser device

The focuser this screen drives: the one associated with the **Optics** selected in the top bar (set on Equipment › Optics). If that tube has none associated, the Pier's first connected focuser is used. Shows its name and whether it is connected.

## Focuser position

The focuser's current position, in steps, read live from the device.

## Focuser temp.

The focuser's temperature sensor, in °C — useful for noticing that the night has cooled enough to need refocusing. Shows — if the focuser has no sensor.

## Step size

How many focuser steps to move between one exposure and the next. Choose it so that the sweep reaches clearly out of focus on both sides of best focus: too small and the V-curve never gets steep enough to fit; too large and too few points land near the bottom.

## Points

The number of exposures taken across the sweep, centred on the current position (3 to 41). More points give a more reliable fit but take longer. The total travel is roughly Step size × (Points − 1).

## Backlash

Mechanical slack in the focuser's gears. When this is above zero, every move during a run overshoots by this many steps and then returns, so the gears always take up the slack from the same side. Set it to the number of steps it takes for the image to start changing after reversing direction; 0 turns the compensation off.

## Auto Focus

Starts a run with the settings shown: the focuser moves to the start of the sweep, takes an exposure at each point, fits the curve and moves to the best position. If no sensible minimum can be found (for example, clouds or no stars) the focuser returns to where it began and the reason is logged.

## Focuser stop

Stops the run that was started from this screen. The focuser goes back to the position it had when the run began.

## Filter Offsets

Opens the filter-offset tool. Different filters bring light to focus at slightly different positions. Here you measure each filter's best focus relative to a **Primary** filter once; afterwards, when a sequence changes filter, Galileo shifts the focuser by that filter's offset instead of running a full autofocus.

## Camera

The camera used for the focus exposures: the one chosen in the top bar's **Camera** selector, shown by its device name and whether it is connected. To use a different one, change the Optics / Camera selectors at the top of the window.

## Gain

The camera gain used for the focus exposures. It starts at the camera's **Default gain** from Equipment › Camera whenever you choose a camera or Pier, and you can change it here; the change applies to this screen's exposures only and is not saved back to the camera. **—** leaves the camera's own setting alone.

## Offset

The camera offset used for the focus exposures. It starts at the camera's **Default offset** from Equipment › Camera and behaves like **Gain**.

## Exp

The exposure time of each frame in the sweep. Choose it long enough to show plenty of stars well above the noise but short enough that bright stars do not saturate — a saturated star's measured size stops changing with focus.

## Manual Focus

Tools for focusing by hand, watching the HFR number change, without running a full automatic sweep.

## Manual Focus position

The focuser position to move to, in steps. Type a value and press **Move**.

## Manual Focus move

Moves the focuser to the position in the box beside it.

## Set Emergency

Remembers the focuser's current position as its **emergency focus** — a known-good position to come back to if you are ever wildly out of focus (a filter or camera change, a bumped focuser, a failed autofocus). Set it when focus is good. Applies to the primary focuser. Needs a connected focuser whose settings have been saved on Equipment > Focuser; the position is kept with those settings and survives a restart.

## Go to Emergency

Moves the focuser back to the saved emergency focus position, the same way **Move** does. Greyed out until one has been set, and while an autofocus run is in progress.

## Emergency position

The saved emergency focus position, or — if none has been set for this focuser.

## Capture

Takes one exposure (using **Exp**) and measures the stars in it, updating the picture and the statistics line.

## Loop

Takes exposures one after another, updating the picture and HFR each time, so you can adjust focus (with the Move box, or the focuser's hand controller) and watch the number fall. Press **Stop** beside it to end the loop.

## Manual Focus stop

Ends the exposure loop started with **Loop**. It is greyed out when no loop is running.

## Frame

The last frame measured, stretched so faint stars show. Stars used for measurement are those the software detected; this is a preview only and is not saved to the image library.

## V-Curve

A graph of star size against focuser position. Blue points are the measured HFR at each position; the orange line is the fitted V-curve; the green marker is the best-focus position the fit found. A clean, symmetric V with the green marker at the bottom means a trustworthy result. A flat or ragged curve means the sweep range, exposure or seeing needs adjusting.

## Statistics

The star count, median HFR and equivalent FWHM (about 1.5 × HFR) for the frame on screen. HFR and FWHM are in pixels. **−1.00** means no stars were found.

## Clear

Forgets the last run's picture, statistics and curve, returning the screen to idle.

## Exposure progress

Shows how far through the current exposure the camera is, as elapsed / total seconds. It fills during each autofocus sample and each manual Capture or Loop exposure, and holds full while the frame downloads and is measured. Empty (—) when no exposure is running.

## Choose layout manually

By default the screen arranges itself to suit the frame: a portrait frame (taller than it is wide) gets a full-height column on the right, about a third of the screen wide, with everything else beside it. Tick this to pick the arrangement yourself with **Layout**.

## Layout

**Landscape** or **Portrait** arrangement of the screen. Available only when **Choose layout manually** is ticked.
