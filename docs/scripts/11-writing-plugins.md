# Episode 11: Plugins for Developers

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening

> SCREEN: A code editor beside Galileo with a custom plugin loaded.

Welcome to the last episode. This one is for people who write code. If your piece of equipment isn't supported, or you want a screen Galileo doesn't have, you can add it yourself without changing Galileo.

I'll assume you're comfortable with Python and know roughly what a class and an async function are. If that's not you, it's still worth watching to see what's possible.

## 2. The design principle

> SCREEN: Architecture diagram: domain core, ports, adapters, plugins.

Galileo is built in layers. The core logic, such as sessions, focusing, solving and safety, is plain Python that knows nothing about INDI, Alpaca or the user interface. It talks to abstract interfaces called ports. The INDI and Alpaca code are adapters that implement those ports.

A plugin registers against the very same ports. There is no second-class plugin interface bolted on the side. If the built-in code and your code come through the same door, that door has to be good.

> PAUSE: 13

## 3. Is a plugin the right tool?

> SCREEN: List: device backend, session block, solver, panel.

Write a plugin to support new hardware, add a plate solver, describe a power box, add a session block, or add a screen. Don't write one to fix a bug in Galileo or change an existing screen. Those belong in Galileo itself, and contributions are welcome.

> PAUSE: 10

## 4. The shape of a plugin

> SCREEN: Folder tree: plugin.toml, pyproject.toml, package folder.

A plugin is a ZIP with a manifest, called plugin dot toml, and a Python package. The package folder must have the same name as the plugin.

> PAUSE: 13

The manifest gives the name, version, the minimum and maximum plugin API versions it supports, the author, a one line description, the tier, first-party or third-party, and the entry point. The current plugin API version is 1.

> SCREEN: Show a complete plugin.toml.

> PAUSE: 26

## 5. The plugin class

> SCREEN: Minimal PluginBase subclass.

Your entry point subclasses PluginBase. Set a name, version, API version, and if you have a screen, a panel level and panel label. Then implement two methods.

Activate is called when the plugin is loaded and enabled. Register everything there. Deactivate is called when it's disabled, updated or unloaded. Release everything there: timers, threads, connections.

> PAUSE: 31

There are no constructor arguments, so do your setup in activate, not in init.

If activate raises an error, Galileo logs it, marks your plugin faulted, and carries on. That protects the user's session. It is not an excuse to skip your own error handling.

## 6. What the context gives you

> SCREEN: PluginContext method list.

Activate receives a context object. It is deliberately narrow.

It gives you registration methods for device backends, session block types, solver backends and switch profiles. It gives you settings, stored in Galileo's database under your plugin's name. It gives you the selected Observatory's location, or nothing if none is set. And it can show or hide your dockable pane.

> PAUSE: 18

There's also a way to request named core services. Be aware that today the normal loader grants none, so don't design around it without reading the guide.

## 7. Example one: a switch profile with no logic

> SCREEN: The WandererBox plugin profile file.

Start with the smallest useful plugin. Suppose your INDI power box works, but its driver uses its own property names instead of INDI's standard power interface. You don't need a panel or any communication code. You describe the mapping in a switch profile.

A profile has a name, the device names it may report, a signature of properties that must exist, channels for each port or heater, and sensors for readings.

> PAUSE: 31

Devices are matched by the signature, not the name, because two drivers can report the same name. Choose properties the driver always defines once connected. Dew heaters are shown from zero to a hundred percent, whatever scale the driver uses. Anything you don't map still appears under Other, so nothing is hidden from the user.

> SCREEN: Register the profile in activate; show it on the Switches page.

> PAUSE: 26

The whole WandererBox plugin is this and nothing else.

## 8. Example two: a device backend

> SCREEN: DeviceBackend subclass skeleton.

To support new hardware, subclass DeviceBackend. Implement connect, disconnect, an is connected property, capabilities and properties, plus whatever your device category needs. For a safety monitor, that includes saying whether it's safe. The easiest way to learn the exact surface is to read the existing INDI or Alpaca adapter for that category.

> PAUSE: 31

Then register it for its category in activate. From then on, Galileo can't tell it from a built-in one.

A lovely example of what's possible: a software safety monitor that looks at your all-sky camera, decides whether it's cloudy, and reports safe or unsafe like any physical sensor. If you build something that protects equipment, make it fail safe: when in doubt, report unsafe.

