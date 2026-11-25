# Episode 1: Introduction and Overview

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: Night-sky footage, then the Galileo splash screen with its progress bar.

Welcome to Galileo. Galileo is an astrophotography imaging application. It points your telescope, focuses it, guides it, takes your pictures, files them away, and calibrates them. And it does that on Windows, on macOS, on Linux, and on small ARM computers such as the Raspberry Pi 5.

This series walks through everything Galileo does. In this first episode we'll look at what it is, why it exists, how the window is laid out, how Galileo thinks about your equipment, and what a typical night looks like from start to finish. Later episodes go into each area in detail.

> PAUSE: 16

One thing before we start, because it matters. Galileo is alpha software. It runs, and a great deal of it works, but some screens are still unfinished, and parts of it have been tested against simulated equipment and not yet against the real thing. Please try it, and please tell us what breaks. But do not yet rely on it for a night you can't afford to lose. Throughout this series, when something is early or untested, I'll say so.

## 2. Why Galileo

> SCREEN: Title card listing Windows, macOS, Linux, Raspberry Pi. Then the INDI and ASCOM Alpaca logos.

Many imagers use a Windows computer at the telescope, because a lot of popular software is built around Windows ASCOM drivers. Others run INDI on Linux or on a Raspberry Pi. Galileo is built so that you don't have to choose your computer first and your software second.

It talks to hardware through two network protocols. The first is INDI, the open instrument protocol that is widely used on Linux, on Raspberry Pi, and in appliances such as StellarMate and Astroberry. The second is ASCOM Alpaca, the network form of the ASCOM standard. Alpaca is how you reach many smart telescopes, such as the Seestar, and it's also how you reach traditional Windows ASCOM drivers, by way of a bridge program called ASCOM Remote.

> PAUSE: 12

Galileo does not load Windows COM drivers directly. Everything it controls is reached over the network, even if the network is just your own computer talking to itself. That has a useful consequence. The computer running Galileo does not have to be the computer your equipment is plugged into. You can have a Raspberry Pi strapped to the mount running an INDI server, and Galileo on a laptop indoors. You can mix INDI devices and Alpaca devices in the same telescope setup.

Galileo also brings together several earlier projects by its author. AstroFiler, an image library and calibration tool, is built in. The sky atlas and framing logic come from a project called Obsy. And VSTarget, a tool for observing variable stars, comes as a plugin. Galileo is free, open-source software under the GNU General Public License, version 3 or later.

## 3. What you need

> SCREEN: Simple diagram: Galileo computer, network, INDI server, Alpaca bridge, devices.

To run Galileo you need a computer. To control equipment you need an INDI server or an Alpaca device for it to talk to.

Three other programs are optional but recommended. ASTAP, with one of its star databases, gives you plate solving, which is how Galileo works out exactly where your telescope is pointing from the stars in a picture. PHD 2 handles autoguiding. And if you want to open your frames in an external viewer, you can point Galileo at the one you like.

You don't need any hardware to look around. The Star Atlas, Planning, framing and the Library all work with nothing connected. So you can install Galileo this afternoon and explore it on a cloudy night, which, for most of us, is most nights.

> PAUSE: 12

## 4. A tour of the window

> SCREEN: Galileo main window on the Dashboard. Highlight the sidebar.

Let's look at the window. Down the left is the sidebar, with one icon for each major section. From the top you have the Dashboard, Star Atlas, Planning, Imaging, Guiding, Focus, Solve, Library and Science. At the bottom are Equipment and Options. The Science section appears only when a science plugin is installed, and other plugins can add icons of their own.

> PAUSE: 20

Some sections open a second column of choices. Planning opens onto What's Up Tonight, Search, Targets, Sessions, Schedule and History. The Library opens onto Images, Sessions, Mappings, Dedup, Merge Objects and Cloud. Equipment has one page for each kind of device.

> SCREEN: Click Planning, then Library, then Equipment, showing each second-level menu.

> PAUSE: 24

At the very bottom of the sidebar is a cluster of small buttons. One cycles the theme between light, dark and red night-vision. Others open the built-in help, the online manual, the community menu, the log viewer and the About box.

