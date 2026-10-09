<!-- order: 97 -->
# Library settings

Settings for the Library: where your images are kept, compression, cloud backup, calibration and downloading from smart telescopes. They are grouped on tabs: **General**, **Cloud Sync**, **Calibration** and **Smart Telescopes**. Press **Save** to keep your changes; **Reset to Defaults** puts the standard values back (without saving).

## General Settings

Where your files are and how they are handled.

## Source Path

The *incoming* folder: where new FITS (and XISF) files wait to be imported. **Load New** on the Library › Images screen imports from here.

## Repository Path

The folder where the Library keeps your organised image files. Galileo creates its folder structure here. **This must be set** for Auto-Save to Library on the Imaging screen to work.

## Temporary Files Folder

Where Galileo puts scratch files, such as frames waiting to be filed. Leave empty to use your system's temporary folder.

## Browse

Chooses a folder or file with a file dialog.

## Refresh on Startup

Carried over from the original AstroFiler settings and saved with the rest, but Galileo does not currently act on it — it has no effect yet.

## Save Modified Headers

When ticked, any change Galileo makes to a frame's header information is also written back into the FITS file itself.

## Reset to Defaults

Puts every setting on every tab back to its standard value. Nothing is saved until you press **Save**.

## FITS Compression

Lossless compression of FITS files to save disk space.

## Enable Compression

Automatically compresses new FITS files with lossless compression. Off by default.

## Algorithm

The compression method. Only FITS gzip level 2 is offered, which is compatible with programs such as Siril and gives the best results on floating-point data.

## Compression Level

From 1 (fastest) to 9 (smallest files). 6 is a good balance.

## Verify Compression

Checks each compressed file to confirm it matches the original, so no data is ever lost. Recommended.

## Minimum File Size

Files smaller than this many bytes are not compressed.

## External Tools

Programs Galileo launches for you.

## FITS Viewer

The program used to open frames when you double-click them or choose View. Leave empty to use your system's default.

## Suppress Warnings

Which confirmation messages to skip.

## Suppress Delete Warnings

When ticked, deleting a file no longer asks you to confirm.

## Cloud Sync

Back up the Library to the cloud.

## Cloud Vendor

The cloud service. Google Cloud Storage is supported.

## Bucket URL

The name of your Google Cloud Storage bucket, such as galileo-repository. Create one in the Google Cloud Console (Cloud Storage › Buckets › Create). Bucket names must be unique across all of Google Cloud.

## Auth File

The Google Cloud service-account key file (JSON) that lets Galileo use the bucket. Create a Service Account in the Cloud Console, give it the *Storage Object Admin* role, and download a JSON key.

## Sync Profile

How files are shared between your computer and the cloud: **Complete Sync** keeps all files in both places; **Backup Only** uploads everything but never downloads missing files; **On Demand** downloads files only when needed.

## Auto-cleanup Backed Files

When ticked, calibration files and uncalibrated light frames are deleted from local storage once they are safely backed up to the cloud, saving disk space. Master calibration frames and processed or stacked images are never deleted.

## Auto-Calibration

How the Library makes master calibration frames automatically.

## Min Files per Master

The fewest calibration frames needed to build a master frame, 2 to 100. More frames make a better master (3–10 is recommended).

## Show Progress Dialogs

Shows progress windows while masters are built. Turn off for unattended processing.

## iTelescope Configuration

Your account on iTelescope, a remote-telescope service, used by **Download** on the Images screen to fetch your calibrated files.

## iTelescope Username
<!-- keys: itelescope-configuration-username -->
Your iTelescope account name.

## iTelescope Password
<!-- keys: itelescope-configuration-password -->
Your iTelescope password, used to sign in over FTPS to download files.

## SFTP Server

An SFTP server you download images from (for example a telescope computer or a network drive), also used by **Download**.

## SFTP Username
<!-- keys: sftp-server-username -->
The account on the SFTP server.

## SFTP Password
<!-- keys: sftp-server-password -->
The account's password, kept in your operating system's keychain rather than in a settings file. Leave empty to use a key file or your SSH agent instead.

## Key file

A private key file to log in with, if you use one instead of a password. Optional.

## Remote folder

The folder on the server to search, including its sub-folders, for FITS files.

## SFTP Port
<!-- keys: sftp-server-port -->
The server's SFTP port. 22 is the standard.

## Only connect to servers already in known_hosts

When off, a server you have not connected to before is accepted and its fingerprint logged, which is fine on a home or observatory network. Turn it on for any server reached over the internet.