> SCREEN: The Kasa Switch adapter.

> PAUSE: 21

## 9. Example three: a solver

> SCREEN: SolverBackend subclass; the Skyshot plugin.

To add a plate solver, subclass SolverBackend with a stable key, a label, a check for whether it's available, a message explaining what's missing, and an async solve method that returns a result. Register it, and it appears in Options and on the Solve screen. A key that clashes with an existing solver is refused. The Skyshot plugin is the reference, including how to download large data files safely, with checksums.

> PAUSE: 31

## 10. Example four: a session block

> SCREEN: A dataclass with an async execute method.

A session block is any class with an async execute method, which receives the running session's context with its devices and services. Register it in activate.

> PAUSE: 21

Two cautions. The first registration of a name wins, so you can't replace a built-in block, and should choose a distinctive name. And at present, plugin blocks don't appear in the Sessions palette. They can be run, but a user can't yet drag one in. Check the guide for whether that has changed.

## 11. Adding screens

> SCREEN: Three screenshots: Science menu item, Equipment panel, top-level section.

Your panel level decides where a screen goes. Science puts it in the Science menu, as VSTarget does. Equipment followed by a category puts it on that equipment page, as the switch plugins do. Top gives you your own sidebar icon, as AllSkyCam does, and you can draw the icon so it follows the theme.

> PAUSE: 21

Implement build page to return your widget. If it raises, Galileo shows a placeholder and logs the error.

## 12. Settings pages, panes and the Dashboard

> SCREEN: AllSkyCam settings page, dock pane, Dashboard view.

Give an options label and a build options page method, and your plugin gets a gear on its tile. Give a dock label to offer a pane users can dock or float. Give a dashboard label to offer a view above the Pier timelines, which the user turns on with Publish on Dashboard. A dashboard view needs a settings page too.

> PAUSE: 26

Store settings through the context, never in your own files. Galileo keeps all configuration in its database.

## 13. Help for your screens

> SCREEN: A help folder with a Markdown file; F1 on the plugin screen.

Put Markdown in a help folder inside your package, named for your screen. Each second-level heading matches a control by its visible text, and the first paragraph under it becomes the hover text. Users get the same help experience as in Galileo itself, which is worth the half hour it takes.

> PAUSE: 26

## 14. Behaving well

> SCREEN: Checklist graphic.

Here are the rules that separate a good plugin from a nuisance.

Never block the user interface thread. Do network and file work off it, and do heavy calculation in Galileo's process pool.

Update the interface only from the interface thread. Events on Galileo's event bus are delivered on whichever thread published them, so pass them across safely.

> PAUSE: 13

Communicate with the rest of Galileo through the event bus and the context. Don't import the INDI or Alpaca adapters, or reach into the user interface's internals.

A disabled plugin must be inert. Stop timers and network activity when disabled, and restart when enabled.

Assume your plugin may be updated in a running application. Don't keep important state in module-level variables, and stop your threads in deactivate.

> PAUSE: 18

## 15. Testing

> SCREEN: Terminal running pytest for a plugin.

Test with a real PluginManager. Load your plugin, check the registration really happened, disable it and check it's inert, then unload it. Use simulated devices, such as the INDI or ASCOM simulators, before real ones. And test the unhappy paths: unplug things, kill the server, give it nonsense.

> PAUSE: 31

## 16. Packaging and publishing

> SCREEN: Running build_plugins.py, then Install from file.

The first-party plugins live in the Galileo-Plugins repository, which has a build script that packs each plugin into a ZIP. Install your ZIP with Install from file to try it exactly as a user would.

> PAUSE: 26

In that repository, publishing to the Marketplace happens automatically when changes reach the main branch, so a contribution goes through a pull request and review. Increase the version number for each release, and users will see Update available. You can include an icon at the root of the ZIP.

## 17. Licensing and trust

> SCREEN: GPL logo.

Galileo is licensed under the GPL, version 3 or later. Because a plugin runs inside the same process, it is very likely a combined work, and needs a GPL-compatible licence to be distributed with Galileo. If you wrap another program or download data, credit it, and make its licence terms visible to the user, as the Skyshot plugin does.

> PAUSE: 13

And remember that users are trusting you with their equipment and their computer, because there is no sandbox. Say clearly what your plugin does and what it hasn't been tested with.