> SCREEN: Cycle through the three themes, ending on dark.

The red theme is for use at the telescope, so that checking your screen doesn't cost you your dark adaptation.

> PAUSE: 12

Across the top is the bar that sets your context. It has an Observatory selector and a Pier selector, and on screens that need them, an Optics selector and a Camera selector. At the right-hand end, once you've picked a target, you'll see a note that says something like, Current object, M 31.

> SCREEN: Highlight the top bar from left to right.

Along the bottom is the status bar, which gives short messages such as a mount connecting or a capture completing. And over the top-right corner you'll see event notices: small panels that appear when something significant happens. An exposure starts, a slew ends, a plate solve succeeds, a focus run finishes, a device connects or drops out. Each one goes away after ten seconds, or you can close it yourself.

> SCREEN: Trigger a connect so that an event notice appears.

> PAUSE: 16

## 5. Observatories, Piers and optical tubes

> SCREEN: Animated diagram: one Observatory containing two Piers; each Pier has a mount and one or more tubes.

This is the most important idea in Galileo, so let's take it slowly.

Galileo organises your equipment the way an observatory is physically laid out. At the top is an Observatory. That's a site: a name, a latitude and longitude, a time zone, and optionally an address and owner. Your location drives the sky atlas, the planning tools, twilight times and the horizon.

Inside an Observatory are Piers. A Pier is one mount, plus whatever rides on it.

On a Pier are one or more optical tubes. Each tube is a telescope or lens, with its focal length and aperture, and the camera, filter wheel, focuser and rotator that belong to it.

> PAUSE: 16

If you own one telescope, you need one Observatory with one Pier and one tube, and you'll set that up once. If you own several, Galileo can run them all from one program. Each Pier keeps its own device connections, its own settings, its own current target, and its own sessions, and several Piers can capture, focus and solve at the same time.

Some things are shared across the whole Observatory. Weather stations and safety monitors belong to the site, not to a Pier, because there's only one sky above your roof. When conditions turn unsafe, every Pier hears about it. What happens next depends on what each Pier is doing, which episode six explains.

> SCREEN: Choose New Observatory from the top bar, show the dialog, cancel. Then show the Pier selector.

> PAUSE: 20

## 6. A night with Galileo

> SCREEN: Montage, one clip for each step as it is described.

Here's the shape of a typical night. We'll cover each of these properly in later episodes.

First, you connect. Cameras and focusers that you've saved connect by themselves when you select a Pier, and one button in the top bar connects everything else configured for that Pier.

> PAUSE: 12

Second, you choose a target. You might open the Star Atlas, a live planetarium showing the sky over your site right now, and click on something. Or you might ask What's Up Tonight, which ranks deep-sky objects for the night, weighing how high they get, how long they stay up, the Moon, how well they fit your field of view, the forecast, and how much data you already have on them.

> SCREEN: Star Atlas, then What's Up Tonight results tiles.

> PAUSE: 20

Third, you get the telescope onto it and make sure it's really there. Goto and Centre slews the mount, takes a short picture, plate solves it, and corrects until the target is where you want it.

Fourth, you focus. The Focus screen steps the focuser through a range, measures the size of the stars at each position, fits a V-shaped curve, and moves to the bottom of the V.

> SCREEN: Focus screen with a completed V-curve.

> PAUSE: 16

Fifth, if you're polar aligning for the first time that night, the Solve screen has a polar alignment routine that tells you which way to turn the adjusters.

Sixth, you start guiding. Galileo drives PHD 2 and shows you the guide star, the error graph and the statistics.

Seventh, you image. You can press Capture and take frames by hand, with a live histogram and star measurements, and even stack them live on screen. Or you can build a session: a list of blocks that says slew here, focus, solve, take forty frames through this filter, change filter, take forty more, then park.

> SCREEN: Imaging screen, then a built session with several blocks.

> PAUSE: 24

Eighth, your frames file themselves. Every captured frame can go straight into the Library, renamed and sorted by object, filter and date.

