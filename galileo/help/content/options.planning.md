<!-- order: 92 -->
# Planning settings

Settings for how Galileo treats the sky when it plans and slews.

## Do not slew where obstructed (see Star Atlas)

When ticked, any slew whose target lies below the horizon obstructions you defined in Options › Star Atlas is refused, whether it was asked for from the Mount page, the Star Atlas, a sequence or plate solving. The message "target is obstructed" is shown instead. Needs a horizon uploaded first.

## Cache All Catalog Thumbnails

Downloads the sky-survey thumbnail for every object in the catalog ahead of time, so searches on Planning › Targets show their pictures immediately instead of fetching them one at a time. There are tens of thousands of objects and each needs a network request, so this can take hours. You can cancel at any time; thumbnails already cached stay cached, and objects already cached are skipped if you run it again.
