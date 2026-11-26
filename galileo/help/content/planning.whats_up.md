<!-- order: 13 -->
# What's Up Tonight

What's Up Tonight ranks the deep-sky objects in the catalogs for a night at your observatory, best first, so you can quickly pick a target. The ranking considers how high and for how long each object gets, how close it is to the Moon, whether it fits your telescope's field of view, the weather forecast, aurora activity and smoke, and how much you have already imaged it.

It needs the Observatory's latitude and longitude (top bar). Set the criteria on the left and press **Rank Tonight**. The picture across the top shows when it is day, twilight and night.

## Observing date

The night to plan. Defaults to tonight. The sky is recomputed for the date you choose; weather, aurora and smoke advisories are only available for today.

## Max candidate magnitude

Objects fainter than this are left out before ranking, so the whole catalog of 10,000+ objects is not ranked every time. Larger numbers include fainter objects.

## Min. altitude

An object that never climbs above this many degrees tonight is ranked down and annotated.

## Catalog

Only rank objects in the ticked catalogs (Messier, Caldwell, NGC, IC). With none ticked, every catalog is included.

## Rank Tonight

Works out the ranking and shows the top results as tiles.

## Day night band

A strip running from local noon on the chosen date to local noon the next day, so the night sits in the middle, showing the hours as day, civil, nautical and astronomical twilight, and night, with the start, end and total of each, and the times of solar noon and solar midnight. Imaging deep-sky objects is best in the dark "Night" segment.

## Field of view fit

Which optical train's field of view the ranking used. Objects too large or too small for it rank lower. If no optics are set, the fit is not evaluated.

## Advisories

Tonight's forecast: weather (cloud, wind, temperature), aurora activity (Kp index) and smoke (air-quality index). Poor values lower the confidence of the ranking.

## Astrospheric forecast

With an Astrospheric API key entered in Options > Planning, rows appear under the day/night band: Cloud, Seeing, Transparency, Temp °C, Dew point °C and Wind. Two more, **Smoke AQI** and **Aurora Kp**, come from NOAA and need no key: Aurora is NOAA's 3-hour Kp forecast (green quiet, yellow/orange active, red storm), and Smoke is today's NOAA smoke rating as one block across the night (shown for today only; North America only), coloured by AQI category. Each cell is one hour of Astrospheric's forecast, lined up with the same hour on the band above and coloured the way Astrospheric rates it, with its value inside (temperature and dew point converted to °C; the others as Astrospheric reports them, wind in Astrospheric's own unit). A dew point close to the temperature means dew is likely on the optics. Hours outside the forecast are left blank. If Astrospheric can't be reached, the line below the band says why (for example the key was rejected or the location is outside its North American/UK/Irish coverage). Informational only; it does not change the ranking.

## Image note

States how many result thumbnails were loaded. What's Up Tonight never downloads images (that made it slow to open); it only shows thumbnails already cached on this computer. To load them all in one go, use **Download Catalog Images** in Options > Planning, or browse the objects on the Targets page. Clicking a thumbnail opens a larger view, read from the same cache (the download includes those larger images, so it works offline).

## Results

One tile per ranked object, with its rank, name, type, brightness, size, constellation, best altitude tonight, and the reasons it scored as it did. A "Reduced confidence" badge means some inputs (horizon profile, weather forecast, aurora, smoke, Moon position) were unavailable; hover it to see which. If you already have data on the object, the tile shows the hours integrated.

## Save

The button on a tile that adds the object to Planning › Targets, your list of saved targets. Saving an object that is already there does nothing.

## Select

Makes this the Pier's current object and adds it to the target list.

## Slew To

Immediately slews the connected mount to this object. The object becomes the Pier's current object.

## Goto and Centre

Slews the connected mount to this object, then plate-solves and re-centres on it once the slew has finished. Needs a connected mount, a solver and the Observatory's location set. The object becomes the Pier's current object.

## Add to Session

Creates a new session on Planning › Sessions that already contains a Target block for this object.
