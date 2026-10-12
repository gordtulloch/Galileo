<!-- order: 98 -->
# Notification settings

Where Galileo sends alerts when a session finishes, fails or is stopped for safety. Alerts always appear in the log; this page adds e-mail and text-message delivery. Changes are saved as you make them and apply from the next session. If the Observatory has its own contact details, those recipients are used instead of the address and phone number here; everything else (server, login, gateway, which events) always comes from this page.

## Send e-mail alerts

Turns e-mail delivery on or off.

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

Texts go out as e-mail to your carrier's e-mail-to-SMS gateway, so this also needs the e-mail server settings above. Enter the gateway's domain (for example `vtext.com`, which sends to `<phone number>@vtext.com`) or an address using `{number}` for the phone number. Without a gateway no text is sent.

## Send test text

Sends a test text through the gateway and reports success or the error.

## Session complete

Alert when a session finishes. Each list (e-mail, text) switches events on or off separately.

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
