# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""
galileo.commands.cloud_sync - Command line utility for cloud synchronization

This script performs cloud synchronization operations using the configured sync profile.
It can perform backup sync, complete sync, or analyze cloud storage from the command line.

Usage:
    python -m galileo.commands.cloud_sync [options]

Options:
    -h, --help       Show this help message and exit
    -v, --verbose    Enable verbose logging
    -c, --config     Path to configuration file (default: library.ini in the Galileo config folder)
    -p, --profile    Override sync profile (backup|complete)
    -a, --analyze    Only analyze cloud storage, don't sync
    -y, --yes        Skip confirmation prompts (auto-confirm)

Sync Profiles:
    backup      Upload local files to cloud (one-way backup)
    complete    Bidirectional sync (download missing + upload new)

Requirements:
    - library.ini configuration file (Options > Library) with cloud settings
    - Valid Google Cloud Storage credentials
    - Configured bucket URL and repository path

Example:
    # Sync using configured profile
    python -m galileo.commands.cloud_sync
    
    # Backup sync with verbose output
    python -m galileo.commands.cloud_sync -p backup -v
    
    # Complete sync with auto-confirm
    python -m galileo.commands.cloud_sync -p complete -y
    
    # Analyze cloud storage only
    python -m galileo.commands.cloud_sync -a
"""

import sys
import os
import argparse
import logging
import threading
import time
import itertools


from galileo.commands._common import get_log_path, load_config

def setup_logging(verbose=False):
    """Setup logging configuration"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(get_log_path(), mode='a', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def get_cloud_config(config):
    """Extract cloud configuration from config file"""
    try:
        cloud_config = {
            'bucket_url': config.get('DEFAULT', 'bucket_url', fallback=''),
            'auth_file_path': config.get('DEFAULT', 'auth_file_path', fallback=''),
            'sync_profile': config.get('DEFAULT', 'sync_profile', fallback='complete')
        }

        # Validate required settings
        if not cloud_config['bucket_url']:
            raise ValueError("Bucket URL not configured. Please set 'bucket_url' in the library settings (Options > Library)")

        if not cloud_config['auth_file_path']:
            raise ValueError("Authentication file path not configured. Please set 'auth_file_path' in the library settings (Options > Library)")

        if not os.path.exists(cloud_config['auth_file_path']):
            raise ValueError(f"Authentication file not found: {cloud_config['auth_file_path']}")

        return cloud_config

    except Exception as e:
        raise ValueError(f"Invalid cloud configuration: {e}")

def validate_bucket_access(cloud_config):
    """Validate that we can access the cloud bucket"""
    from galileo.library.services.gcs import _get_gcs_client

    try:
        # Extract bucket name
        bucket_url = cloud_config['bucket_url']
        if bucket_url.startswith('gs://'):
            bucket_name = bucket_url.replace('gs://', '').rstrip('/')
        else:
            bucket_name = bucket_url.rstrip('/')

        # Test connection
        auth_info = {'auth_string': cloud_config['auth_file_path']}
        client = _get_gcs_client(auth_info)
        bucket = client.bucket(bucket_name)

        # Try to list objects to test access
        list(bucket.list_blobs(max_results=1))

        logging.info(f"Successfully validated access to bucket: {bucket_name}")
        return True

    except Exception as e:
        raise Exception(f"Failed to access cloud bucket: {e}")

