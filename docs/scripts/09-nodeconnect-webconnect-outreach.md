# Episode 9: NodeConnect, WebConnect and Outreach

Target running time: 30 minutes. Lines beginning with `>` are production directions and are not narrated.

## 1. Opening, and an honest word

> SCREEN: Diagram: Master computer in the centre; spoke computers, browsers, phones around it.

Welcome back. This episode is about reaching beyond one computer: keeping several Galileo computers in step, operating your observatory from a web browser, getting alerts, and sharing your live image with the public.

First, honesty. These are the youngest parts of Galileo. They've been developed and tested largely in software. NodeConnect has not yet been tested between two real computers on a real network. WebConnect is an early build with only some of its screens, and has not been proven in real browsers. Treat what you see as a preview, check the release notes for your version, and don't leave unattended equipment depending on them.

> PAUSE: 15

## 2. The vocabulary

> SCREEN: Highlight Master, then spokes.

One computer is the Master. This is usually the observatory computer. Other Galileo computers paired with it are spokes. A computer is a spoke or a Master, never both, and one with neither is simply standalone.

Browsers and phone apps also connect to the Master. And they all arrive through the same door, called Connect Link.

> PAUSE: 10

## 3. Connect Link

> SCREEN: Options, Connect Link.

Connect Link is Galileo's encrypted network link. It's off until you turn it on, and even then it listens only while an installed plugin that needs it is running. While it's off, nothing listens and nothing is announced on your network.

Open Options, Connect Link and enable it. The default port is 8765.

> SCREEN: Enable Connect Link and Apply.

> PAUSE: 21

Listen on chooses the network address. Automatic is usually right, but a computer with a VPN or virtual network adapters can pick the wrong one. The symptom is that a phone can't connect, and the status line shows an address that isn't your home network. Choose your real address from the list. Galileo will not listen on every interface at once.

> PAUSE: 13

You can set how long a pairing request waits, which is five minutes by default, how long the audit log is kept, and whether this computer announces itself so others can find it by name. The announcement contains the name, port and role, never a secret.

Note the certificate fingerprint. A device that pairs remembers it and will talk to nothing else.

> SCREEN: Highlight the fingerprint.

> PAUSE: 13

## 4. Pairing and permissions

> SCREEN: Pairing requests list with a six-digit code. Press Approve.

Every device must be approved by a person. The device asks to pair, a short code appears on both, and you compare them. If they match, press Approve and choose what it may do: view, control, or transfer data. Access to settings is left unticked.

> PAUSE: 26

If the codes don't match, or you didn't start the request, reject it.

Revoke cuts a device off immediately, including any open connection. Delete removes it, so it would have to pair again. Turning Connect Link off closes everything but remembers your paired devices.

> PAUSE: 13

One more boundary: this is designed for your own network, or a VPN you run yourself. Galileo provides no cloud relay. Do not forward its port to the open internet.

## 5. NodeConnect: what it does

> SCREEN: Two computers side by side.

Suppose you set up everything carefully on the observatory computer, then want the same observatories, piers, equipment and options on your laptop. NodeConnect does that, and can also send your images home.

Install nodeconnect from the Marketplace on both computers. Enable Connect Link on the Master. Open NodeConnect's settings with the gear on its tile.

> SCREEN: Install on both and open settings.

> PAUSE: 23

## 6. Pairing a spoke

> SCREEN: Spoke: enter Master address, press Pair with Master. Master: approve.

On the spoke, enter the Master's address and press Pair with Master. Compare the codes on the two screens and approve on the Master. The spoke synchronises at once, then every few minutes, and Sync now does it on demand.

> PAUSE: 31

When something changes on the Master, it tells the spokes, which fetch it, so changes usually arrive within seconds.

## 7. What is shared, and conflicts

> SCREEN: Table: shared, and kept local.

Equipment profiles and most options are shared. Settings that only make sense on one computer stay there, and passwords and keys are not shared unless you choose otherwise.

> PAUSE: 13

If the same record was edited on both computers, the later edit wins, and the other value is kept so you can recover it. Changes that arrive while a session is running wait until it finishes, so a synchronisation never changes your equipment underneath an exposure.

Be aware of two limits. Two image libraries that grew separately are not merged. And both computers need compatible versions of Galileo; a spoke with an older database waits and tells you so.

> PAUSE: 13

## 8. Recent syncs and undo

> SCREEN: Recent syncs list. Select one. Show Undo this sync.

Recent syncs lists what each pass did: records added, changed or deleted, and anything that failed. Undo this sync puts back what that pass replaced or deleted on this computer. Restored records then synchronise like any other edit. Keep reports sets how many are remembered.

> PAUSE: 26

Before your first synchronisation, back up the database file on both computers. That's good advice with any tool that copies settings between machines.

## 9. Sending images home

> SCREEN: Image transfer settings with a time window.

