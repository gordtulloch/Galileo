# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch
import os
import logging
import hashlib
from galileo.library.exceptions import CloudSyncError

# Debug flag: if True, only report actions; if False, perform sync
DEBUG = False

logger = logging.getLogger(__name__)

def _calculate_md5_hash(file_path):
    """
    Calculate MD5 hash of a local file.

    Args:
        file_path (str): Path to the file

    Returns:
        str: MD5 hash as hexadecimal string, or None if error
    """
    try:
        hash_md5 = hashlib.md5(usedforsecurity=False)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        logger.exception(f"Error calculating MD5 hash for {file_path}")
        return None

def _should_upload_file(client, bucket_name, gcs_object_name, local_file_path):
    """
    Determine if a file should be uploaded to GCS by comparing MD5 hashes.

    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        gcs_object_name (str): Object name in GCS
        local_file_path (str): Path to local file

    Returns:
        tuple: (should_upload: bool, reason: str)
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)

        # Check if the blob exists in GCS
        if not blob.exists():
            return True, "file does not exist in cloud"

        # Refresh blob metadata to get current information
        blob.reload()

        # Get the GCS file's MD5 hash
        gcs_md5 = blob.md5_hash
        if not gcs_md5:
            return True, "cloud file has no MD5 hash available"

        # Calculate local file's MD5 hash
        local_md5 = _calculate_md5_hash(local_file_path)
        if not local_md5:
            return True, "could not calculate local file hash"

        # Convert GCS MD5 from base64 to hex for comparison
        import base64
        try:
            gcs_md5_hex = base64.b64decode(gcs_md5).hex()
        except Exception as e:
            logger.warning(f"Could not decode GCS MD5 hash for {gcs_object_name}: {e}")
            return True, "could not decode cloud file hash"

        # Compare hashes
        if local_md5 == gcs_md5_hex:
            return False, "file already exists with same content (MD5 match)"
        else:
            return True, f"file content differs (local MD5: {local_md5}, cloud MD5: {gcs_md5_hex})"

    except Exception as e:
        logger.warning(f"Error checking if {gcs_object_name} should be uploaded: {e}")
        # If we can't check, err on the side of uploading
        return True, f"error checking cloud file: {e}"

def _get_cloud_file_hashes(client, bucket_name, prefix):
    """
    Get MD5 hashes for all files in the cloud bucket with the given prefix.
    This is more efficient than checking files individually.

    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        prefix (str): Prefix to filter objects

    Returns:
        dict: Dictionary mapping object names to MD5 hashes (hex format)
    """
    try:
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)

        cloud_hashes = {}
        for blob in blobs:
            if blob.md5_hash:
                try:
                    # Convert from base64 to hex
                    import base64
                    md5_hex = base64.b64decode(blob.md5_hash).hex()
                    cloud_hashes[blob.name] = md5_hex
                except Exception as e:
                    logger.warning(f"Could not decode MD5 for {blob.name}: {e}")
            else:
                logger.debug(f"No MD5 hash available for {blob.name}")

        logger.info(f"Retrieved hashes for {len(cloud_hashes)} cloud files")
        return cloud_hashes

    except Exception:
        logger.exception("Error retrieving cloud file hashes")
        return {}

def _should_upload_file_bulk(cloud_hashes, gcs_object_name, local_file_path):
    """
    Determine if a file should be uploaded using pre-fetched cloud hashes.
    This is more efficient than checking files individually.

    Args:
        cloud_hashes (dict): Dictionary of cloud object names to MD5 hashes
        gcs_object_name (str): Object name in GCS
        local_file_path (str): Path to local file

    Returns:
        tuple: (should_upload: bool, reason: str)
    """
    # Check if file exists in cloud
    if gcs_object_name not in cloud_hashes:
        return True, "file does not exist in cloud"

    # Calculate local file hash
    local_md5 = _calculate_md5_hash(local_file_path)
    if not local_md5:
        return True, "could not calculate local file hash"

    # Compare hashes
    cloud_md5 = cloud_hashes[gcs_object_name]
    if local_md5 == cloud_md5:
        return False, "file already exists with same content (MD5 match)"
    else:
        return True, f"file content differs (local MD5: {local_md5}, cloud MD5: {cloud_md5})"

def _get_gcs_client(auth_info):
    """
    Create and return a Google Cloud Storage client.

    Args:
        auth_info (dict): Authentication information

    Returns:
        storage.Client: Authenticated GCS client
    """
    try:
        from google.cloud import storage
        from google.oauth2 import service_account

        if auth_info.get('auth_string'):
            # Check if it's a file path to a service account key
            auth_path = auth_info['auth_string']
            if os.path.exists(auth_path) and auth_path.endswith('.json'):
                # Use service account key file
                credentials = service_account.Credentials.from_service_account_file(auth_path)
                client = storage.Client(credentials=credentials)
                logger.info(f"Authenticated using service account key: {auth_path}")
            else:
                # Try default credentials
                client = storage.Client()
                logger.info("Using default Google Cloud credentials")
        else:
            # Use default credentials (ADC, environment, etc.)
            client = storage.Client()
            logger.info("Using default Google Cloud credentials")

        return client

    except ImportError as exc:
        raise ImportError("Google Cloud Storage library not installed. Run: pip install google-cloud-storage") from exc
    except Exception as e:
        raise CloudSyncError(f"Failed to authenticate with Google Cloud: {e}") from e

def _parse_gcs_path(gcs_path):
    """
    Parse GCS path into bucket name and prefix.

    Args:
        gcs_path (str): GCS path like gs://bucket-name/path/

    Returns:
        tuple: (bucket_name, prefix)
    """
    if not gcs_path.startswith('gs://'):
        raise ValueError("GCS path must start with gs://")

    path_parts = gcs_path[5:].split('/', 1)  # Remove gs:// and split
    bucket_name = path_parts[0]
    prefix = path_parts[1] if len(path_parts) > 1 else ''

    # Ensure prefix ends with / if not empty
    if prefix and not prefix.endswith('/'):
        prefix += '/'

    return bucket_name, prefix

def _upload_file_to_gcs(client, bucket_name, local_file_path, gcs_object_name):
    """
    Upload a file to Google Cloud Storage, preserving the local directory structure.
    This will overwrite any existing file with the same object name.

    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        local_file_path (str): Full path to local file
        gcs_object_name (str): Object name in GCS (includes directory structure)
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)

        # Check if file already exists for logging purposes
        exists_before = blob.exists()
        if exists_before:
            logger.debug(f"Overwriting existing cloud file: gs://{bucket_name}/{gcs_object_name}")

        blob.upload_from_filename(local_file_path)

        action = "overwrote" if exists_before else "uploaded"
        logger.debug(f"Successfully {action}: {local_file_path} -> gs://{bucket_name}/{gcs_object_name}")

    except Exception:
        logger.exception(f"Failed to upload {local_file_path}")
        raise