Ninth, calibration. The Flats and Darks assistants take your calibration frames, and the Library links them to the lights they belong with, builds master frames, calibrates, and stacks.

> SCREEN: Library Images tree, then Library Sessions with resource indicators.

> PAUSE: 20

You can do all of this one step at a time, standing next to the telescope. Or you can plan several nights ahead, place sessions on a calendar, let Galileo schedule them around darkness, the Moon and your horizon, and have it stop, park the telescopes and close the roof when the weather turns.

## 7. The Dashboard

> SCREEN: Dashboard with timelines for two Piers.

When you open Galileo you land on the Dashboard. It's a one-screen answer to the question, what is my observatory doing?

Each Pier gets its own compact timeline, with lanes for the session, the mount, the meridian flip, guiding, plate solving, focusing and capture, where every box is one frame. Below the lanes is the guide error over time, and beside it a dot plot of recent guide error. Time runs left to right, and the right-hand edge is now.

> PAUSE: 20

So at a glance you can see whether a Pier is exposing, refocusing or has lost its guide star, and when that happened. Galileo records the last twelve hours in the background, whether or not you're looking.

At the bottom is a node health line for the computer itself: processor and memory use, free disk space, temperature where the computer reports it, and uptime. Watch the disk space. A night of frames needs somewhere to go. There are also buttons to restart or shut down the computer, which is handy for one that lives at the telescope. They ask first, and they're refused while a session is running.

> SCREEN: Highlight the node health line, then the Restart and Shut down buttons without pressing them.

> PAUSE: 16

## 8. Built-in help

> SCREEN: Imaging screen. Hover over a control to show the tooltip. Then press the question mark beside the title.

You don't need to memorise any of this. Galileo has help built in for every screen and every control, it works offline, and it matches the version you have installed.

There are several ways in. Hover over a control for a short description. Click into a field and press F 1 for the full entry. Click the question mark beside a screen's title. Or press Shift and F 1, then click any control, and Galileo explains it instead of doing it.

> SCREEN: Demonstrate Shift F1 and click Capture. Then search the help window for "dark".

> PAUSE: 28

The help window stays open while you work, with a topic tree on the left and a search box that looks across the whole application.

## 9. Where your data lives, and what to do when something goes wrong

> SCREEN: The View Log window with the level filter and search box.

Galileo keeps its settings, your observatories, your equipment and your image catalog in a single database in your user folders. Upgrading or uninstalling does not remove it.

Each run writes a log. The View Log button shows it, with a level filter, a search box and automatic refresh. If Galileo hits an unexpected error it saves a crash report, with passwords and tokens removed. There's also a watchdog you can turn on, which parks the mount, closes the dome and sends you an alert if Galileo stops responding.

> PAUSE: 16

For help from people, the speech-bubble button opens links to the community: ask a question, browse discussions, suggest a feature, or report a problem. The bug report form arrives with your version, operating system and current screen already filled in, and nothing is sent until you submit it yourself. There's also a Discord server.

## 10. Beyond the desktop

> SCREEN: Options, Plugins, Marketplace tab.

Galileo grows through plugins. From the Plugin Marketplace you can add variable-star planning and photometry, control of smart plugs and relay boards, support for particular power boxes, an all-sky camera viewer, and an extra plate solver.

> PAUSE: 16

There are also plugins that connect Galileo to the outside world. NodeConnect keeps several Galileo computers in step. WebConnect lets you operate the observatory from a web browser. MobileConnect serves apps for phones and tablets, with a virtual reality client in development. And an outreach mode lets visitors at a star party watch your live image on their own phones. These connection features are the newest and least tested part of Galileo, and we'll be frank about their state when we get to them.

> SCREEN: Options, Connect Link page, showing that it is off by default.

> PAUSE: 16

## 11. Who Galileo is for

> SCREEN: Three setups: a smart telescope, a backyard refractor, a multi-pier shed.

Let me describe three people, and see whether one of them is you.

The first owns a smart telescope and wants more control than the phone app gives. If your telescope offers Alpaca, Galileo can connect to it over your network, plan targets, run sessions and file the results in a proper library.

