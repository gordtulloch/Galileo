# Episode 6: Observatory Safety and Multi-Pier Operation

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: A roll-off roof observatory with clouds building behind it.

Welcome back. The last episode taught Galileo to run a night. This one is about what happens when the night goes wrong, and about running more than one telescope at once.

> PAUSE: 14

Please hear this first, because it's the most important thing in the series. Galileo is alpha software. It is not a certified safety system. It can park your telescopes and close your roof when the weather turns, but only while the computer, the software and the network are all working. Protect expensive equipment with something that works even when they aren't.

> PAUSE: 17

## 2. Layers of protection

> SCREEN: Diagram of stacked layers: hardware, mount limits, session, weather, watchdog, alerts, person.

Think in layers. At the bottom is hardware: a rain sensor wired to the roof controller, mount limit switches, a roof that cannot hit the telescope. Above that are the mount's own limits. Then Galileo's safety rules, your session's shutdown steps, a watchdog, and alerts that reach a human. No single layer is enough.

> PAUSE: 25

## 3. Describing the site

> SCREEN: Observatory dialog, including contact details.

Everything starts with an accurate Observatory: latitude, longitude, time zone. It can also carry contact details for the person responsible. If it does, e-mail and text alerts go to those recipients. Phone alerts through ntfy go to whoever has subscribed to your topic.

> SCREEN: Fill in the contact fields.

> PAUSE: 25

## 4. Weather stations and safety monitors

> SCREEN: Equipment, Safety page.

Open Equipment, Safety. There are two kinds of device. A weather station gives readings, such as temperature, humidity, wind, cloud and rain. A safety monitor gives one answer: safe or unsafe.

You can add several with the plus button, one per tab. They belong to the Observatory, so every Pier shares them. Switching Pier doesn't disconnect them, and the Pier's Connect button leaves them alone. Each tab has its own Connect.

> SCREEN: Scan, connect and save a weather station, then add a safety monitor.

> PAUSE: 35

How do you get one? Galileo accepts anything that presents itself over INDI or Alpaca as a weather station or safety monitor. A software cloud detector that publishes a standard safety monitor works too. Online forecasts shown in planning are information only. They are not safety devices.

## 5. Choosing rules

> SCREEN: Measures table: tick, comparison, threshold.

For a weather station, tick each measure that should count. Choose how it's compared, for example greater than, and the threshold. An unticked measure is shown for information. For a yes or no reading such as rain, use zero or one as your device does.

> SCREEN: Set rules for rain, wind, humidity and cloud.

> PAUSE: 35

Think about each. Rain: any at all is unsafe. Wind: where does your telescope start to shake, and where does your roof become hard to move? Humidity: how close to the dew point before optics fog? Cloud: where is imaging pointless? Set limits with margin, because weather arrives faster than roofs move.

Set the polling interval, from five seconds to ten minutes. Shorter reacts faster, though many stations only update about once a minute. Then Save.

> PAUSE: 17

A banner shows safe, or unsafe with the reasons. If a connected device can't be read, treat that as what it is: you don't know the weather. Scheduled starts count an unreadable connected device as unsafe. But if no safety device is connected at all, there is nothing to hold anything back. So check it's connected, every night.

> PAUSE: 17

## 6. The protective stop

> SCREEN: A numbered list: stop, guiding, park, close, wait.

Here is the behaviour, so learn it.

First, nothing new starts. Then Galileo stops whatever is running: sessions, captures, focus runs, solves, the flats and darks assistants, and held jogs. The exposure in progress is abandoned. This happens whether you started it, the schedule did, or nothing is running at all.

> PAUSE: 21

Second, guiding stops, and every mount in the Observatory is parked. Galileo doesn't take the command for granted: it waits for each mount to report that it is parked.

> PAUSE: 21

Third, the roof or dome closes, once every mount under it has confirmed. If one can't, even because it's switched off or disconnected, the roof is left open. Galileo keeps retrying the park, closes as soon as it can, and alerts you again and again until it does or the weather clears.

> SCREEN: Trip a threshold during a capture on simulators: stop, park, roof closing, banner.

> PAUSE: 42

