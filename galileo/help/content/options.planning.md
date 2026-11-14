<!-- order: 92 -->
# Planning settings

Settings for how Galileo treats the sky when it plans and slews.

## Do not slew where obstructed (see Star Atlas)

When ticked, any slew whose target lies below the horizon obstructions you defined in Options › Star Atlas is refused, whether it was asked for from the Mount page, the Star Atlas, a sequence or plate solving. The message "target is obstructed" is shown instead. Needs a horizon uploaded first.

## API key

Your Astrospheric Professional API key. When set, What's Up Tonight adds Astrospheric's cloud cover, seeing and transparency forecast for tonight to its advisory line (North America, Greenland, Iceland, Ireland and the UK only). Leave it empty to switch this off. Press **Save** to keep it. The key is stored in Galileo's database and shown masked; each forecast uses Astrospheric API credits.

## Save

Saves the API key beside it (Enter in the field does the same). Saving an empty field removes the key and turns the Astrospheric forecast off. The next time What's Up Tonight is shown it picks up the change.

## Download Catalog Images

Downloads one ZIP file of sky-survey thumbnails for the whole catalog from galileo-imaging.com and unpacks it into Galileo's image cache, so What's Up Tonight and Planning › Targets show pictures without fetching each one. The pack holds both the small tile images and the larger click-to-enlarge images, so enlarging a thumbnail works offline too. Images you already have are kept; run it again after an update to add the new ones. You can cancel while it downloads.