def perform_analysis(cloud_config):
    """Perform cloud storage analysis"""
    from galileo.library.services.gcs import list_gcs_bucket_files
    from galileo.library.database import setup_database; from galileo.library.models import fitsFile

    logging.info("Starting cloud storage analysis...")

    # Setup database
    setup_database()

    # Extract bucket name
    bucket_url = cloud_config['bucket_url']
    if bucket_url.startswith('gs://'):
        bucket_name = bucket_url.replace('gs://', '').rstrip('/')
    else:
        bucket_name = bucket_url.rstrip('/')

    # Get cloud file list (this can take a long time; show user activity)
    auth_info = {'auth_string': cloud_config['auth_file_path']}

    cloud_files = None
    listing_error = None

    def _list_worker():
        nonlocal cloud_files, listing_error
        try:
            cloud_files = list_gcs_bucket_files(bucket_name, auth_info)
        except Exception as e:
            listing_error = e

    worker = threading.Thread(target=_list_worker, daemon=True)
    worker.start()

    if sys.stdout.isatty():
        spinner = itertools.cycle(["|", "/", "-", "\\"])
        start = time.time()
        while worker.is_alive():
            elapsed = int(time.time() - start)
            sys.stdout.write(f"\r{next(spinner)} Downloading file listing from cloud... ({elapsed}s)")
            sys.stdout.flush()
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
    else:
        logging.info("Downloading file listing from cloud (this may take a while)...")
        worker.join()

    if listing_error is not None:
        raise listing_error
    if cloud_files is None:
        cloud_files = []

    logging.info(f"Found {len(cloud_files)} files in cloud storage")

    # Get database statistics
    total_db_files = fitsFile.select().count()
    files_with_cloud_url = fitsFile.select().where(
        (fitsFile.fitsFileCloudURL.is_null(False)) &
        (fitsFile.fitsFileCloudURL != "")
    ).count()
    files_without_cloud_url = total_db_files - files_with_cloud_url

    # Report analysis
    print(f"\n{'='*60}")
    print("CLOUD SYNC ANALYSIS REPORT")
    print(f"{'='*60}")
    print("Configuration:")
    print(f"  Bucket URL: {cloud_config['bucket_url']}")
    print(f"  Sync Profile: {cloud_config['sync_profile']}")
    print(f"  Auth File: {cloud_config['auth_file_path']}")
    print("\nCloud Storage:")
    print(f"  Files in bucket: {len(cloud_files)}")
    print(f"  Total size: {sum(f.get('size', 0) for f in cloud_files):,} bytes")
    print("\nLocal Database:")
    print(f"  Total FITS files: {total_db_files}")
    print(f"  Files with cloud URLs: {files_with_cloud_url}")
    print(f"  Files without cloud URLs: {files_without_cloud_url}")
    print("\nSync Status:")
    if cloud_config['sync_profile'] == 'backup':
        print(f"  Backup Sync: {files_without_cloud_url} files ready to upload")
    elif cloud_config['sync_profile'] == 'complete':
        print(f"  Complete Sync: {files_without_cloud_url} files ready to upload")
        print("  Complete Sync: Analysis of missing local files requires sync operation")
    print(f"{'='*60}")

def perform_sync(cloud_config, sync_profile, auto_confirm=False):
    """Perform the actual sync operation"""
    from galileo.library.database import setup_database

    logging.info(f"Starting {sync_profile} sync...")

    # Setup database
    setup_database()

    # Get repository path
    config = load_config()
    repo_path = config.get('DEFAULT', 'repo', fallback='')

    if not repo_path or not os.path.exists(repo_path):
        raise ValueError("Repository path is not configured or does not exist")

    # Confirmation prompt
    if not auto_confirm:
        operation_desc = {
            'backup': f"Backup Sync: Upload local files to {cloud_config['bucket_url']}",
            'complete': f"Complete Sync: Bidirectional sync with {cloud_config['bucket_url']}",
            'ondemand': f"On Demand Sync: Upload and delete soft-deleted files to {cloud_config['bucket_url']}"
        }

        print(f"\nAbout to perform: {operation_desc.get(sync_profile, sync_profile)}")
        print(f"Repository: {repo_path}")

        response = input("Continue? (y/N): ").strip().lower()
        if response != 'y':
            print("Operation cancelled.")
            return

    # Create a minimal cloud sync dialog for command-line use
    class CommandLineProgress:
        """Simple progress callback for command-line operations"""
        def __init__(self):
            self.current = 0
            self.total = 0
            self.last_percent = -1

        def update(self, current, total, message=""):
            self.current = current
            self.total = total if total > 0 else 1
            percent = int((current / self.total) * 100)

            if percent != self.last_percent or message:
                if message:
                    print(f"[{percent:3d}%] {message}")
                else:
                    print(f"[{percent:3d}%] Processing... ({current}/{self.total})")
                self.last_percent = percent

    # Perform sync based on profile
    try:
        if sync_profile == 'backup':
            perform_backup_sync_cli(cloud_config, repo_path)
        elif sync_profile == 'complete':
            perform_complete_sync_cli(cloud_config, repo_path)
        elif sync_profile == 'ondemand':
            perform_ondemand_sync_cli(cloud_config, repo_path)
        else:
            raise ValueError(f"Unknown sync profile: {sync_profile}")

        logging.info(f"{sync_profile.capitalize()} sync completed successfully")

    except Exception as e:
        logging.exception(f"Sync operation failed: {e}")
        raise