def _download_file_from_gcs(client, bucket_name, gcs_object_name, local_file_path):
    """
    Download a file from Google Cloud Storage, preserving the directory structure.

    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        gcs_object_name (str): Object name in GCS (includes directory structure)
        local_file_path (str): Full path where to save the file locally
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)

        # Create directory structure if it doesn't exist
        local_dir = os.path.dirname(local_file_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)

        blob.download_to_filename(local_file_path)
        logger.debug(f"Successfully downloaded: gs://{bucket_name}/{gcs_object_name} -> {local_file_path}")

    except Exception:
        logger.exception(f"Failed to download gs://{bucket_name}/{gcs_object_name}")
        raise

def _should_download_file(blob, local_file_path):
    """
    Determine if a file should be downloaded from GCS.

    Args:
        blob: GCS blob object
        local_file_path (str): Path to local file

    Returns:
        tuple: (should_download: bool, reason: str)
    """
    if not os.path.exists(local_file_path):
        return True, "file does not exist locally"

    # Compare file sizes
    local_size = os.path.getsize(local_file_path)
    gcs_size = blob.size

    if local_size != gcs_size:
        return True, f"size mismatch (local: {local_size}, GCS: {gcs_size})"

    # Compare modification times
    local_mtime = os.path.getmtime(local_file_path)
    gcs_mtime = blob.time_created.timestamp() if blob.time_created else 0

    # Allow some tolerance for timestamp differences (1 second)
    if abs(local_mtime - gcs_mtime) > 1:
        return True, f"timestamp mismatch (local: {local_mtime}, GCS: {gcs_mtime})"

    return False, "file is up to date"

def _register_fits_file(file_path):
    """
    Register a FITS file in the database using the single file registry.

    Args:
        file_path (str): Path to the FITS file
    """
    try:
        # Import here to avoid circular imports
        from galileo.library.core import fitsProcessing

        if file_path.lower().endswith(('.fits', '.fit', '.fts')):
            processor = fitsProcessing()
            # Split path into directory and filename for registerFitsImage
            root_dir = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            success = processor.registerFitsImage(root_dir, filename, moveFiles=False)
            if success:
                logger.info(f"Registered FITS file in database: {file_path}")
            else:
                logger.warning(f"Failed to register FITS file: {file_path}")
        else:
            logger.debug(f"Skipped non-FITS file: {file_path}")

    except Exception:
        logger.exception(f"Error registering FITS file {file_path}")

def _download_phase(client, bucket_name, prefix, local_repo_path, debug, progress_callback):
    """PHASE 1: download the GCS files that are missing or stale locally.

    Returns ``(downloaded_files, cancelled)``. ``downloaded_files`` holds the ``/``-separated relative paths
    handled here, so the upload phase can skip them; ``cancelled`` is True if the progress callback asked to stop.
    """
    if debug:
        logger.info("DEBUG MODE: Starting DOWNLOAD analysis:")
    else:
        logger.info("LIVE MODE: Starting DOWNLOAD operations:")

    downloaded_files: set[str] = set()
    download_count = 0
    skip_count = 0

    try:
        bucket = client.bucket(bucket_name)

        # List all objects in the bucket with the specified prefix
        blobs = list(bucket.list_blobs(prefix=prefix))
        total_gcs_files = len(blobs)

        if progress_callback:
            progress_callback(15, 100, "download_prepare", "Starting download operations")

        for i, blob in enumerate(blobs):
            if not blob.name.startswith(prefix):
                continue
            # Calculate relative path by removing prefix
            relative_path = blob.name[len(prefix):]

            # Skip if it's just the prefix (directory marker)
            if not relative_path:
                continue

            # Preserve directory structure when creating local path
            local_file_path = os.path.join(local_repo_path, relative_path.replace('/', os.path.sep))

            # Check if file should be downloaded
            should_download, reason = _should_download_file(blob, local_file_path)
            if not should_download:
                logger.debug(f"Skipping: {relative_path} ({reason})")
                skip_count += 1
                continue

            try:
                # Update progress callback
                if progress_callback:
                    continue_operation = progress_callback(15 + (i * 35 // total_gcs_files), 50, "download", f"Processing {relative_path}")
                    # If the callback returns False, it means the operation was cancelled
                    if continue_operation is False:
                        logger.info("Google Sync download operation was cancelled by user")
                        return downloaded_files, True

                if debug:
                    logger.info(f"[DEBUG] Would download: gs://{bucket_name}/{blob.name} -> {relative_path} (reason: {reason})")
                else:
                    logger.info(f"Downloading: gs://{bucket_name}/{blob.name} -> {relative_path} (reason: {reason})")
                    _download_file_from_gcs(client, bucket_name, blob.name, local_file_path)

                    # Register FITS files in database
                    _register_fits_file(local_file_path)

                # Track this file as downloaded to avoid re-uploading
                downloaded_files.add(relative_path.replace(os.path.sep, '/'))
                download_count += 1

            except Exception:
                logger.exception(f"Failed to download {blob.name}")

        if debug:
            logger.info(f"DEBUG MODE: Would download {download_count} files from GCS, would skip {skip_count} up-to-date files")
        else:
            logger.info(f"Downloaded {download_count} files from GCS, skipped {skip_count} up-to-date files")

        # Log downloaded files tracking for debugging
        logger.info(f"Tracking {len(downloaded_files)} downloaded files to exclude from upload phase")
        if debug and len(downloaded_files) > 0:
            logger.debug(f"First few downloaded files: {list(downloaded_files)[:5]}...")

    except Exception:
        logger.exception("Failed to list GCS objects")

    return downloaded_files, False


def _list_local_files(local_repo_path):
    """Relative paths of every file under *local_repo_path*, skipping hidden folders, dot-files and bytecode."""
    local_files = []
    for root, dirs, files in os.walk(local_repo_path):
        # Skip hidden directories and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            if not file.startswith('.') and not file.endswith('.pyc'):
                local_files.append(os.path.relpath(os.path.join(root, file), local_repo_path))
    return local_files


def _upload_phase(client, bucket_name, prefix, local_repo_path, local_files, downloaded_files, cloud_hashes,
                  debug, progress_callback):
    """PHASE 2: upload the local files the cloud lacks (excluding the ones just downloaded).

    Returns ``(upload_count, skipped_count, excluded_count, replaced_count)``, or ``None`` if the progress
    callback asked to stop.
    """
    total_local_files = len(local_files)

    if debug:
        logger.info("DEBUG MODE: Starting UPLOAD analysis:")
    else:
        logger.info("LIVE MODE: Starting UPLOAD operations:")

    upload_count = 0
    skipped_count = 0
    excluded_count = 0
    replaced_count = 0  # Files replaced due to header modifications

    for i, file_path in enumerate(local_files):
        try:
            full_local_path = os.path.join(local_repo_path, file_path)
            # Preserve the complete local directory structure in GCS
            # Convert backslashes to forward slashes for GCS compatibility
            gcs_object_name = prefix + file_path.replace('\\', '/')

            # Create normalized path for comparison (should match what was stored in downloaded_files)
            normalized_file_path = file_path.replace('\\', '/')

            # Skip files that were just downloaded to avoid circular uploads
            if normalized_file_path in downloaded_files:
                logger.debug(f"Excluding recently downloaded file from upload: {file_path}")
                excluded_count += 1
                continue

            # Debug: Log first few exclusion checks if in debug mode
            if debug and i < 5:
                logger.debug(f"Upload check for '{normalized_file_path}': in downloaded_files = {normalized_file_path in downloaded_files}")

            # Update progress
            if progress_callback:
                continue_operation = progress_callback(50 + (i * 45 // total_local_files), 95, "checking", f"Checking {file_path}")
                # If the callback returns False, it means the operation was cancelled
                if continue_operation is False:
                    logger.info("Google Sync operation was cancelled by user")
                    return None

            # Check if file should be uploaded (compare hashes using bulk method)
            should_upload, reason = _should_upload_file_bulk(cloud_hashes, gcs_object_name, full_local_path)
            if not should_upload:
                logger.debug(f"Skipping upload: {file_path} ({reason})")
                skipped_count += 1
                continue

            # A file that was downloaded but now has a different hash (header changes made during registration)
            # replaces the cloud version rather than creating a duplicate. (Unreachable while downloaded files are
            # excluded above; kept so the exclusion can be relaxed without losing this handling.)
            upload_reason = reason
            if normalized_file_path in downloaded_files and "file content differs" in reason:
                upload_reason = f"replacing modified file after download ({reason})"
                logger.info(f"File was modified after download (likely header fixes): {file_path}")
                replaced_count += 1

            if debug:
                logger.info(f"[DEBUG] Would upload: {file_path} -> gs://{bucket_name}/{gcs_object_name} ({upload_reason})")
            else:
                logger.info(f"Uploading: {file_path} -> gs://{bucket_name}/{gcs_object_name} ({upload_reason})")
                if progress_callback:
                    progress_callback(50 + (i * 45 // total_local_files), 95, "upload", f"Uploading {file_path}")
                _upload_file_to_gcs(client, bucket_name, full_local_path, gcs_object_name)
            upload_count += 1

        except Exception:
            logger.exception(f"Failed to process {file_path}")

    return upload_count, skipped_count, excluded_count, replaced_count


def _log_upload_summary(debug, upload_count, skipped_count, excluded_count, replaced_count):
    """Log the totals of the upload phase (the dry-run wording when *debug*)."""
    prefix = "DEBUG MODE: Would " if debug else ""
    if debug:
        logger.info(f"DEBUG MODE: Would upload {upload_count} files to GCS, skip {skipped_count} duplicates, exclude {excluded_count} recently downloaded")
    else:
        logger.info(f"Uploaded {upload_count} files to GCS, skipped {skipped_count} duplicates, excluded {excluded_count} recently downloaded")
    if replaced_count > 0:
        logger.info(f"{prefix}{'replace' if debug else 'Replaced'} {replaced_count} files modified during download (header fixes)")
    if upload_count + skipped_count > 0:
        total = upload_count + skipped_count
        efficiency = f"Efficiency gain: {skipped_count}/{total} files ({100 * skipped_count / total:.1f}%) already exist"
        logger.info(f"DEBUG MODE: {efficiency}" if debug else efficiency)


def sync_with_google_cloud_repo(gcs_repo_path, auth_info, local_repo_path, sync_to_local=False, debug=DEBUG, progress_callback=None):
    """
    Connects to a Google Cloud Repository and synchronizes files with the local repository.
    If debug is True, only reports actions; if False, performs actual sync.

    Args:
        gcs_repo_path (str): Path to the Google Cloud Repository (gs://bucket/path).
        auth_info (dict): Authentication information for Google Cloud.
        local_repo_path (str): Path to the local repository directory.
        sync_to_local (bool): If True, download missing files from GCS to local repo.
        debug (bool): If True, only report actions.
        progress_callback (callable): Optional callback function for progress updates.
                                     Called with (current_count, total_count, operation_type, filename)
    """
    logger.info(f"Google Cloud Sync - Debug mode: {debug}")
    logger.info(f"GCS repository path: {gcs_repo_path}")
    logger.info(f"Local repository path: {local_repo_path}")
    logger.info(f"Sync to local enabled: {sync_to_local}")
    logger.info(f"Authentication info provided: {bool(auth_info)}")

    if not gcs_repo_path:
        logger.warning("No Google Cloud repository path specified in configuration")
        return

    if not local_repo_path:
        logger.warning("No local repository path specified in configuration")
        return

    if not os.path.exists(local_repo_path):
        logger.warning(f"Local repository path does not exist: {local_repo_path}")
        return

    try:
        # Initialize GCS client (in both debug and live modes)
        client = _get_gcs_client(auth_info)
        bucket_name, prefix = _parse_gcs_path(gcs_repo_path)

        logger.info(f"Connected to GCS bucket: {bucket_name} with prefix: {prefix}")

        # Update progress with connection info
        if progress_callback:
            progress_callback(5, 100, "connect", f"Connected to GCS bucket: {bucket_name}")

        # Get cloud file hashes for efficient duplicate checking
        logger.info("Retrieving cloud file hashes for duplicate detection...")
        if progress_callback:
            progress_callback(10, 100, "scan", "Retrieving cloud file metadata...")
        cloud_hashes = _get_cloud_file_hashes(client, bucket_name, prefix)

        # PHASE 1: Download missing files from GCS if enabled (Complete sync)
        downloaded_files: set[str] = set()
        if sync_to_local:
            downloaded_files, cancelled = _download_phase(client, bucket_name, prefix, local_repo_path, debug, progress_callback)
            if cancelled:
                return

        # PHASE 2: Find all local files and upload those that aren't from download phase
        logger.info("Scanning local repository for files to upload...")
        if progress_callback:
            progress_callback(50, 100, "scan", "Scanning local files for upload")

        local_files = _list_local_files(local_repo_path)
        logger.info(f"Found {len(local_files)} local files to potentially sync")

        counts = _upload_phase(client, bucket_name, prefix, local_repo_path, local_files, downloaded_files,
                               cloud_hashes, debug, progress_callback)
        if counts is None:
            return
        _log_upload_summary(debug, *counts)

        if debug:
            logger.info("DEBUG MODE: Synchronization analysis completed successfully")
        else:
            logger.info("Synchronization completed successfully")

        # Final progress update
        if progress_callback:
            try:
                progress_callback(100, 100, "complete", "Synchronization completed successfully")
            except Exception:
                logger.exception("Error in final progress callback")
                # Don't raise here as the sync was successful

    except ImportError as e:
        logger.exception("Google Cloud Storage library not available")
        logger.info("To install: pip install google-cloud-storage")
        # Report error in progress callback if available
        if progress_callback:
            progress_callback(0, 100, "error", f"Missing Google Cloud Storage library: {e}")
        raise

    except Exception as e:
        logger.exception("Synchronization failed")
        # Report error in progress callback if available
        if progress_callback:
            progress_callback(0, 100, "error", f"Sync error: {e}")
        raise

def validate_google_cloud_config(repo_path, auth_info):
    """
    Validates the Google Cloud configuration.

    Args:
        repo_path (str): Path to the Google Cloud Repository.
        auth_info (dict): Authentication information for Google Cloud.

    Returns:
        tuple: (is_valid, error_message)
    """
    if not repo_path:
        return False, "Repository path is required"

    if not isinstance(repo_path, str) or not repo_path.strip():
        return False, "Repository path must be a non-empty string"

    if not auth_info:
        return False, "Authentication information is required"

    # Basic validation of auth_info structure
    if not isinstance(auth_info, dict):
        return False, "Authentication information must be a dictionary"

    # Could add more specific validation based on Google Cloud auth requirements

    return True, "Configuration is valid"
