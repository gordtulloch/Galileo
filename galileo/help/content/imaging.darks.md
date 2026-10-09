<!-- order: 22 -->
# Darks Assistant

The Darks Assistant captures dark frames — exposures with the lens or mirror covered — which record the sensor's heat noise and hot pixels so they can be subtracted from your lights. Open it from the Imaging screen's **Darks…** button. Cover the telescope (or close the dust cover) *before* you press Start, and keep the camera at the same temperature and gain as for your lights.

Each frame is saved to the Library.

## Filter

The filter to select on the wheel before each exposure. Leave at (none) for unfiltered darks, or when no filter wheel is connected. A dark does not depend on the filter, but this keeps the wheel position consistent with the matching lights.

## Exposures (s)

A comma-separated list of exposure lengths in seconds. One dark frame is captured at each value, in the order given. For example `10,20,30,60`. Match the lengths of the lights you want to calibrate.

## Start

Starts capturing the darks. The dialog cannot be closed while it runs.

## Stop

Abandons the run in progress.