def perform_backup_sync_cli(cloud_config, repo_path):
    """Perform backup sync from command line"""
    from galileo.library.services.gcs import upload_file_to_backup
    from galileo.library.models import fitsFile

    # Get bucket info
    bucket_url = cloud_config['bucket_url']
    if bucket_url.startswith('gs://'):
        bucket_name = bucket_url.replace('gs://', '').rstrip('/')
    else:
        bucket_name = bucket_url.rstrip('/')

    auth_info = {'auth_string': cloud_config['auth_file_path']}

    # Get files without cloud URLs (including soft-deleted files)
    fits_files = list(fitsFile.select().where(
        (fitsFile.fitsFileName.is_null(False)) &
        ((fitsFile.fitsFileCloudURL.is_null(True)) | (fitsFile.fitsFileCloudURL == ""))
    ))

    print(f"Found {len(fits_files)} files to backup")

    uploaded_count = 0
    updated_count = 0
    error_count = 0

    for i, fits_file in enumerate(fits_files):
        try:
            print(f"[{i+1:3d}/{len(fits_files)}] {os.path.basename(fits_file.fitsFileName)}")

            # Get relative path
            full_path = fits_file.fitsFileName
            if full_path.startswith(repo_path):
                relative_path = os.path.relpath(full_path, repo_path)
            else:
                relative_path = os.path.basename(full_path)

            # Check if file exists
            if not os.path.exists(full_path):
                logging.warning(f"File not found: {full_path}")
                error_count += 1
                continue

            # Upload
            success, cloud_url, message = upload_file_to_backup(
                bucket_name, auth_info, full_path, relative_path
            )

            if success:
                fits_file.fitsFileCloudURL = cloud_url
                fits_file.save()
                updated_count += 1

                # Check if we actually uploaded (vs already existed)
                if "uploaded" in message.lower():
                    uploaded_count += 1

                # Delete local file if it's soft-deleted, but verify cloud backup first
                if fits_file.fitsFileSoftDelete:
                    try:
                        # Verify file exists in cloud before deleting
                        from galileo.library.services.gcs import check_file_exists_in_gcs
                        from galileo.library.services.cloud import _get_gcs_client

                        client = _get_gcs_client(auth_info)
                        gcs_object_name = relative_path.replace('\\', '/')

                        if check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
                            # File verified in cloud, safe to delete locally
                            os.remove(full_path)
                            print("    → Uploaded and deleted soft-deleted file after cloud verification")
                        else:
                            logging.error(f"SAFETY CHECK FAILED: File not found in cloud, keeping local copy: {relative_path}")
                            print("    → Uploaded (cloud verification failed, keeping local copy)")
                    except OSError as e:
                        logging.warning(f"Failed to delete soft-deleted file {relative_path}: {e}")
                        print("    → Uploaded (failed to delete local copy)")
                    except Exception as e:
                        logging.exception(f"Cloud verification failed for {relative_path}, keeping local copy: {e}")
                        print("    → Uploaded (cloud verification failed, keeping local copy)")
                elif "uploaded" in message.lower():
                    print("    → Uploaded")
                else:
                    print("    → Already exists")
            else:
                logging.error(f"Failed to upload {relative_path}: {message}")
                error_count += 1

        except Exception as e:
            logging.exception(f"Error processing {fits_file.fitsFileName}: {e}")
            error_count += 1

    print("\nBackup sync completed:")
    print(f"  Files processed: {len(fits_files)}")
    print(f"  Files uploaded: {uploaded_count}")
    print(f"  Database records updated: {updated_count}")
    print(f"  Errors: {error_count}")