> PAUSE: 20

The second has a classic rig: an equatorial mount, a refractor or reflector, a cooled camera, a filter wheel, a focuser and a guide camera. For this person Galileo replaces several programs with one window: planetarium, planner, capture, focus, solving and library, working alongside PHD 2 for guiding.

> PAUSE: 20

The third runs a small observatory, perhaps with a roll-off roof, a weather station and more than one telescope. Galileo's Piers, shared safety monitoring, schedule and Dashboard are built with that person in mind. In fact Galileo's design is checked against the author's own setup: a roll-off roof shed with a weather station and rain sensor, two Seestar smart telescopes over Alpaca, and a small refractor on an OnStep mount over INDI.

> PAUSE: 20

You don't have to be any of these on day one. Start with one camera and one frame, and add pieces as you need them.

## 12. Words you will hear

> SCREEN: Glossary cards, one per term.

A few terms come up throughout the series, so here they are once.

A light frame is a picture of the sky. A dark is taken with the telescope covered, at the same exposure and temperature. A flat is a picture of an evenly lit surface, which records dust and darkening towards the corners. A bias is the shortest possible exposure with no light.

> PAUSE: 16

Plate solving means identifying the stars in a picture to learn exactly where it points. Guiding means correcting the mount continuously by watching a star. Dithering means shifting slightly between frames. Half-flux radius is Galileo's measure of star sharpness, where smaller is better.

> PAUSE: 16

And FITS is the image format astronomers use. It stores the picture together with a header recording the object, exposure, filter, camera and much more. Galileo works in FITS throughout. It can import the XISF format, converting it on the way in, but it doesn't write it.

> PAUSE: 16

## 13. Common questions

> SCREEN: Question cards, one at a time.

Before we finish, some questions people ask.

Do I need to replace everything I use now? No. Galileo works with PHD 2 for guiding and ASTAP for solving, and your frames are ordinary FITS files that any processing program can read. Galileo captures and organises. It stacks for a quick look, but your careful processing stays wherever you like to do it.

Will it work without the internet? The core work does. Capturing, focusing, guiding, local plate solving and the Library run on your own network. Weather advisories, online object lookups, downloads and cloud backup need a connection.

Does it send my data anywhere? Features that go online do so for a stated job, such as fetching a forecast, looking up an object name, downloading images or backing up to your own storage. The community and bug report buttons only open your browser, and you decide what to submit.

Can I try it beside my current software? Yes, but let only one program control a device at a time.

> PAUSE: 20

## 14. What to expect from your first week

> SCREEN: A simple five-step checklist on screen.

Here's how I'd approach the first week. On day one, install Galileo, create your observatory and explore the Star Atlas and Planning with nothing connected. Read some of the built-in help.

On day two, indoors and in daylight, connect your equipment or the simulators and confirm each device responds. Take a few frames with the cover on.

> PAUSE: 20

On your first clear night, keep it modest. Slew to a bright object, focus, plate solve and take a handful of frames. On the next, add guiding. After that, build your first short session and sit beside it while it runs.

> PAUSE: 20

If something fails along the way, write down what you were doing, save the log, and report it. A clear report from a real setup is the most useful thing an early user can give.

## 15. The rest of the series

> SCREEN: Title card listing episodes 2 to 11.

Here's what's coming.

Episode two covers installation and equipment setup. Episode three is the Star Atlas and planning. Episode four, a longer one, covers focusing, solving, guiding and imaging. Episode five is automation with sessions and scheduling. Episode six covers observatory safety and running several piers. Episode seven is the Library. Episode eight is plugins and the marketplace. Episode nine covers NodeConnect, WebConnect and outreach. Episode ten covers MobileConnect and the phone, tablet and headset clients. And episode eleven is for developers who want to write a plugin of their own.

> PAUSE: 16

If you're setting up for the first time, watch episode two next and follow along with your own equipment. If you're already installed, jump to whatever you need.

Thanks for watching, and clear skies.

> SCREEN: End card with the project address, wiki and Discord.

> PAUSE: 20