Fourth, it waits. Conditions must stay safe for fifteen minutes by default, and then you press Acknowledge in the banner. Until then nothing starts. You can still operate equipment by hand, and Galileo won't undo what you do. The record survives a restart.

> PAUSE: 17

## 7. Settings for the stop

> SCREEN: Safety page, the Protective stop box.

At the foot of the Safety page you can switch the protective stop off, or only the roof close; set how long a device may drop out before it counts, one minute by default; set how long safe must last; and opt in to restarting scheduled sessions automatically. A restarted session begins again from its first block. Each weather rule can also be set to Warn, which tells you without stopping anything. The stop and roof close are on by default, so check your rules are ones you really want to act on. A saved safety device that isn't connected counts as unsafe.

> PAUSE: 35

## 8. Closing the roof

> SCREEN: A hardware rain sensor wired to a roof controller.

So how should a roof close in bad weather? The robust answer is outside Galileo: a roof controller with its own rain sensor, and its own safe-to-close logic, that works with the computer switched off. Galileo's weather rules and alerts then become your early warning.

Know your geometry. On many roll-off roofs the telescope must be parked before the roof can pass. Galileo's automatic closes park first, but its Close button does not, and a mount can report parked when it isn't where you think. Make collision physically impossible, or make your hardware enforce it.

> PAUSE: 28

## 9. The Dome page

> SCREEN: Equipment, Dome. Open, close, park, abort.

The Dome page gives you Open, Close, Park and Abort, with the shutter state and azimuth. Learn where Abort is. The Observatory Status box summarises the dome and weather and says whether you're ready.

> SCREEN: Open and close the simulator dome.

> PAUSE: 35

For a rotating dome, Slave dome to mount keeps the slit in front of the telescope while it tracks. Leave it off if other software or hardware already does that, so the two don't fight.

Open and close dome with sessions opens the shutter as a session starts, and closes and parks the dome as it ends, including when it is stopped or fails. Before closing, Galileo parks every telescope under the roof and waits for each to confirm. If one can't be confirmed, even because it isn't connected, the roof is left open and you're alerted. It also waits while another Pier is imaging. A protective stop closes the roof by its own rules, whether or not this is ticked.

> PAUSE: 25

## 10. Mount limits and the meridian

> SCREEN: Mount page, limits and flip.

The mount's limits protect against collisions. Set minimum and maximum altitude, and an hour angle limit. They apply on every screen and during sessions: Galileo refuses slews outside them and stops a mount that tracks past them. Set the meridian flip too.

> PAUSE: 25

Also set your horizon, and under Planning, don't slew where obstructed, so nothing sends the telescope into a wall. Software limits depend on the mount knowing where it is. If it has lost its position, limits are wrong too, which is why hardware limits still matter.

> SCREEN: Try to slew into the horizon and show the refusal.

> PAUSE: 28

## 11. The Emergency Stop

> SCREEN: Imaging, Mount Control, red button.

In Mount Control there is a red Emergency Stop that halts all motion at once. The Dome page has Abort. Know both, and know where the physical power switch is.

> PAUSE: 17

## 12. The watchdog

> SCREEN: Options, Equipment, Enable watchdog.

Weather isn't the only failure. Software can hang. Under Options, Equipment, turn on the watchdog and choose a timeout, five minutes by default. If Galileo stops responding for that long, the watchdog parks the mounts under the roof, closes the dome shutter only once all confirm, and sends an alert. It takes effect the next time Galileo starts, and the status bar shows its state.

> PAUSE: 35

Know its limits. It parks every Pier's mount, but closes only the dome of the Pier shown on the equipment pages. It can't help if the computer loses power, crashes completely or loses the network to your devices. For those you need protection at the equipment: your INDI server's own watchdog driver, or roof hardware.

> PAUSE: 17

## 13. Alerts that reach you

> SCREEN: Options, Notifications. Send test alert.

Set up phone alerts through ntfy, with e-mail as backup, and enable safety abort and session error. Send a test. Make sure your phone will actually wake you for it, which may mean changing its do not disturb settings. Remember the alerts need your internet connection.

> PAUSE: 35

## 14. Test it

> SCREEN: A written test plan on screen.