## 18. Where to read more

> SCREEN: The wiki developer guide and the design documents folder.

The Plugin Developers Guide is in the wiki. The software design document explains the architecture. For a substantial plugin, follow VSTarget's example and write its own scope, requirements, design and traceability documents. AllSkyCam is the best example to copy for a self-contained screen plugin, and Kasa Switch or the generic relay for a minimal device.

> PAUSE: 26

## 19. A walk-through: your first plugin

> SCREEN: Create each file as narrated.

Let's put it together with the smallest plugin that shows something. Make a folder called hello sky. Inside it, create the manifest, and a package folder with the same name containing one Python file.

> PAUSE: 39

In the manifest, give the name hello sky, a version of one point zero, minimum and maximum API of one, your name, a description, tier third-party and the entry point.

> PAUSE: 39

In the Python file, define a class that subclasses PluginBase. Give it a name, version and API version, a panel level of top and a panel label. Write activate to store the context, and deactivate to let it go. In build page, return a simple label.

> PAUSE: 58

Zip it with the manifest at the root of the archive. In Galileo, choose Install from file. Your icon appears in the sidebar.

> SCREEN: Install and show the new section.

> PAUSE: 39

## 20. Making it useful

> SCREEN: Extend the label to show site information.

Now make it do something. Ask the context for the site location, and show the latitude and longitude, handling the case where none is set. Add a settings page with one option, and store it through the context. Add a help file so F 1 works.

> PAUSE: 52

Then bump the version, rebuild the ZIP and install over the top. Watch it update without restarting. If it keeps behaving like the old version, you're probably holding something in a module or a thread that you didn't release.

> PAUSE: 26

## 21. Working with asynchronous code

> SCREEN: An async connect method with a timeout.

Device operations are asynchronous. Don't block inside them with ordinary sleeps or slow library calls; hand blocking work to a thread. Put a timeout on everything that talks to a network, and turn failures into clear messages that say what the user can do. A device that hangs for ever is far worse than one that reports an error.

> PAUSE: 31

For heavy calculation that holds Python's global interpreter lock, use Galileo's shared process pool, with functions defined at module level so they can be sent to another process.

> PAUSE: 21

## 22. Common mistakes

> SCREEN: Checklist of mistakes.

A few to avoid. A package folder whose name doesn't match the plugin. Doing work in the constructor. Writing your own settings file. Leaving timers running after being disabled. Importing internals that will change under you. Assuming a device always answers. And testing only the case where everything works.

> PAUSE: 26

## 23. Reading an existing plugin

> SCREEN: AllSkyCam source tree, file by file.

The fastest way to learn is to read one. AllSkyCam is laid out cleanly. One file holds the settings and their limits. One talks to the camera server. One decides whether it's daytime. One keeps a memory-limited set of recent images. One runs the fetch cycle and never raises an error into the application. A service owns the timer and worker thread, and the interface only displays what the service holds.

> PAUSE: 52

That separation is worth copying. The logic can be tested without any windows, the interface stays thin, and stopping the service makes the whole plugin inert. Its tests include an end to end run against a pretend camera server on the same computer.

> SCREEN: Run the AllSkyCam tests.

> PAUSE: 39

## 24. Designing for the user

> SCREEN: A settings page with a Test connection button.

Finally, think about the person at the telescope. Offer a way to test a connection before saving it. Say what went wrong in plain words and what to try. Keep working in the red night theme, which means not relying on colour alone. Default to doing nothing: never move or switch hardware just because your screen was opened. And ask before anything that can't be undone.

> PAUSE: 26

## 25. Contributing back

> SCREEN: The Galileo-Plugins repository and the contributing guide.

If your plugin would help others, share it. Read the contributing guide, which includes the contributor agreement and the test conventions. Include tests, help files and a changelog, and say honestly which hardware you've tried it on. An untested path clearly labelled is useful. An untested path described as working is a trap for someone at two in the morning.

> PAUSE: 26

## 26. Closing the series

> SCREEN: Montage from the whole series.

That's the series. We've installed Galileo, connected an observatory, planned nights, focused, solved, aligned, guided and imaged, organised the results, added plugins, reached out to browsers, phones and the public, and now looked under the hood.

Galileo is young, and it improves with use. Report what breaks, share what works, and if you build something, tell the community. Thank you for watching, and clear skies.

> PAUSE: 13
