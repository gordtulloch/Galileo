<!-- order: 97 -->
# Connect Link

The encrypted link that other Galileo computers, phones, tablets and browsers use to reach this one. It is **off until you turn it on**, and even then it only listens while an installed plugin that needs it (NodeConnect, MobileConnect or WebConnect) is running. While it is off nothing listens and nothing is advertised on your network. Turning it off closes everything at once but keeps your paired devices, so turning it on again needs no new pairing.

## Enable Connect Link

Turns the link on or off. Turning it off closes the listener and every open connection and stops advertising this computer on the network. Your paired devices are kept.

## Port

The network port the link listens on, 1024 to 65535. The default is 8765. Changing it restarts the listener when you press **Apply**; devices already paired find this computer again by its address.

## Pairing request lifetime

How long a pairing request waits for you, and then how long the device has to collect its permission once you approve it. 30 seconds to an hour; the default is five minutes.

## Keep the audit log for

How many days Connect Link keeps its record of what each device did (requests, refusals, who opened an outreach event). Older entries are deleted each day. The log never holds a password, token or secret.

## Advertise on the network

Lets other computers on your network find this one by name instead of by typing its address. Only the computer's name, port and role are announced, never a secret, and finding it does not let anyone pair with it. Changing this restarts the listener when you press **Apply**.

## Apply

Saves the settings above and restarts the listener if the port or advertising changed.

## Certificate fingerprint

The fingerprint of this computer's certificate. A device you pair with remembers it and refuses to talk to anything else, so it is how a device knows it has reached the right computer. You can compare it with the one the device shows.

## Approve…

Opens the request selected in **Pairing requests**. Check that the code on the device matches the code in the list, tick the permissions to give it (view, control, data transfer; settings access is left unticked), and press OK. The device then collects its permission once.

## Reject

Refuses the selected pairing request.

## Revoke

Stops the selected device at once, including any connection it has open. The device stays in the list marked revoked; **Delete** removes it.

## Delete

Removes the selected paired device. It will have to pair again.