def perform_ondemand_sync_cli(cloud_config, repo_path):
    """Perform on-demand sync from command line - upload and delete soft-deleted files"""
    from galileo.library.services.gcs import upload_file_to_backup
    from galileo.library.models import fitsFile

    # Get bucket info
    bucket_url = cloud_config['bucket_url']
    if bucket_url.startswith('gs://'):
        bucket_name = bucket_url.replace('gs://', '').rstrip('/')
    else:
        bucket_name = bucket_url.rstrip('/')

    auth_info = {'auth_string': cloud_config['auth_file_path']}

    # Get soft-deleted files
    soft_deleted_files = list(fitsFile.select().where(
        (fitsFile.fitsFileName.is_null(False)) &
        (fitsFile.fitsFileSoftDelete == True)
    ))

    print(f"Found {len(soft_deleted_files)} soft-deleted files to upload and delete")

    if len(soft_deleted_files) == 0:
        print("No soft-deleted files found. Nothing to do.")
        return

    uploaded_count = 0
    deleted_count = 0
    updated_count = 0
    error_count = 0

    for i, fits_file in enumerate(soft_deleted_files):
        try:
            print(f"[{i+1:3d}/{len(soft_deleted_files)}] {os.path.basename(fits_file.fitsFileName)}")

            # Get relative path
            full_path = fits_file.fitsFileName
            if full_path.startswith(repo_path):
                relative_path = os.path.relpath(full_path, repo_path)
            else:
                relative_path = os.path.basename(full_path)

            # Check if file exists
            if not os.path.exists(full_path):
                logging.warning(f"Soft-deleted file not found: {full_path}")
                error_count += 1
                continue

            # Upload
            success, cloud_url, message = upload_file_to_backup(
                bucket_name, auth_info, full_path, relative_path
            )

            if success:
                fits_file.fitsFileCloudURL = cloud_url
                fits_file.save()
                updated_count += 1

                # Check if we actually uploaded (vs already existed)
                if "uploaded" in message.lower():
                    uploaded_count += 1

                # Verify cloud backup before deleting local file
                try:
                    from galileo.library.services.gcs import check_file_exists_in_gcs
                    from galileo.library.services.cloud import _get_gcs_client

                    client = _get_gcs_client(auth_info)
                    gcs_object_name = relative_path.replace('\\', '/')

                    if check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
                        # File verified in cloud, safe to delete locally
                        os.remove(full_path)
                        deleted_count += 1
                        print("    → Uploaded and deleted after cloud verification")
                    else:
                        logging.error(f"SAFETY CHECK FAILED: File not found in cloud, keeping local copy: {relative_path}")
                        print("    → Uploaded (cloud verification failed, keeping local copy)")
                except OSError as e:
                    logging.warning(f"Failed to delete soft-deleted file {relative_path}: {e}")
                    print("    → Uploaded (failed to delete local copy)")
                except Exception as e:
                    logging.exception(f"Cloud verification failed for {relative_path}, keeping local copy: {e}")
                    print("    → Uploaded (cloud verification failed, keeping local copy)")
            else:
                logging.error(f"Failed to upload {relative_path}: {message}")
                error_count += 1

        except Exception as e:
            logging.exception(f"Error processing {fits_file.fitsFileName}: {e}")
            error_count += 1

    print("\nOn-demand sync completed:")
    print(f"  Soft-deleted files processed: {len(soft_deleted_files)}")
    print(f"  Files uploaded: {uploaded_count}")
    print(f"  Local files deleted: {deleted_count}")
    print(f"  Database records updated: {updated_count}")
    print(f"  Errors: {error_count}")

