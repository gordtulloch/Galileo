<!-- order: 91 -->
# Equipment settings

Settings that apply to the whole application. Each device's driver, server, port and poll interval are set on its own page under Equipment and saved per Pier.

## Enable watchdog

Turns the crash/hang watchdog on or off. While it is on, Galileo checks that it is still responding; if it is not for the whole timeout, the mount is parked and the dome closed so the equipment is left safe, and an alert is sent through Options > Notifications. Takes effect the next time Galileo starts.

## Watchdog timeout

How many seconds Galileo may go without responding before the watchdog acts (10–3600; the default is 300). Too short a value risks a false alarm during a slow operation. Takes effect the next time Galileo starts.

## Hold devices in the device service

Off by default. When on, a device you connect from an Equipment screen is built and held by the same device service the headless engine uses, so the safety guard and the remote-control surface find it, instead of only the screen that connected it. While it is on, Galileo also runs the engine inside this window, so the single-engine lock is held and the engine's local channel is available; if another engine is already running on this computer, this Galileo says so in its log and keeps its own devices. The screens look and work the same either way. It applies to devices connected from now on, and the engine part takes effect the next time Galileo starts; one already connected stays as it is, so disconnect and reconnect it after changing this. Turn it off again if a device will not connect.
