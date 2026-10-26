<!-- order: 92 -->
# Guiding settings

How PHD2 dithers and settles. These are used by the Guiding screen's Guide and Dither buttons and by dithers in a session, and apply from the next command. They are saved for the whole application. PHD2's host and port are set on the Guiding screen.

## Save

Saves the values below. Changes are not stored until you click Save.

## Dither amount

The maximum distance, in guide-camera pixels, that a dither moves the guide star away from its position (0.1–30).

## Dither in RA only

Dither only along Right Ascension, leaving Declination alone.

## Settle tolerance

After a guide or dither command, the guide error must fall below this many pixels to count as settled.

## Settle time

How many seconds the error must stay within the settle tolerance before guiding counts as settled.

## Settle timeout

If guiding has not settled after this many seconds, the command is reported as failed.