Now prove it, in daylight, with you present. Start a session on safe conditions, then trip a threshold, and watch everything stop, park and close. Trip one with nothing running. Unplug the weather station and wait a minute. Switch off one mount and confirm the roof stays open and you're alerted. Unplug the network cable. Press your rain sensor. Write down what actually happened.

> SCREEN: Run through each test.

> PAUSE: 78

Repeat after every Galileo update. Behaviour in alpha software changes.

## 15. Multi-Pier: the idea

> SCREEN: Shed with two or three telescopes.

Now the happier subject. One Observatory can hold several Piers, and one Galileo runs them all. Each Pier is a mount with its own optical tubes. The author's reference setup has three: two Seestar smart telescopes over Alpaca, and a small refractor on an OnStep mount over INDI, under one roll-off roof.

> PAUSE: 25

## 16. Setting up the Piers

> SCREEN: Top bar: New Pier, then equipment pages.

Create a Pier for each mount, select it, and set up its equipment. Name them so you can tell them apart at a glance. Each Pier keeps its connections when you select another. So select each in turn, press Connect, and leave them all working.

> SCREEN: Connect three Piers, watching the progress screen.

> PAUSE: 53

Check that each Pier points at its own devices. If two drivers on one server have similar names, confirm by moving one focuser and watching which telescope responds.

## 17. What is separate and what is shared

> SCREEN: Two-column table.

Separate for each Pier: devices, optics, mount limits, focus and solve settings, current target, sessions and guiding. Each Pier needs its own copy of PHD 2, on its own port, such as 4400 and 4401, because one guiding program can't steer two mounts.

Shared by the Observatory: location, horizon, weather and safety devices, and often the roof.

> PAUSE: 35

## 18. Running them together

> SCREEN: Different sessions on each Pier.

Build sessions on each Pier and schedule them. Scheduled sessions start on every Pier whose equipment is connected, not just the one you're looking at. A Pier with nothing connected waits without holding up the others. Run, on the other hand, acts on the Pier shown in the top bar.

> SCREEN: Schedule one session on each Pier and watch them start.

> PAUSE: 53

You can capture on one Pier while focusing or solving on another. Watch the computer's load. Several cameras downloading at once need processor, memory, USB or network capacity, and a lot of disk.

## 19. Sharing a roof

> SCREEN: Two Piers under one roof; session log showing a skipped close.

With a shared roof, a Dome Close or Dome Sync block won't disturb it while another Pier is imaging. That step is skipped and noted in the log. Opening is never blocked. A protective stop is different: it stops every Pier first, then closes for all of them.

> PAUSE: 35

So design for it. The last Pier to finish should be the one that closes. Give each session its own park block, and consider which finishes latest. Make sure every telescope, parked, is below the roof's path, since one that failed to park can still be in the way.

> PAUSE: 17

## 20. Watching it all

> SCREEN: Dashboard with three timelines.

The Dashboard shows every Pier: session, mount, flip, guiding, solving, focus, captured frames and guide error. Double-click a timeline to make that Pier the working one. History is kept for twelve hours, until Galileo restarts.

> SCREEN: Double-click between timelines.

> PAUSE: 42

The health line at the bottom shows processor, memory, free disk, temperature and uptime, with warnings when they're tight. Under ten gigabytes free is a warning, under two is critical. Restart and Shut down are there too, refused while a session runs. A computer you've shut down can't be woken remotely.

> SCREEN: Highlight the health line.

> PAUSE: 28

If you run an all-sky camera, publish the AllSkyCam view on the Dashboard. Seeing the sky beside your timelines is worth a great deal.

## 21. A nightly checklist

> SCREEN: Checklist, ticked line by line.

Before leaving the observatory to run: safety devices connected and reading. Banner says safe for the right reasons. Rain protection tested recently. Mount limits and park positions set. Sessions contain park and close steps. Watchdog on. Alerts tested. Disk space free. Roof path clear. Someone able to respond if an alert arrives.

> PAUSE: 70

## 22. Wrap-up

> SCREEN: Dawn over a closed roof.

To summarise. Unsafe weather stops everything, parks the mounts and closes the roof, then waits for you. It can't do any of that without power, software and network. Build layers, test them, and keep a person in the loop. Next, we follow your frames into the Library. Clear skies.

> PAUSE: 17