def perform_upload_without_deletion_cli(cloud_config, repo_path):
    """Perform upload without deletion for complete sync - keep files in both places"""
    from galileo.library.services.gcs import upload_file_to_backup
    from galileo.library.models import fitsFile

    # Get bucket info
    bucket_url = cloud_config['bucket_url']
    if bucket_url.startswith('gs://'):
        bucket_name = bucket_url.replace('gs://', '').rstrip('/')
    else:
        bucket_name = bucket_url.rstrip('/')

    auth_info = {'auth_string': cloud_config['auth_file_path']}

    # Get files without cloud URLs (including soft-deleted and masters)
    fits_files = list(fitsFile.select().where(
        (fitsFile.fitsFileName.is_null(False)) &
        ((fitsFile.fitsFileCloudURL.is_null(True)) | (fitsFile.fitsFileCloudURL == ""))
    ))

    print(f"Found {len(fits_files)} files to upload (keeping local copies)")

    uploaded_count = 0
    updated_count = 0
    error_count = 0

    for i, fits_file in enumerate(fits_files):
        try:
            print(f"[{i+1:3d}/{len(fits_files)}] {os.path.basename(fits_file.fitsFileName)}")

            # Get relative path
            full_path = fits_file.fitsFileName
            if full_path.startswith(repo_path):
                relative_path = os.path.relpath(full_path, repo_path)
            else:
                relative_path = os.path.basename(full_path)

            # Check if file exists
            if not os.path.exists(full_path):
                logging.warning(f"File not found: {full_path}")
                error_count += 1
                continue

            # Upload
            success, cloud_url, message = upload_file_to_backup(
                bucket_name, auth_info, full_path, relative_path
            )

            if success:
                fits_file.fitsFileCloudURL = cloud_url
                fits_file.save()
                updated_count += 1

                # Check if we actually uploaded (vs already existed)
                if "uploaded" in message.lower():
                    uploaded_count += 1

                # Complete Sync: NO deletion - keep files in both places
                if "uploaded" in message.lower():
                    print("    → Uploaded (keeping local copy)")
                else:
                    print("    → Already exists")
            else:
                logging.error(f"Failed to upload {relative_path}: {message}")
                error_count += 1

        except Exception as e:
            logging.exception(f"Error processing {fits_file.fitsFileName}: {e}")
            error_count += 1

    print("\nUpload phase completed:")
    print(f"  Files processed: {len(fits_files)}")
    print(f"  Files uploaded: {uploaded_count}")
    print(f"  Database records updated: {updated_count}")
    print(f"  Errors: {error_count}")

