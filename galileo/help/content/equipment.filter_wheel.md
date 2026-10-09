<!-- order: 32 -->
# Filter Wheel

The Filter Wheel page connects Galileo to the motorised filter wheel and shows its current filter. The filter names read from the wheel appear on the right; the Imaging screen, the Flats Assistant and the sequencer use them when they change filter.

Set-up: choose the **Driver**, enter the **Server**, press **Scan**, pick the wheel in **Device**, press **Connect**, then **Save**.

## Name

The filter wheel's name as reported by its driver.

## Description

The driver's description of the filter wheel.

## Current filter

The filter currently in the light path. Choose another from the list and press **Change** to move the wheel.

## Change

Rotates the wheel to the filter chosen in the box to its left. Galileo waits for the wheel to stop. If the focuser has a saved offset for that filter (see Focus › Filter Offsets), it is applied by sequences when they change filter.

## Filters

The slots of the wheel in order, with the name each is given by the driver. Names come from the wheel's own configuration (in the ASCOM driver or INDI properties), not from Galileo.

## Filter name

The list of filter names, one per wheel position, starting from position 1.

## Settings

Filter-wheel-specific driver settings. None are available.
