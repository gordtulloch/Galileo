<!-- order: 91 -->
# Equipment settings

Settings that apply to the whole application. Each device's driver, server, port and poll interval are set on its own page under Equipment and saved per Pier.

## Enable watchdog

Turns the crash/hang watchdog on or off. While it is on, Galileo checks that it is still responding; if it is not for the whole timeout, the mount is parked and the dome closed so the equipment is left safe, and an alert is sent through Options > Notifications. Takes effect the next time Galileo starts.

## Watchdog timeout

How many seconds Galileo may go without responding before the watchdog acts (10–3600; the default is 300). Too short a value risks a false alarm during a slow operation. Takes effect the next time Galileo starts.