A spoke can send its images to the Master in the background. You can limit transfers to a time window, such as overnight. Each image is verified on arrival before being marked as held by the Master. A pause in capturing starts a transfer soon after your frames are taken.

Removing local copies once the Master has them is off by default. If you turn it on, the spoke keeps the catalog entry and thumbnail, and fetches the picture back when you open it, provided the Master can be reached.

> PAUSE: 23

NodeConnect can also notify you if synchronising keeps failing, a pairing request is waiting, or a conflict was resolved.

## 10. Notifications

> SCREEN: Options, Notifications.

Notifications are part of Galileo itself, not of these plugins, and they're how you find out something happened when you're not looking.

The easiest method is a phone alert through ntfy, a free app that needs no account. Install it on your phone. In Galileo, press Generate topic, subscribe to that same topic in the app, and press Send test alert. Anyone who knows your topic can read your alerts, so keep the long random one.

> SCREEN: Generate topic, subscribe on phone, send test.

> PAUSE: 31

E-mail can be a backup, used only when the phone alert fails, or you can receive both. Text messages through carrier gateways are offered, but many carriers have shut those down.

Choose which events alert you: session complete, session error, safety abort, autofocus complete, meridian flip, and messages from a session's Notification block. Then test each channel in daylight.

> PAUSE: 18

## 11. WebConnect: the idea

> SCREEN: A laptop, a tablet and a Chromebook showing the same page.

WebConnect lets you watch and operate a running observatory from a web browser, with nothing to install on the device. The principle is operate, don't configure. A browser can never change equipment profiles, observatories, safety rules, options or plugin settings.

Losing the connection or closing the tab never stops imaging. The exception is a movement you're holding down, which stops when you let go or the link drops.

> PAUSE: 13

## 12. What's there today

> SCREEN: WebConnect Pier screen, then Camera, Focus, Solve and Polar tabs.

The sign-in and pairing, the live updates and the first operating screens are built, including camera, focus and solve views with pictures, and a polar alignment page. The full set of screens is not finished.

The goal is everything you'd do during a night: see every Pier's timeline, connect devices, capture, find and centre, solve, focus, guide, handle a meridian flip, run sessions, respond to safety events, and stop everything.

> PAUSE: 26

If the live connection drops, the page says so, shows how old its information is, and disables operations, though stop, park and close dome can still be attempted.

## 13. Installing and approving a browser

> SCREEN: Install webconnect, open its settings.

WebConnect runs on the Master. It's designed to be hosted in two ways. On a general Windows, Mac or Linux computer, install the webconnect plugin, and it runs its own secure web server. On Astroberry, it's designed to run as a service behind Astroberry's web server, installed from a package repository.

> PAUSE: 18

To sign in, open the address in a browser and ask to connect, compare the codes, and approve the browser on the Master, on WebConnect's settings page. There are no usernames or passwords: the approved browsers are the sign-ins, and you can revoke any of them. Expect a browser warning about a certificate your own computer issued, and check you're really connecting to your own machine before accepting it.

> SCREEN: Approve a browser.

> PAUSE: 26

## 14. Viewers, operators and the control lease

> SCREEN: Two browsers; one holds control.

Each browser is either a Viewer, which sees everything and changes nothing, or an Operator. Only one controller can drive a Pier at a time, using a control lease shared by the desktop, the apps and browsers, so two people can't give your mount conflicting orders. Any number can watch. Destructive actions ask for confirmation, and what's done remotely is recorded in an audit log.

> PAUSE: 18

The same safety checks apply as at the desktop. A browser can acknowledge a safety event, but cannot switch off the safety monitor or override a mount limit.

## 15. Polar alignment from the mount

> SCREEN: Polar tab on a tablet beside a mount.

One screen worth showing: the Polar tab. Press Start, and the three measurement solves run. Then you get the error as a large number, green under one arcminute, amber under five and red above, instructions for each adjuster, the target plot and a trend chart. Hold a tablet at the mount and turn the knobs. As of this recording it has not been tried on a real mount, so check its answer against the desktop.

> PAUSE: 31

## 16. Several computers, one address

> SCREEN: Browser showing Piers from two computers.

The design is that, with NodeConnect, a browser talks only to the Master and sees the Piers of paired spokes through it, where each spoke has allowed that. This relaying is not finished in WebConnect, so don't plan around it yet.

> PAUSE: 13

## 17. Outreach

> SCREEN: A star party: people holding phones showing an image.

Outreach is for star parties and public events. Visitors scan a code with their phone and watch your live image. They install no app, make no account, and can control nothing. They see only the Observatory and Pier name and a picture with no file details, so your location and equipment settings aren't exposed.

The ways visitors join are supplied by the connection plugins, so at least one has to be installed and report that it's ready. The visitor side is still maturing. Rehearse the whole thing at home before an audience arrives.

> PAUSE: 13

## 18. Setting up an event

> SCREEN: Options, Outreach.

Connect Link must be on. Open Options, Outreach.

