# Episode 5: Automation with Sessions and Scheduling

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: A telescope working alone at night, lights off in the house.

Welcome back. In the last episode you did everything by hand. Now we teach Galileo to do it for you. We'll build sessions out of blocks, repeat them with loops, save them as templates, run them, place them on a calendar across several nights, let Galileo arrange them, protect the whole thing with safety rules, and review the results in the morning.

A word first. Automation moves real motors while you're asleep. Galileo is alpha software, and no software knows about the cable you left draped over the mount. Build up trust gradually: simulators first, then supervised nights, and only then anything unattended.

> PAUSE: 9

## 2. Four words to keep straight

> SCREEN: Diagram: block, session, template, schedule.

A block is one step: slew, focus, take these frames, park. A session is an ordered list of blocks. A template is a saved copy of a session's blocks, for reuse. And the schedule is a calendar saying when sessions should run.

Planning sessions are instructions. The sessions in the Library are records of what you captured. Same word, different things.

> PAUSE: 9

## 3. The Sessions screen

> SCREEN: Planning, Sessions, empty list and block palette.

Open Planning, then Sessions. Your session cards are listed, and the block palette is on the right. Sessions belong to a Pier, and each Pier has its own list.

Press Add Session for an empty one. Or use Add to Session on any target, in the Star Atlas, Search, Targets or What's Up Tonight, and you get one that already begins with the slew to that object.

> SCREEN: Show both ways of creating a session.

> PAUSE: 23

Each card belongs to one camera. A new session takes the camera selected in the top bar, and every exposure, solve, focus run and flat in the session uses it, whatever the top bar says later. On a telescope with two cameras that matters.

## 4. Editing blocks

> SCREEN: Drag blocks in, reorder, right-click, drag one out.

Drag a block from the palette into the session. Drag within the card to reorder. Right-click a block to change its settings. To remove it, drag it out or use its menu. Every block and setting has built-in help.

> PAUSE: 23

Some blocks have prerequisites. Plate Solve needs to know what it's centring on, so it can only go below a Slew To.

In the Slew To block, type a name such as M 31 or Veil and press the magnifying glass. Galileo searches its own catalog first, and the SIMBAD online database only if that finds nothing. You can also type coordinates by hand.

> SCREEN: Search for an object in the Slew To dialog.

> PAUSE: 23

## 5. The blocks: mount and building

> SCREEN: Highlight each block in the palette as it is named.

Let's go through them all.

Slew To moves to a target and starts tracking. Plate Solve takes a picture, solves it and corrects the pointing. Park Mount and Unpark Mount do what they say.

Dome Open opens the shutter or roof, and does not run in unsafe conditions. Dome Close closes it. Dome Sync lines the slit up with the telescope.

> PAUSE: 16

## 6. The blocks: camera, focus and guiding

> SCREEN: Open the Image block dialog.

Cool Camera takes the sensor to your set temperature, and Warm Camera brings it back gently.

Image is the one that collects light. Set exposure, count, filter, binning, gain, offset and frame type. Leave gain or offset on camera default to leave the camera alone. Under Framing and Mosaic you can give the block a centre and a grid of panes with overlap, and it captures each pane in turn.

> PAUSE: 27

Filter Change moves the wheel and applies any saved focus offset. Autofocus runs a sweep with your Focus settings, either on the current filter or after switching to one you name.

Guide Start begins guiding, with an option to calibrate first. Calibrate after changing optics or rotating the camera, and otherwise skip it to save time. Dither nudges between frames. Guide Stop ends guiding, and belongs before any slew.

> PAUSE: 16

## 7. The blocks: calibration and messages

> SCREEN: Flat Capture and Dark Capture dialogs.

Flat Capture offers the same choices as the Flats Assistant: sky, flat panel or observatory panel, exposure or calculate, number of frames, filter and measurement method.

Dark Capture takes a list of exposure lengths. Close Cover shuts a connected dust cover or flip-flat first and reopens it afterwards. With no cover, the block carries on and notes it in the log, so don't assume your darks were dark unless something really blocked the light. A Seestar uses its dark filter instead, so choose that in Filter.

> PAUSE: 23

Finally Notification sends your message to your notification channels when the session reaches it.

## 8. Loops

> SCREEN: Drag in FOR Filter and indent blocks under it.

FOR Filter repeats once for each chosen filter. Right-click to pick them from your filter wheel. FOR Object repeats once for each object in its list, which you build by searching the catalog.

Only blocks indented beneath a loop are inside it. Drag right to put a block in, left to take it out. An unindented block runs once, after the loop. A loop moves together with its contents.

> SCREEN: Indent three blocks; then outdent the last one.

> PAUSE: 27

Read your indentation before every first run. If Park is inside the loop, your mount parks after the first filter. If Autofocus is outside it, you focus once and not for each filter.

