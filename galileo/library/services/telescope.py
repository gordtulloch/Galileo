#!/usr/bin/env python3
"""
Astrofiler Smart Telescope Integration
Handles communication with smart telescopes like SEESTAR for automated file retrieval.
"""

import socket
import ipaddress
import os
import logging
from galileo.library.config import (
    get_itelescope_password,
    load_config as load_library_config,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
from galileo.library.services.telescope_ftp import FtpMixin
from galileo.library.services.telescope_ftps import FtpsMixin, _new_ftps_client  # noqa: F401  (re-exported)
from galileo.library.services.telescope_sftp import SftpMixin
from galileo.library.services.telescope_smb import SMB_AVAILABLE, SmbMixin, SMBConnection

# Configure logging
logger = logging.getLogger(__name__)

# Reduce SMB library verbosity
logging.getLogger('SMB').setLevel(logging.WARNING)
logging.getLogger('SMB.SMBConnection').setLevel(logging.WARNING)
logging.getLogger('SMB.SMBProtocol').setLevel(logging.WARNING)


class SmartTelescopeManager(SmbMixin, FtpMixin, FtpsMixin, SftpMixin):
    """Manages connections to smart telescopes."""

    def __init__(self):
        self.supported_telescopes = {
            'SeeStar': {
                'default_hostname': 'seestar.local',
                'default_username': 'guest',  # nosec B105 -- default account name, not a secret
                'default_password': 'guest',
                'share_name': 'EMMC Images',
                'fits_path': 'MyWorks'
            },
            'StellarMate': {
                'default_hostname': 'stellarmate.local',
                'default_username': 'stellarmate',  # nosec B105 -- default account name, not a secret
                'default_password': 'smate',
                'share_name': 'Pictures',
                'fits_path': ''  # Start scanning from root
            },
            'DWARF 3': {
                'default_hostname': '192.168.88.1',
                'default_username': None,  # nosec B105 -- No authentication for FTP
                'default_password': None,  # No authentication for FTP
                'protocol': 'ftp',
                'fits_path': 'Astronomy'  # DWARF stores FITS files in /Astronomy
            },
            'iTelescope': {
                'default_hostname': 'data.itelescope.net',
                'default_username': '',  # nosec B105 -- To be configured by user
                'default_password': '',  # To be configured by user
                'protocol': 'ftps',  # FTP with TLS
                'fits_path': '',  # Start scanning from root
                'port': 21
            },
            'SFTP': {
                # A remote-telescope/observatory data server over SSH (EXT-120, LIB-170). The host comes
                # from the Download dialog or --hostname; the account, key, folder and host-key policy
                # from Options > Library > Smart Telescopes (see galileo.library.config.get_sftp_settings).
                'default_hostname': '',
                'default_username': None,  # nosec B105 -- default account name, not a secret
                'default_password': None,
                'protocol': 'sftp',
                'fits_path': '/'
            }
        }

    def get_itelescope_credentials(self):
        """Get iTelescope credentials — username from the config file, password from the OS keychain (NFR-SEC-010)."""
        try:
            config = load_library_config()
            username = config.get('DEFAULT', 'itelescope_username', fallback='')
            return username.strip(), get_itelescope_password().strip()
        except Exception:
            logger.exception("Error reading iTelescope credentials")
            return '', ''

    def get_local_network(self):
        """Get the local network range based on the local IP address."""
        try:
            # Connect to a remote address to determine the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Determine likely network based on IP
            if local_ip.startswith('192.168.'):
                # Extract the third octet and assume /24
                parts = local_ip.split('.')
                return f"192.168.{parts[2]}.0/24"
            elif local_ip.startswith('10.'):
                # For 10.x networks, assume /24 on the same subnet
                parts = local_ip.split('.')
                return f"10.{parts[1]}.{parts[2]}.0/24"
            elif local_ip.startswith('172.'):
                # 172.16.0.0 to 172.31.255.255 - assume /24
                parts = local_ip.split('.')
                return f"172.{parts[1]}.{parts[2]}.0/24"
            else:
                return "192.168.1.0/24"

        except Exception as e:
            logger.debug(f"Error getting network info: {e}")
            return "10.0.0.0/24"

    def check_smb_port(self, ip, timeout=2):
        """Check if SMB port (445) is open on the given IP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((str(ip), 445))
                return result == 0
        except Exception:
            return False

    def check_ftp_port(self, ip, timeout=2):
        """Check if FTP port (21) is open on the given IP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((str(ip), 21))
                return result == 0
        except Exception:
            return False

    def get_hostname(self, ip):
        """Try to get the hostname for the given IP address."""
        try:
            hostname = socket.gethostbyaddr(str(ip))[0]
            return hostname
        except Exception:
            return None

    def is_target_device(self, hostname, telescope_type):
        """Check if the device matches the target telescope type."""
        if not hostname:
            return False

        if telescope_type == 'SeeStar':
            return 'seestar' in hostname.lower()
        elif telescope_type == 'StellarMate':
            return 'stellarmate' in hostname.lower()

        return False

    def find_telescope(self, telescope_type, network_range=None, hostname=None):
        """Find a specific telescope on the network."""
        logger.info(f"Starting search for {telescope_type} telescope (hostname={hostname}, network={network_range})")

        # An SFTP server is addressed by name; there is nothing to scan for
        if telescope_type == 'SFTP':
            if not hostname:
                return None, "Enter the SFTP server's hostname or IP address."
            return hostname, None

        # For iTelescope, bypass all network scanning and SMB checks
        if telescope_type == 'iTelescope':
            if hostname:
                logger.info(f"Using provided iTelescope hostname: {hostname}")
                return hostname, None
            else:
                default_hostname = self.supported_telescopes['iTelescope']['default_hostname']
                logger.info(f"Using default iTelescope hostname: {default_hostname}")
                return default_hostname, None

        if not SMB_AVAILABLE:
            logger.error("SMB protocol not available. Install pysmb package.")
            return None, "SMB protocol not available. Install pysmb package."

        if hostname:
            # For SeeStar, only use mDNS resolution for seestar.local hostnames
            # No reverse DNS lookups as SeeStar patched their firmware to disable them
            try:
                logger.debug(f"Resolving hostname {hostname}")
                ip = socket.gethostbyname(hostname)
                logger.debug(f"Hostname {hostname} resolved to {ip}")

                if self.check_smb_port(ip):
                    # For SeeStar, trust the mDNS hostname and skip reverse DNS
                    if telescope_type == 'SeeStar':
                        if 'seestar' in hostname.lower() or hostname.upper().startswith('SEESTAR'):
                            logger.info(f"Found {telescope_type} telescope at {ip} (mDNS hostname: {hostname})")
                            return ip, None
                        else:
                            logger.warning(f"Hostname {hostname} doesn't match expected SeeStar pattern")
                            return None, f"Hostname {hostname} doesn't match expected SeeStar pattern"

                    # For StellarMate, trust the mDNS hostname and skip reverse DNS
                    elif telescope_type == 'StellarMate':
                        if 'stellarmate' in hostname.lower() or hostname.upper().startswith('STELLARMATE'):
                            logger.info(f"Found {telescope_type} telescope at {ip} (mDNS hostname: {hostname})")
                            return ip, None
                        else:
                            logger.warning(f"Hostname {hostname} doesn't match expected StellarMate pattern")
                            return None, f"Hostname {hostname} doesn't match expected StellarMate pattern"

                    # For other telescope types, check if the provided hostname matches
                    elif self.is_target_device(hostname, telescope_type):
                        logger.info(f"Found {telescope_type} telescope at {ip} (user provided hostname: {hostname})")
                        return ip, None

                logger.warning(f"Device {hostname} ({ip}) not found or not accessible")
                return None, f"Device {hostname} not found or not accessible"
            except Exception:
                logger.exception(f"Unable to resolve hostname {hostname}")
                return None, f"Unable to resolve hostname {hostname}"

        # For SeeStar, try the default mDNS hostname first before network scanning
        if telescope_type == 'SeeStar':
            default_hostname = self.supported_telescopes['SeeStar']['default_hostname']
            logger.info(f"Trying default mDNS hostname: {default_hostname}")
            try:
                ip = socket.gethostbyname(default_hostname)
                if self.check_smb_port(ip):
                    logger.info(f"Found {telescope_type} telescope at {ip} via mDNS ({default_hostname})")
                    return ip, None
            except Exception as e:
                logger.debug(f"Default mDNS hostname {default_hostname} not reachable: {e}")

        # For StellarMate, try the default mDNS hostname first before network scanning
        elif telescope_type == 'StellarMate':
            default_hostname = self.supported_telescopes['StellarMate']['default_hostname']
            logger.info(f"Trying default mDNS hostname: {default_hostname}")
            try:
                ip = socket.gethostbyname(default_hostname)
                if self.check_smb_port(ip):
                    logger.info(f"Found {telescope_type} telescope at {ip} via mDNS ({default_hostname})")
                    return ip, None
            except Exception as e:
                logger.debug(f"Default mDNS hostname {default_hostname} not reachable: {e}")

        # Scan network for device (no reverse DNS lookups for SeeStar, skip entirely for iTelescope)
        if telescope_type == 'iTelescope':
            logger.error("iTelescope should have been handled above - network scanning not applicable")
            return None, "iTelescope configuration error"

        if not network_range:
            network_range = self.get_local_network()
            logger.debug(f"Using auto-detected network range: {network_range}")

        try:
            network = ipaddress.IPv4Network(network_range, strict=False)
            logger.info(f"Scanning network {network} for {telescope_type} devices...")
        except ValueError as e:
            logger.exception(f"Invalid network range {network_range}")
            return None, f"Invalid network range: {e}"

        # Use ThreadPoolExecutor for parallel scanning
        with ThreadPoolExecutor(max_workers=50) as executor:
            # Submit scan jobs for all IPs in the network
            future_to_ip = {executor.submit(self._scan_ip_for_telescope, ip, telescope_type): ip for ip in network.hosts()}
            logger.debug(f"Submitted {len(future_to_ip)} scan tasks")

            # Process completed scans
            completed = 0
            for future in as_completed(future_to_ip):
                completed += 1
                if completed % 50 == 0:  # Log progress every 50 IPs
                    logger.debug(f"Scanned {completed}/{len(future_to_ip)} IPs...")

                result = future.result()
                if result:
                    logger.info(f"Found {telescope_type} telescope at {result}")
                    return result, None

        logger.warning(f"No {telescope_type} device found on network {network_range}")
        return None, f"No {telescope_type} device found on network {network_range}"

    def _scan_ip_for_telescope(self, ip, telescope_type):
        """Scan a single IP for the target telescope type."""
        config = self.supported_telescopes.get(telescope_type, {})

        if config.get('protocol') == 'ftp':
            # For DWARF telescopes using FTP
            if self.check_ftp_port(ip):
                logger.debug(f"Found FTP service at {ip} - potential {telescope_type} device")
                return str(ip)
        else:
            # For SMB-based telescopes (SeeStar, StellarMate)
            if self.check_smb_port(ip):
                if telescope_type in ['SeeStar', 'StellarMate']:
                    logger.debug(f"Found SMB service at {ip} - potential {telescope_type} device")
                    return str(ip)
                else:
                    # For other telescope types, still use reverse DNS if needed
                    hostname = self.get_hostname(ip)
                    if self.is_target_device(hostname, telescope_type):
                        return str(ip)
        return None

    def get_fits_files(self, telescope_type, ip, username=None, password=None):
        """Get all FITS files from the telescope."""
        logger.info(f"Starting FITS file discovery on {telescope_type} at {ip}")

        config = self.supported_telescopes.get(telescope_type)
        if not config:
            logger.error(f"Unsupported telescope type: {telescope_type}")
            return [], f"Unsupported telescope type: {telescope_type}"

        # Check protocol type
        if config.get('protocol') == 'ftp':
            return self._get_fits_files_ftp(telescope_type, ip, username, password)
        elif config.get('protocol') == 'ftps':
            return self._get_fits_files_ftps(telescope_type, ip, username, password)
        elif config.get('protocol') == 'sftp':
            return self._get_fits_files_sftp(ip)
        else:
            return self._get_fits_files_smb(telescope_type, ip, username, password)


    def _extract_object_from_filename(self, filename):
        """Extract object name from iTelescope filename if possible."""
        # iTelescope filenames might contain object information
        # This is a basic implementation - may need refinement based on actual filename patterns
        try:
            # Remove 'calibrated' prefix and file extension
            base_name = filename.lower()
            base_name = base_name.removeprefix('calibrated')  # Remove 'calibrated' prefix
            base_name = base_name.removeprefix('_')  # Remove leading underscore

            # Remove file extension
            if base_name.endswith('.fit.zip'):
                base_name = base_name[:-8]  # Remove '.fit.zip' extension
            elif base_name.endswith('.fits'):
                base_name = base_name[:-5]
            elif base_name.endswith('.fit'):
                base_name = base_name[:-4]

            # Extract first part which might be object name
            parts = base_name.split('_')
            if parts:
                return parts[0].title()

        except Exception:
            logger.debug("Could not derive object name from filename", exc_info=True)

        return "Unknown"

    def download_file(self, telescope_type, ip, file_info, local_path, username=None, password=None, progress_callback=None):
        """Download a specific file from the telescope."""
        file_name = os.path.basename(file_info['path'])
        logger.info(f"Starting download of {file_name} ({self.format_file_size(file_info['size'])}) from {ip}")

        config = self.supported_telescopes.get(telescope_type)
        if not config:
            logger.error(f"Unsupported telescope type for download: {telescope_type}")
            return False, f"Unsupported telescope type: {telescope_type}"

        # Check protocol type
        if config.get('protocol') == 'ftp':
            return self._download_file_ftp(telescope_type, ip, file_info, local_path, progress_callback)
        elif config.get('protocol') == 'ftps':
            return self._download_file_ftps(telescope_type, ip, file_info, local_path, username, password, progress_callback)
        elif config.get('protocol') == 'sftp':
            return self._download_file_sftp(ip, file_info, local_path, progress_callback)
        else:
            return self._download_file_smb(telescope_type, ip, file_info, local_path, username, password, progress_callback)


    def format_file_size(self, size_bytes):
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1

        return f"{size_bytes:.1f} {size_names[i]}"

    # --- SFTP (EXT-120, LIB-170) ----------------------------------------------


    def delete_file(self, telescope_type, ip, file_info):
        """Delete a file from the telescope."""
        if telescope_type == 'SFTP':
            return self._delete_file_sftp(ip, file_info)

        if not SMB_AVAILABLE:
            return False, "SMB library not available"

        try:
            config = self.supported_telescopes.get(telescope_type)
            if not config:
                return False, f"Unsupported telescope type: {telescope_type}"

            conn = SMBConnection(
                config['default_username'],
                config['default_password'],
                "galileo",
                ip,
                use_ntlm_v2=True
            )

            if not conn.connect(ip, 445):
                return False, "Failed to connect to telescope"

            try:
                # Delete the file
                file_name = file_info['name']
                file_path = file_info['path']
                share_name = file_info['share_name']

                logger.debug(f"Deleting file {file_name} from {ip}")
                conn.deleteFiles(share_name, file_path)

                logger.info(f"Successfully deleted {file_name} from telescope")
                conn.close()
                return True, None

            except Exception as e:
                conn.close()
                logger.exception(f"Error deleting {file_name}")
                return False, f"Error deleting file: {e}"

        except Exception as e:
            logger.exception(f"Connection error during deletion of {file_info.get('name', 'unknown file')}")
            return False, f"Connection error: {e}"

# Global instance
smart_telescope_manager = SmartTelescopeManager()
