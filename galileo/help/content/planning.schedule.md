<!-- order: 16 -->
# Schedule

The Schedule is a calendar of your planned sessions and pier operations over several nights. Each night is a column; the hours run from dusk (top) to dawn (bottom), so a night is one continuous strip. Each column is shaded by how dark the sky is at that hour (when the Observatory's location is set) and labelled with the Moon's phase.

A session or pier operation appears as a coloured block, positioned by its start time and sized by its duration. Concurrent blocks sit side by side in the column. A block's border shows how its run went: green when completed, red on error.

**Working with blocks:** drag a block to another day or time to move it. Right-click a session block to *Set Time…*, *Edit…* its scheduling rules, *Show Trajectory…* (altitude over time), view its *Log*, or *Remove from Schedule*. Right-click empty space in the grid to *Add Pier Operation* (open or close the dome, sync the dome, park or unpark the mount) at that time. Sessions with no start time yet sit in the **Unscheduled** tray at the bottom left; drag one onto the grid to give it a start time.

A session runs by itself only once it has a start time, while Galileo is running with the equipment of the Pier shown in the top bar connected.

## Zoom Out

Shows fewer pixels per hour, so more of the night fits on the screen.

## Zoom In

Shows more pixels per hour, for placing blocks precisely.

## Fewer Days

Shows one fewer night column.

## More Days

Shows one more night column.

## Show Almanac Shading

Shades each column by the Sun's altitude at that hour, from daylight to full astronomical darkness, and labels each night with the Moon's phase. Needs the Observatory's latitude and longitude.

## Show Past Events

Reveals entries whose time has already passed. They are hidden by default to keep the calendar uncluttered.

## Autoschedule

Places every unscheduled session on the night being shown, then asks you to confirm. Sessions are placed in priority order (lowest priority number first), each in the earliest free slot long enough for its duration where the Sun is below its twilight limit, the target is above its minimum altitude and your horizon profile, and the Moon is far enough away. Slots that overlap another entry on the same Pier are skipped, and entries already on the calendar are never moved. Anything that cannot be placed is listed with the reason. Needs the Observatory's latitude and longitude.

## Day

The ◀ and ▶ buttons move the calendar back or forward by one day.

## Today

Returns the calendar to tonight.

## Unscheduled

Sessions that are planned but have no start time. Drag one onto the calendar to schedule it.

## Log

On a block, opens the log of that block's run. Only shown once the block has run.

## Set start time

In the *Set Time* dialog: tick to give the entry a start time, then set the date and time (your local time). Untick to leave it unscheduled.

## Set end time

In the *Set Time* dialog: tick to give the entry an explicit end. Without one, the block lasts for the **Duration**.

## Duration

How long, in minutes, the block lasts when no end time is set. It also sizes the block on the calendar.

## Edit…

Opens the job editor for a session block: queue priority, observing constraints, start and completion conditions, and frames required. Changes are saved straight away. Pier operations have no editor.

## Show Trajectory…

Charts the block's target altitude against time for tonight, from the Observatory's location. Needs the Observatory's latitude and longitude.

## Priority

In the job editor: lower numbers run first when several jobs are eligible.

## Min. altitude (°)

In the job editor: the job will not run while the target is below this altitude.

## Min. Moon separation (°)

In the job editor: the job will not run while the target is closer than this to the Moon.

## Twilight restriction

In the job editor: how dark the sky must be before the job may run (civil, nautical or astronomical twilight).

## Horizon

In the job editor: whether the job respects the horizon obstructions defined for the Observatory.

## Start

In the job editor: start immediately, when the target culminates, or at a fixed time.

## Completion

In the job editor: run once, repeat a number of times, or repeat indefinitely.

## Repeat count

In the job editor: how many times the job repeats when Completion is *Repeat N times*.

## Frames required

In the job editor: the number of frames the job must capture to count as complete.
