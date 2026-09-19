# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Google Cloud Storage helpers shared by the Cloud screen and the ``cloud_sync`` command (LIB-120).

Lifted out of the Qt dialog module so the headless command-line utility doesn't
have to import PySide6.
"""

import os
import logging
import base64

logger = logging.getLogger(__name__)

# Hash helpers used for duplicate detection
from galileo.library.services.cloud import _calculate_md5_hash, _get_cloud_file_hashes  # noqa: F401


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
        
        if 'auth_string' in auth_info and auth_info['auth_string']:
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
        
    except ImportError:
        raise ImportError("Google Cloud Storage library not installed. Run: pip install google-cloud-storage")
    except Exception as e:
        raise Exception(f"Failed to authenticate with Google Cloud: {e}")


def check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
    """
    Check if a file exists in Google Cloud Storage.
    
    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        gcs_object_name (str): Object name in GCS
        
    Returns:
        bool: True if file exists, False otherwise
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)
        return blob.exists()
    except Exception as e:
        logger.error(f"Failed to check if file exists: gs://{bucket_name}/{gcs_object_name}: {e}")
        return False


def upload_file_to_backup(bucket_name, auth_info, local_file_path, relative_path):
    """
    Upload a single file to cloud backup if it doesn't already exist.
    
    Args:
        bucket_name (str): Name of the GCS bucket
        auth_info (dict): Authentication information
        local_file_path (str): Full path to local file
        relative_path (str): Relative path to maintain directory structure
        
    Returns:
        tuple: (success: bool, cloud_url: str, message: str)
    """
    try:
        logger.info(f"Processing backup for: {relative_path}")
        
        # Get authenticated client
        client = _get_gcs_client(auth_info)
        
        # Normalize the path for cloud storage (use forward slashes)
        gcs_object_name = relative_path.replace('\\', '/')
        
        # Check if file already exists
        if check_file_exists_in_gcs(client, bucket_name, gcs_object_name):
            # File exists, just build the cloud URL
            cloud_url = f"gs://{bucket_name}/{gcs_object_name}"
            logger.info(f"File already exists in cloud: {gcs_object_name}")
            return True, cloud_url, "File already exists in cloud"
        
        # File doesn't exist, upload it
        logger.info(f"Uploading to cloud: {gcs_object_name}")
        _upload_file_to_gcs(client, bucket_name, local_file_path, gcs_object_name)
        cloud_url = f"gs://{bucket_name}/{gcs_object_name}"
        logger.info(f"Successfully uploaded: {gcs_object_name}")
        return True, cloud_url, "File uploaded successfully"
        
    except Exception as e:
        logger.error(f"Failed to upload file to backup: {local_file_path}: {e}")
        return False, "", str(e)


def _upload_file_to_gcs(client, bucket_name, local_file_path, gcs_object_name):
    """
    Upload a file to Google Cloud Storage, preserving the local directory structure.
    
    Args:
        client: GCS client
        bucket_name (str): Name of the GCS bucket
        local_file_path (str): Full path to local file
        gcs_object_name (str): Object name in GCS (includes directory structure)
    """
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)
        
        blob.upload_from_filename(local_file_path)
        logger.debug(f"Successfully uploaded: {local_file_path} -> gs://{bucket_name}/{gcs_object_name}")
        
    except Exception as e:
        logger.error(f"Failed to upload {local_file_path}: {e}")
        raise


