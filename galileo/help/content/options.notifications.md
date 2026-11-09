<!-- order: 98 -->
# Notification settings

Where Galileo sends alerts when a session finishes, fails or is stopped for safety. Alerts always appear in the log; this page adds phone (ntfy), e-mail and text-message delivery. Changes are saved as you make them and apply from the next session. These channels run on this computer and need no phone app, so they are how you are alerted while away: the MobileConnect app only shows alerts while it is open and connected. If the Observatory has its own contact details, those recipients are used instead of the address and phone number here; everything else (server, login, gateway, which events) always comes from this page.

## Send phone alerts (ntfy)

Turns phone alerts on or off. They are sent through [ntfy](https://ntfy.sh), a free app for Android and iPhone that needs no account: Galileo makes one secure request from this computer and the app shows it as an ordinary notification, so it is the easiest way to be reached overnight. Set up: install ntfy on your phone, press **Generate topic** here, then in the app choose Subscribe to topic and enter the same topic, and press **Send test alert**. Safety aborts arrive as urgent alerts. The Observatory's contact choice does not apply to phone alerts, which go to whoever subscribes to the topic.

## Topic

The name that ties this computer to your phone's subscription: 1 to 64 letters, digits, `-` or `_`. **Anyone who knows the topic can read your alerts**, so use a long random one (press Generate topic) rather than something like `galileo`. Alerts are not sent while the topic is empty.

## Generate topic

Fills Topic with a new random name. Subscribe to it in the ntfy app afterwards; the previous topic stops reaching your phone.

## ntfy server

Where alerts are posted. Leave as `https://ntfy.sh` (the free public server) unless you run your own ntfy server.

## Access token

Only for a private ntfy server that requires login. Kept in your operating system's credential store, never in a settings file.

## Use e-mail as a backup

While on, e-mail alerts are sent only when the phone alert could not be sent (no internet, ntfy down), so you are not told twice. Turn off to receive both every time. Needs the e-mail address and server settings below; each event still follows the E-mail alerts list.

## Send test alert

Sends a test phone alert using what is currently in the fields, even if not yet saved, and reports success or the exact error. It does not use the e-mail backup, so a failure shows.

## Send e-mail alerts

Turns e-mail delivery on or off. With phone alerts set up and Use e-mail as a backup on, e-mail is sent only if the phone alert fails.

## E-mail address

Where e-mail alerts are sent.

## SMTP server

The outgoing mail server, for example `smtp.gmail.com`. Use the server your e-mail provider documents for sending mail.

## Port

The server's port: usually 587 for STARTTLS, 465 for SSL/TLS, 25 for none. Changing Security switches to that mode's usual port.

## Security

How the connection to the server is protected. Choose **STARTTLS** or **SSL/TLS** whenever your provider supports it; **None** sends your login unencrypted.

## Username

The login for the SMTP server. Leave blank if the server needs no login.

## Password

The login password (many providers require an app-specific password). It is kept in your operating system's credential store (Windows Credential Manager, macOS Keychain, Secret Service on Linux), never in a settings file. If no credential store is available it cannot be saved.

## From address

The sender shown on alerts. Leave blank to use the username, or the e-mail address.

## Send test e-mail

Sends a test message using what is currently in the fields, even if not yet saved, and reports success or the exact error.

## Send text-message alerts

Turns text-message delivery on or off.

## Phone number

The phone to text.

## SMS gateway

Most US carriers (AT&T, T-Mobile and soon Verizon) have shut down or are retiring their e-mail-to-SMS gateways, so this may not deliver; prefer phone alerts (ntfy). Texts go out as e-mail to your carrier's e-mail-to-SMS gateway, so this also needs the e-mail server settings above. Enter the gateway's domain (for example `vtext.com`, which sends to `<phone number>@vtext.com`) or an address using `{number}` for the phone number. Without a gateway no text is sent.

## Send test text

Sends a test text through the gateway and reports success or the error.

## Session complete

Alert when a session finishes. Each list (phone, e-mail, text) switches events on or off separately.

## Session error

Alert when a session stops on an error.

## Safety abort

Alert when a session or the watchdog stops equipment for safety reasons (weather, safety monitor, hang).

## Autofocus complete

Alert when an autofocus run finishes.

## Meridian flip

Alert when a meridian flip happens.

## Session message

Alert from a session's Notification block.
