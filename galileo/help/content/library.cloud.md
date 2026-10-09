<!-- order: 76 -->
# Cloud

Cloud backs up your repository to cloud storage (Google Cloud Storage) and keeps it in step with your local files. Set up the bucket and credentials in Options › Library › Cloud Sync first. The box at the top shows what is currently configured.

Use **Analyze** first to match what is already in the cloud to your local catalog, then **Sync** to move files according to your Sync Profile.

## Current Configuration

The cloud vendor, bucket, authentication file and sync profile currently set up.

## Configure

Opens Options › Library to change the cloud settings.

## Analyze

Downloads a listing of the files in your cloud bucket and compares it with the local catalog, then records the cloud address of every file found in both places. It does not move any files. It can take several minutes with many files.

## Sync

Moves files to and from the cloud according to the **Sync Profile** in Options: *Complete Sync* keeps every file both locally and in the cloud; *Backup Only* sends everything to the cloud and never downloads missing files; *On Demand* downloads files only when they are needed.