def list_gcs_bucket_files(bucket_name, auth_info, prefix=""):
    """
    List all files in a Google Cloud Storage bucket.
    
    Args:
        bucket_name (str): Name of the GCS bucket
        auth_info (dict): Authentication information
        prefix (str): Optional prefix to filter files
        
    Returns:
        list: List of dictionaries containing file information
    """
    try:
        logger.info(f"Listing files in bucket: {bucket_name}")
        
        # Get authenticated client
        client = _get_gcs_client(auth_info)
        bucket = client.bucket(bucket_name)
        
        # List all blobs with optional prefix
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        files = []
        for blob in blobs:
            # Skip directory markers (objects ending with /)
            if blob.name.endswith('/'):
                continue
            
            # Convert MD5 hash from base64 to hex format for comparison
            md5_hash_hex = None
            if blob.md5_hash:
                try:
                    # GCS returns MD5 as base64, convert to hex for comparison
                    md5_hash_hex = base64.b64decode(blob.md5_hash).hex()
                except Exception as e:
                    logger.warning(f"Failed to convert MD5 hash for {blob.name}: {e}")
                    md5_hash_hex = None
                
            file_info = {
                'name': blob.name,
                'size': blob.size,
                'created': blob.time_created.isoformat() if blob.time_created else None,
                'updated': blob.updated.isoformat() if blob.updated else None,
                'md5_hash': md5_hash_hex,  # Now in hex format for easy comparison
                'md5_hash_base64': blob.md5_hash,  # Keep original for reference
                'crc32c': blob.crc32c,
                'content_type': blob.content_type,
                'url': f"gs://{bucket_name}/{blob.name}",
                'public_url': blob.public_url if hasattr(blob, 'public_url') else None
            }
            files.append(file_info)
            
        logger.info(f"Found {len(files)} files in bucket")
        return files
        
    except Exception as e:
        logger.error(f"Error listing bucket files: {e}")
        error_msg = str(e)
        
        # Provide more specific error messages for common issues
        if "404" in error_msg or "not found" in error_msg.lower():
            raise Exception(f"Failed to list files in bucket {bucket_name}: 404 GET https://storage.googleapis.com/storage/v1/b/{bucket_name}/o?projection=noAcl&prefix=&prettyPrint=false: The specified bucket does not exist.")
        elif "403" in error_msg or "access denied" in error_msg.lower():
            raise Exception(f"Failed to list files in bucket {bucket_name}: Access denied. Check your service account permissions.")
        elif "401" in error_msg or "unauthorized" in error_msg.lower():
            raise Exception(f"Failed to list files in bucket {bucket_name}: Authentication failed. Check your service account key file.")
        else:
            raise Exception(f"Failed to list files in bucket {bucket_name}: {error_msg}")


def download_file_from_gcs(bucket_name, auth_info, gcs_object_name, local_file_path):
    """
    Download a file from Google Cloud Storage to local disk.
    
    Args:
        bucket_name (str): Name of the GCS bucket
        auth_info (dict): Authentication information
        gcs_object_name (str): Object name in GCS
        local_file_path (str): Full path where to save the file locally
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        logger.info(f"Downloading from cloud: {gcs_object_name}")
        
        # Get authenticated client
        client = _get_gcs_client(auth_info)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_name)
        
        # Create directory structure if it doesn't exist
        local_dir = os.path.dirname(local_file_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        
        # Download the file
        blob.download_to_filename(local_file_path)
        logger.info(f"Successfully downloaded: gs://{bucket_name}/{gcs_object_name} -> {local_file_path}")
        return True, "File downloaded successfully"
        
    except Exception as e:
        logger.error(f"Failed to download gs://{bucket_name}/{gcs_object_name}: {e}")
        return False, str(e)


def find_cloud_duplicates(cloud_files):
    """
    Find duplicate files in cloud storage based on MD5 hash.
    
    Args:
        cloud_files (list): List of cloud file dictionaries
        
    Returns:
        dict: Dictionary with duplicate statistics and details
    """
    try:
        hash_groups = {}
        files_with_hashes = 0
        
        # Group files by MD5 hash
        for file_info in cloud_files:
            md5_hash = file_info.get('md5_hash')
            if md5_hash:
                files_with_hashes += 1
                if md5_hash not in hash_groups:
                    hash_groups[md5_hash] = []
                hash_groups[md5_hash].append(file_info)
        
        # Find duplicates (hash groups with more than one file)
        duplicates = {}
        total_duplicate_files = 0
        total_wasted_space = 0
        
        for hash_value, files in hash_groups.items():
            if len(files) > 1:
                duplicates[hash_value] = {
                    'files': files,
                    'count': len(files),
                    'size': files[0].get('size', 0),  # All files with same hash have same size
                    'wasted_space': (len(files) - 1) * files[0].get('size', 0)
                }
                total_duplicate_files += len(files)
                total_wasted_space += duplicates[hash_value]['wasted_space']
        
        return {
            'total_files': len(cloud_files),
            'files_with_hashes': files_with_hashes,
            'duplicate_groups': len(duplicates),
            'duplicate_files': total_duplicate_files,
            'unique_duplicates': len(duplicates),  # Number of unique content duplicated
            'wasted_space_bytes': total_wasted_space,
            'details': duplicates
        }
        
    except Exception as e:
        logger.error(f"Error finding cloud duplicates: {e}")
        return {
            'total_files': len(cloud_files) if cloud_files else 0,
            'files_with_hashes': 0,
            'duplicate_groups': 0,
            'duplicate_files': 0,
            'unique_duplicates': 0,
            'wasted_space_bytes': 0,
            'details': {},
            'error': str(e)
        }


def format_file_size(size_bytes):
    """Convert bytes to human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"
