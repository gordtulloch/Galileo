<!-- order: 21 -->
# Flats Assistant

The Flats Assistant captures a set of flat frames — evenly lit exposures that record dust, vignetting and uneven illumination so they can be divided out of your light frames. Open it from the Imaging screen's **Flats…** button. It needs a connected camera; set the camera's *Max well depth* on Equipment › Camera — every flat method needs it to know the target brightness, and Start refuses without it.

Do flats with the same optical train, focus and camera angle as your lights. Pick a method, set the options, and press **Start**.

## Flat Method

How the light source is provided. **Sky Flats**: Galileo waits for twilight, points the mount at a star-poor patch of sky and adjusts each exposure to the right brightness. **Observatory Panel**: a fixed light panel or dome screen you have already pointed the scope at; Galileo only adjusts the exposure towards 50% of the max well depth. **Flat Panel**: a motorised cover with a built-in light (Equipment › Flat Panel); Galileo opens it, switches the light on, tunes the exposure (and the panel brightness if the exposure alone cannot reach the target) and closes it afterwards. Flat Panel is greyed out unless a flat panel is connected. If the target brightness cannot be reached, the run stops and says why.

## Exposure

The exposure time of each flat. Leave it at **Calculate** to have Galileo work out the exposure from the camera's max well depth, or set a value to fix it.

## Number of Frames

How many flat frames to capture per filter.

## Filter

Which filter to take flats with. **All** repeats the run for every filter in the wheel in turn. With no filter wheel connected the run is unfiltered.

## Method

How the brightness (ADU) of a flat is measured when hunting for the right exposure: **Average** of all pixels, or the **Median**, which ignores stray bright stars.

## Exposure Increment

The smallest exposure step, in seconds, taken while hunting for the right exposure. A smaller step is more precise but slower to converge.

## Start

Starts capturing. The dialog cannot be closed while a run is in progress; the status line shows which filter and frame it is on.

## Stop

Abandons the run in progress.