Enter the name of your guest Wi-Fi and its passphrase, which is kept in your system's keychain. Enter the allowed network range. Only private address ranges are accepted, so nothing from the internet can join. Use a separate guest network, not the one your equipment is on.

> PAUSE: 21

Set the default duration, a guest limit, and image size and quality, where smaller is kinder to a busy network. Tick which Piers to offer and which ways of joining, then Save.

> SCREEN: Fill in and Save.

> PAUSE: 21

## 19. Running the event

> SCREEN: Press Open event. Show the Event display with codes.

Choose how long, and press Open event. It refuses, and tells you why, if something is missing. The Event display shows a code for the guest Wi-Fi and one for each way of joining. Put it on a screen or print it.

> PAUSE: 26

Extend adds thirty minutes. Eject all guests disconnects everyone but leaves the event open. New secret replaces the codes if one has travelled further than you meant. End event shuts it down. Nothing about an event is saved, and restarting Galileo ends it.

A live stack on a bright object makes a wonderful show: the picture visibly improves while people watch.

> SCREEN: Live stack updating on a visitor's phone.

> PAUSE: 26

## 20. A safe way to try these features

> SCREEN: Checklist graphic.

Because these are early features, here's a sensible way in. First, back up the database on every computer involved. Second, try them with simulated devices. Third, test with the telescope disconnected from anything that can move into something. Fourth, supervise real use until you've seen it behave, including what happens when you pull the network cable.

> PAUSE: 26

Pulling the cable is a good test. Imaging on the observatory computer should carry on. Any held motion should stop. The remote view should tell you it's no longer live.

## 21. A worked example: laptop and observatory

> SCREEN: Perform each step as narrated.

Imagine an observatory computer in the shed and a laptop indoors. The shed computer is the Master, with your equipment set up. Give both computers names you can recognise.

> PAUSE: 15

Enable Connect Link on the shed computer. Install nodeconnect on both. Pair the laptop, approving it in the shed, or over your remote desktop. Watch the first synchronisation, then open Recent syncs and read what changed.

> PAUSE: 52

Now edit something small on the Master, such as a filter or telescope description, and watch it reach the laptop. Then try Undo, so you know what it does before you ever need it.

> PAUSE: 39

## 22. Network basics

> SCREEN: Diagram: router, equipment network, guest network.

All of these depend on a sound network. Give the Master a fixed address on your router, so saved addresses stay valid. Make sure Wi-Fi reaches the observatory, or run a cable. Allow Galileo's port through the Master's firewall on private networks only.

> PAUSE: 21

Keep guests on a separate network with no route to your equipment. If you want access from away from home, use a VPN you trust, and never expose the port directly.

> PAUSE: 13

## 23. Planning a public night

> SCREEN: Star party footage.

For outreach, a little preparation goes a long way. Rehearse in daylight with two phones. Print the codes large. Choose bright, showy targets such as the Moon, a globular cluster or the Orion Nebula. Use live stacking so people see the image build. Tell visitors what they're looking at and how far its light has travelled. Keep cables out of walkways, and keep your control screen facing away from the crowd.

> PAUSE: 39

When it's over, end the event. If a code was photographed and shared, it stops working once the event ends.

## 24. Common questions

> SCREEN: Question cards.

Do I need NodeConnect to use the phone app? No. A single computer is simply a Master with nothing else attached.

If the Master goes down, what happens to a spoke? It carries on as its own Galileo and keeps imaging. You just can't reach it by way of the Master, and syncing resumes later.

> PAUSE: 13

Can two people operate at once? They can watch at once. Only one at a time holds control of a Pier.

Can I see FITS files in the browser? The browser shows previews prepared on the observatory computer. Downloading a full frame is a deliberate action.

> PAUSE: 13

Is this a remote desktop? No. It's a separate interface built for operating. If you need every desktop screen from far away, a remote desktop tool over a VPN remains the straightforward answer, and the two can happily coexist.

Will it manage the operating system? No. On Astroberry, drivers, updates, Wi-Fi and backups stay in Astroberry Manager.

> PAUSE: 13

## 25. Troubleshooting the links

> SCREEN: Connect Link status line and audit settings.

If a device can't connect, check that Connect Link is enabled, that a plugin needing it is installed and running, and that the status line shows your real network address. Check both devices are on the same network, and that a firewall or guest isolation isn't in the way.

> PAUSE: 21

If pairing times out, start again and approve within five minutes. If a spoke says it's waiting, it may be a session running, or versions that don't match. And if a plugin's page is blank, update it, restart, and read the log.

> PAUSE: 21

## 26. Wrap-up

To sum up: Connect Link is the door, and it's shut until you open it. Every device is approved by you. NodeConnect shares settings and images between computers. WebConnect operates from a browser. Outreach lets the public watch and nothing more. Next episode: the apps for phones, tablets and headsets. Clear skies.

> PAUSE: 10