Loops can sit around loops: for each object, then for each filter. Keep it as simple as your night allows.

> PAUSE: 12

## 9. A first session: one target

> SCREEN: Build the session step by step as narrated.

Here's a sensible single-target session. Dome Open, if you have one. Unpark. Cool Camera. Slew To your target. Plate Solve. Autofocus. Guide Start. Image: thirty frames of two minutes. Guide Stop. Warm Camera. Park. Dome Close. Notification, saying the target is finished.

> PAUSE: 51

Notice the shape: prepare, point, refine, capture, then put everything away. Always end with the put-away steps.

## 10. A second session: several filters and targets

> SCREEN: Build the loop version.

For a filter camera, replace the single Image with a loop over luminance, red, green and blue, containing Filter Change, Autofocus, Image and Dither.

For a night of several objects, wrap the lot in FOR Object, with the Slew To and Plate Solve inside, and guiding started and stopped inside too, so you never slew while guiding.

> PAUSE: 45

## 11. Time estimates

> SCREEN: Highlight the Estimated total time line. Change the count.

Under each card is the estimated total time. It counts exposures and downloads, loop repeats, and allowances for slews, filter changes, focusing, solving and cooling. It updates as you edit.

These are planning figures, not measurements. Retries aren't counted, nor is any focus run or meridian flip the session doesn't list. Leave yourself a margin before dawn.

> PAUSE: 16

## 12. Saving and templates

> SCREEN: Save, name the session, then Save as Template.

Press Save and give the session a name. A saved or scheduled session survives restarts, until it completes or you delete it. A session you never saved or scheduled is not kept.

Note that a session which completes is removed from the list. So if you'll want the recipe again, press Save as Template.

> PAUSE: 18

A template stores the procedure. Load from Template fills a session you've already started with a Slew To, and keeps your target. Add Session from Template, at the bottom, makes a new session including the template's target, for you to change. Mosaic settings aren't stored in templates, because a template is a method and not a framing.

> SCREEN: Create a new session from a template and change its target.

> PAUSE: 23

## 13. Running a session

> SCREEN: Press Run with something deliberately disconnected.

Run starts now. First Galileo checks that every device each block needs is connected and that the order makes sense. If not, it lists the problems and doesn't start.

> PAUSE: 16

> SCREEN: Connect the device and Run again. Show the executing block marker.

While running, a green marker shows the block being carried out, with frame progress, and the card is locked. Pause holds before the next block or frame, Resume continues, and Stop abandons the current exposure or slew. The Imaging screen shows the session's progress too.

> PAUSE: 34

If a scheduled session is already running on the Pier, Run stops it and takes over.

## 14. When things go wrong

> SCREEN: Table: bad frame, three bad frames, failed slew or solve, unsafe.

Galileo treats failures according to what they could cost you.

A bad frame is logged and skipped. Three in a row abandon that Image block.

A failed slew, plate solve, park or dome opening ends the session, so that nothing carries on with the telescope in an unknown state. Because a session can end early, don't rely on its last blocks as your only protection. Use the safety settings too.

If conditions turn unsafe, every session is stopped, however it was started. Galileo's protective stop then parks the mounts and closes the roof itself, so it doesn't depend on what your session had left to do.

> PAUSE: 18

## 15. The protections around a session

> SCREEN: Mount limits, Safety page, dome options, watchdog.

Set these once, before any unattended night.

On the Mount page: the meridian flip, and altitude and hour angle limits. On the Safety page: your weather station and safety monitor, with thresholds. On the Dome page: whether sessions open and close the dome by themselves, which includes closing and parking the dome if a session is stopped or fails. Before any automatic close, every telescope under the roof is parked and confirmed, or the roof is left open. Under Options, Planning: don't slew into your horizon. Under Options, Equipment: the watchdog. And under Options, Notifications: a phone alert, tested.

> SCREEN: Visit each page briefly.

> PAUSE: 34

Then test the whole chain on a calm evening while you're standing there. Trip the safety threshold deliberately and watch what happens.

## 16. The Schedule

> SCREEN: Press Schedule on a card; open Planning, Schedule.

Press Schedule on a session. The card is outlined in red and locked, the button becomes Deschedule, and the session waits in the Unscheduled tray on the Schedule.

Each column of the calendar is a night, dusk at the top and dawn at the bottom, shaded by darkness, with the Moon's phase above. Drag the session onto a night at the time you want. You can zoom, show more or fewer nights, and reveal past events.

> SCREEN: Drag a session onto tonight, then onto tomorrow.

> PAUSE: 34

Beneath the calendar, Upcoming Sessions lists what's still to run, soonest first.

## 17. Scheduling rules

> SCREEN: Right-click, Edit.

Right-click a block for Set Time, with start, end or duration, then Edit for the rules: priority, where lower numbers go first; minimum altitude; minimum distance from the Moon; how dark the twilight must be; whether to respect your horizon; start now, at the target's highest point or at a fixed time; run once, a number of times or indefinitely; and frames required.

