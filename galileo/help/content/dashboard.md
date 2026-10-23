<!-- order: 65 -->
# Dashboard

The Dashboard shows what every Pier of the selected Observatory is doing, as a compact timeline per Pier, so you can keep an eye on a multi-Pier Observatory (or a single Pier running overnight) without switching screens. The other screens remain the focused, single-Pier view.

Galileo records each Pier's activity in the background, about once a second, whether or not the Dashboard is showing, so the timelines are already filled in when you open it. The record is kept in memory for the last twelve hours and starts again when Galileo restarts. The Dashboard refreshes itself every couple of seconds while it is on screen, without slowing the rest of Galileo down. Double-click a Pier's timeline to make that Pier the working Pier.

## Pier timelines

Each Pier has its own timeline, headed by the Pier's name (a dot marks the Pier selected in the top bar) and a one-line status: the running session, the mount state, guiding and the current guide error. Time runs left to right, with the clock times along the bottom; the right-hand edge is now. The axis covers the period since the Pier first did anything (never less than 15 minutes, never more than 12 hours). Hover over a bar to see what it is and when it began.

The lanes, top to bottom:

- **Session** — a session is running (green) or paused (yellow), or ended in an error (red).
- **Mount** — the mount is tracking (green) or slewing (yellow). Blank means parked, not tracking or not connected.
- **Flip** — a meridian flip is in progress.
- **Guide** — guiding is running (green), calibrating or settling (yellow), or the guide star was lost (red).
- **Align** — a plate solve is running, from a session or from the Solve screen.
- **Focus** — an autofocus run is in progress, from a session or from the Focus screen.
- **Capture** — an exposure is being taken: white boxes are light frames, blue boxes are dark or flat frames. Each box is one frame.

Below the lanes is the **guide error** over the same period: RA in blue and Dec in red, on a scale that grows to fit the largest error (shown at the left, in arcseconds). To the right, the guide error of the last couple of minutes is plotted as dots inside 1″ (green) and 2″ (yellow) rings; a tight cloud at the centre means good guiding.

In the red night-vision theme the colours become shades of red, told apart by brightness.

## Plugin area

When a plugin offers a view for the Dashboard and you tick **Publish on Dashboard** on its page under Options, the view appears in a strip above the timelines — an all-sky camera animation, for example. The strip takes whatever height the timelines leave free, so every Pier's timeline stays in view; if there are too many Piers for that, the strip keeps a minimum height and the Dashboard scrolls. With nothing published there is no strip.
