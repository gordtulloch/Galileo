<!-- order: 94 -->
# Focus settings

The default values for an autofocus run on the current Pier. They seed the Focus screen's own controls, and are used by autofocus started from a sequence. Saved per Pier, so a different telescope can have different defaults. Press **Save** to keep your changes; they apply from the next run.

See the Focus screen's help for what each setting does while a run is in progress.

## Step size

How many focuser steps to move between one exposure and the next during a sweep. The sweep should reach clearly out of focus on both sides of best focus.

## Number of points

How many exposures are taken across the sweep, centred on the current focuser position (3–41). More points give a more reliable fit but take longer.

## Exposure time

The exposure time of each frame measured during a sweep, in seconds.

## Backlash compensation

Overshoot and return by this many steps before every focuser move during a run, so the gears always take up slack from the same side. 0 turns it off.