> PAUSE: 23

Show Trajectory charts the target's altitude through the night. Look at it before you schedule. A target that sets behind your house at eleven isn't a three-hour job.

> SCREEN: Show Trajectory.

> PAUSE: 18

Right-click an empty spot to add a pier operation: open, close or sync the dome, or park or unpark.

## 18. Autoschedule

> SCREEN: Several unscheduled sessions with priorities. Press Autoschedule.

Autoschedule places all unscheduled sessions on the night shown. In priority order, each gets the earliest free slot long enough, where it's dark enough, the target is above its minimum altitude and your horizon, and the Moon is far enough away. It doesn't overlap entries on the same Pier or move ones you placed. You see a preview before accepting, and anything that doesn't fit is listed with the reason.

> PAUSE: 34

If something won't fit, read the reason. Usually it's too long for the dark window, so split it, or relax one rule.

## 19. Running to the clock, weather and shared roofs

> SCREEN: Schedule status line showing BLOCKED.

A scheduled session starts by itself when its time comes, provided Galileo is running and the equipment is connected. The computer must be awake, so turn off sleep. With several Piers, each one whose equipment is connected starts its own.

If conditions turn unsafe, the status line shows Blocked with the reason. The running session is stopped, and the telescopes are parked and the roof closed. Nothing new starts until conditions have been safe for a while and you acknowledge, unless you've opted in to restarting scheduled sessions automatically.

> PAUSE: 16

With a shared roof, one Pier won't close it or move the dome while another is imaging. That step is skipped and noted. Opening is never blocked. The automatic close with sessions waits in the same way. Make sure every telescope under a roll-off roof is somewhere the roof clears.

> PAUSE: 12

## 20. Rehearsing a session

> SCREEN: Run a shortened session against simulators.

Before a session runs under the stars, rehearse it. Connect simulators, make a copy of your session, and shorten every exposure to a second and every count to two or three. The structure stays, and the whole night plays in minutes.

> PAUSE: 45

Watch the order of the blocks. Does it unpark before it slews? Does it guide after it solves? Do the loops repeat what you meant, and nothing more? Does it end parked and warm?

> PAUSE: 23

Then break it on purpose. Disconnect a device and press Run, and see the pre-run check complain. Trip the safety monitor and watch the session stop, the mount park and the roof close.

> SCREEN: Trip the safety monitor and show the protective stop.

> PAUSE: 34

## 21. A project over several nights

> SCREEN: Template, then several scheduled nights.

Faint objects need more than one night. Build the session once and save it as a template. For each night, create a session from the template, and either run it or place it on the calendar. Because completed sessions are removed from the list, the template is your master copy.

> PAUSE: 27

Between nights, check your total in the Library or on the What's Up Tonight tile, which shows hours integrated. Keep exposure, gain, offset and temperature the same, so that one set of darks serves the whole project. Use Load and Slew, or plate solve to the same target, to match your framing, and if you have a rotator, record the angle.

> PAUSE: 23

Take flats at the end of each night if anything in the optical train moves between sessions.

## 22. The morning after

> SCREEN: Schedule block borders and the log; History; Library.

Make a habit of five checks. On the Schedule, a block's border shows whether it completed or ended in error; open its log. Show Past Events if it has scrolled away. In History, look at star size and count. In the Library, confirm the frames arrived under the right object. Look at a handful of frames by eye. And check the equipment is parked, covered and warm.

> PAUSE: 45

## 23. Common questions about automation

> SCREEN: Question cards.

Where is the meridian flip block? It's no longer in the palette. Set the flip on the Mount page, and it applies while sessions run, though older sessions containing the block still load.

Can I edit a running session? No. Stop it, or for a scheduled one, deschedule it first.

> PAUSE: 12

Will it refocus by itself as the temperature changes? Put Autofocus blocks where you want them, for example inside your filter loop, so focus is renewed each time round.

What if the computer restarts? A saved or scheduled session is still there, but check the state of your equipment before relying on anything carrying on. Never assume a mount parked itself.

> PAUSE: 12

## 24. Watching, reviewing, and wrap-up

> SCREEN: Dashboard with timelines.

While it runs, the Dashboard shows each Pier's session, mount, guiding, solving, focusing and every captured frame on a timeline, with guide error beneath.

> PAUSE: 18

> SCREEN: Planning, History, chart and table.

In the morning, History shows each light frame's star size, star count and guide error. Rising size suggests focus drift. Falling counts suggest cloud or dew. Export it, then check the Library to see what arrived.

> PAUSE: 23

Start small: one target, one supervised night. Save what works as a template. Add one piece of automation at a time. Next, safety and running several telescopes. Clear skies.

> PAUSE: 9