def perform_complete_sync_cli(cloud_config, repo_path):
    """Perform complete sync from command line"""
    from galileo.library.services.gcs import list_gcs_bucket_files, download_file_from_gcs
    from galileo.library.models import fitsFile
    from galileo.library.core import fitsProcessing

    # Read configuration file
    config = load_config()

    # Get bucket info
    bucket_url = cloud_config['bucket_url']
    if bucket_url.startswith('gs://'):
        bucket_name = bucket_url.replace('gs://', '').rstrip('/')
    else:
        bucket_name = bucket_url.rstrip('/')

    auth_info = {'auth_string': cloud_config['auth_file_path']}

    print("Phase 1: Downloading missing files from cloud...")

    # Get cloud files
    cloud_files = list_gcs_bucket_files(bucket_name, auth_info)
    print(f"Found {len(cloud_files)} files in cloud storage")

    downloaded_count = 0
    registered_count = 0

    for i, cloud_file in enumerate(cloud_files):
        print(f"[{i+1:3d}/{len(cloud_files)}] Checking {cloud_file['name']}")

        # Check if file already exists in database (already processed)
        filename_only = os.path.basename(cloud_file['name'])
        cloud_url = f"gs://{bucket_name}/{cloud_file['name']}"

        # Check if file is already in database/repository by multiple methods
        existing_file = None

        # Method 1: Check by exact filename
        try:
            existing_file = fitsFile.get(fitsFile.fitsFileName == filename_only)
            print(f"    → File already exists in repository (by filename): {filename_only}")
        except fitsFile.DoesNotExist:
            pass

        # Method 2: Check by cloud URL (for files downloaded previously)
        if existing_file is None:
            try:
                existing_file = fitsFile.get(fitsFile.fitsFileCloudURL == cloud_url)
                print(f"    → File already exists in repository (by cloud URL): {filename_only}")
            except fitsFile.DoesNotExist:
                pass

        # Method 3: Check by timestamp pattern (extract date/time from filename)
        if existing_file is None:
            import re
            # Extract timestamp pattern like "20240116031554" from filename
            timestamp_match = re.search(r'-(\d{14})[s-]', filename_only)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                try:
                    # Look for any file with this timestamp
                    existing_file = fitsFile.get(fitsFile.fitsFileName.contains(timestamp))
                    print(f"    → File already exists in repository (by timestamp {timestamp}): {filename_only}")
                except fitsFile.DoesNotExist:
                    pass

        if existing_file is None:
            try:
                print("    → Downloading to incoming folder...")

                # Get source folder from configuration
                source_path = config.get('DEFAULT', 'source', fallback='')
                if not source_path:
                    logging.error("Source folder not configured. Cannot download files.")
                    continue

                # Ensure source folder exists
                os.makedirs(source_path, exist_ok=True)

                # Download to source folder (incoming)
                incoming_file_path = os.path.join(source_path, os.path.basename(cloud_file['name']))

                success, message = download_file_from_gcs(
                    bucket_name, auth_info, cloud_file['name'], incoming_file_path
                )

                if success:
                    downloaded_count += 1
                    print("    → Downloaded successfully")

                    # Register and move if it's a FITS file
                    if incoming_file_path.lower().endswith(('.fits', '.fit', '.fts')):
                        processor = fitsProcessing()
                        # Split path into directory and filename for registerFitsImage
                        root_dir = os.path.dirname(incoming_file_path)
                        filename = os.path.basename(incoming_file_path)
                        result = processor.registerFitsImage(root_dir, filename, moveFiles=True)
                        if result:  # Success includes both new registrations and duplicates
                            registered_count += 1
                            if result == "DUPLICATE":
                                # File already exists in repository, delete the downloaded copy
                                try:
                                    os.remove(incoming_file_path)
                                    print("    → File already exists in repository, deleted incoming copy")
                                except OSError as e:
                                    print(f"    → File exists but failed to delete incoming copy: {e}")
                            else:
                                print("    → Registered and moved to repository")
                        else:
                            print("    → Downloaded but failed to register")
                    else:
                        print("    → Downloaded non-FITS file")

            except Exception as e:
                logging.exception(f"Failed to download {cloud_file['name']}: {e}")

    print("\nPhase 1 completed:")
    print(f"  Files downloaded: {downloaded_count}")
    print(f"  Files registered: {registered_count}")

    print("\nPhase 2: Uploading local files without cloud URLs...")

    # Perform upload without deletion for complete sync (keep files in both places)
    perform_upload_without_deletion_cli(cloud_config, repo_path)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Galileo Cloud Sync Command Line Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('-v', '--verbose', action='store_true',
                      help='Enable verbose logging')
    parser.add_argument('-c', '--config', default=None,
                      help='Path to configuration file (default: library.ini in the Galileo config folder)')
    parser.add_argument('-p', '--profile', choices=['backup', 'complete', 'ondemand'],
                      help='Override sync profile (backup|complete|ondemand)')
    parser.add_argument('-a', '--analyze', action='store_true',
                      help='Only analyze cloud storage, don\'t sync')
    parser.add_argument('-y', '--yes', action='store_true',
                      help='Skip confirmation prompts (auto-confirm)')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    try:
        # Load configuration
        config = load_config(args.config)
        cloud_config = get_cloud_config(config)

        # Override sync profile if specified
        if args.profile:
            cloud_config['sync_profile'] = args.profile

        # Validate bucket access
        validate_bucket_access(cloud_config)

        if args.analyze:
            # Perform analysis only
            perform_analysis(cloud_config)
        else:
            # Perform sync
            perform_sync(cloud_config, cloud_config['sync_profile'], args.yes)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logging.exception(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
