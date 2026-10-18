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
            'Celestron Origin': {
                'default_hostname': '192.168.1.208',  # Default IP on the Origin hotspot network
                'default_username': None,  # nosec B105 -- anonymous FTP
                'default_password': None,
                'protocol': 'ftp',  # Plain FTP (not FTPS)
                'fits_path': 'RawData',  # Raw FITS are stored in /RawData
                'port': 21
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

    def get_celestron_hostname(self):
        """The Celestron Origin's hostname or IP from the library settings ('' if unset)."""
        try:
            config = load_library_config()
            return config.get('DEFAULT', 'celestron_hostname', fallback='').strip()
        except Exception as e:
            logger.exception(f"Error reading Celestron Origin hostname: {e}")
            return ''

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

        hostname_lower = hostname.lower()
        if telescope_type == 'SeeStar':
            return 'seestar' in hostname_lower
        elif telescope_type == 'StellarMate':
            return 'stellarmate' in hostname_lower
        elif telescope_type == 'Celestron Origin':
            hostname_parts = hostname_lower.replace('-', '.').split('.')
            return 'origin' in hostname_lower or 'celestron' in hostname_parts

        return False

    def _is_ip_address(self, hostname):
        """True if *hostname* is already an IP address."""
        try:
            ipaddress.ip_address(hostname)
            return True
        except ValueError:
            return False

    def find_telescope(self, telescope_type, network_range=None, hostname=None):
        """Find a specific telescope on the network."""
        logger.info(f"Starting search for {telescope_type} telescope (hostname={hostname}, network={network_range})")

        config = self.supported_telescopes.get(telescope_type, {})
        protocol = config.get('protocol', 'smb')

        # An Origin the user has saved an address for is used in preference to its hotspot default
        if telescope_type == 'Celestron Origin' and not hostname:
            hostname = self.get_celestron_hostname() or None

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

        if protocol == 'smb' and not SMB_AVAILABLE:
            logger.error("SMB protocol not available. Install pysmb package.")
            return None, "SMB protocol not available. Install pysmb package."

        if hostname:
            # For SeeStar, only use mDNS resolution for seestar.local hostnames
            # No reverse DNS lookups as SeeStar patched their firmware to disable them
            try:
                logger.debug(f"Resolving hostname {hostname}")
                ip = socket.gethostbyname(hostname)
                logger.debug(f"Hostname {hostname} resolved to {ip}")

                port_open = self.check_ftp_port(ip) if protocol == 'ftp' else self.check_smb_port(ip)
                if port_open:
                    # For SeeStar, trust the mDNS hostname and skip reverse DNS
                    if telescope_type == 'SeeStar':
                        if 'seestar' in hostname.lower() or hostname.upper().startswith('SEESTAR'):
                            logger.info(f"Found {telescope_type} telescope at {ip} (mDNS hostname: {hostname})")
                            return ip, None
                        logger.warning(f"Hostname {hostname} doesn't match expected SeeStar pattern")
                        return None, f"Hostname {hostname} doesn't match expected SeeStar pattern"

                    # For StellarMate, trust the mDNS hostname and skip reverse DNS
                    elif telescope_type == 'StellarMate':
                        if 'stellarmate' in hostname.lower() or hostname.upper().startswith('STELLARMATE'):
                            logger.info(f"Found {telescope_type} telescope at {ip} (mDNS hostname: {hostname})")
                            return ip, None
                        logger.warning(f"Hostname {hostname} doesn't match expected StellarMate pattern")
                        return None, f"Hostname {hostname} doesn't match expected StellarMate pattern"

                    # A DWARF answers on whatever address the user gave (192.168.88.1 on its own hotspot)
                    elif telescope_type == 'DWARF 3':
                        logger.info(f"Found {telescope_type} telescope at {ip} (user provided hostname: {hostname})")
                        return ip, None

                    # A Celestron Origin is addressed by IP or by an origin/celestron hostname
                    elif telescope_type == 'Celestron Origin':
                        if self.is_target_device(hostname, telescope_type) or self._is_ip_address(hostname):
                            logger.info(f"Found {telescope_type} telescope at {ip} (user provided hostname: {hostname})")
                            return ip, None
                        logger.warning(f"Hostname {hostname} doesn't match expected {telescope_type} pattern")
                        return None, f"Hostname {hostname} doesn't match expected {telescope_type} pattern"

                    # For other telescope types, check if the provided hostname matches
                    elif self.is_target_device(hostname, telescope_type):
                        logger.info(f"Found {telescope_type} telescope at {ip} (user provided hostname: {hostname})")
                        return ip, None
                    else:
                        logger.warning(f"Hostname {hostname} doesn't match expected {telescope_type} pattern")
                        return None, f"Hostname {hostname} doesn't match expected {telescope_type} pattern"

                logger.warning(f"Device {hostname} found but service port is closed")
                return None, f"Device {hostname} found but service port is closed"
            except Exception as e:
                logger.exception(f"Unable to resolve hostname {hostname}: {e}")
                return None, f"Unable to resolve hostname {hostname}"

        # Try the model's default hostname (mDNS name or hotspot address) before scanning the network
        default_hostname = config.get('default_hostname')
        if default_hostname:
            logger.info(f"Trying default hostname: {default_hostname}")
            try:
                ip = socket.gethostbyname(default_hostname)
                port_open = self.check_ftp_port(ip) if protocol == 'ftp' else self.check_smb_port(ip)
                if port_open:
                    logger.info(f"Found {telescope_type} telescope at {ip} via default hostname ({default_hostname})")
                    return ip, None
            except Exception as e:
                logger.debug(f"Default hostname {default_hostname} not reachable: {e}")

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

    def _get_fits_files_smb(self, telescope_type, ip, username=None, password=None):
        """Get FITS files via SMB protocol (SeeStar)."""
        if not SMB_AVAILABLE:
            logger.error("SMB protocol not available")
            return [], "SMB protocol not available"

        config = self.supported_telescopes.get(telescope_type)
        username = username or config['default_username']
        password = password or config['default_password']
        share_name = config['share_name']
        fits_path = config['fits_path']

        logger.debug(f"Using SMB share: {share_name}, path: {fits_path}, username: {username}")

        try:
            # Create SMB connection
            conn = SMBConnection(username, password, "client", "server", use_ntlm_v2=True)

            # Try to connect
            logger.debug(f"Attempting SMB connection to {ip}:445...")
            connected = conn.connect(str(ip), 445, timeout=10)

            if not connected:
                logger.error(f"Failed to connect to SMB service at {ip}")
                return [], "Failed to connect to SMB service"

            logger.info(f"Successfully connected to SMB service at {ip}")

            try:
                # Get FITS files from the specified path
                logger.debug(f"Scanning for FITS files in {share_name}/{fits_path}")
                start_time = time.time()
                fits_files = self._get_fits_files_from_path_smb(conn, share_name, fits_path, telescope_type)
                scan_time = time.time() - start_time

                conn.close()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                conn.close()
                logger.exception(f"Error accessing files on {ip}: {e}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"Connection error to {ip}: {e}")
            return [], f"Connection error: {e}"

    def _get_fits_files_ftp(self, telescope_type, ip, username=None, password=None):
        """Get FITS files via FTP protocol (DWARF, Celestron Origin)."""
        logger.info(f"Using FTP connection for {telescope_type}")

        config = self.supported_telescopes.get(telescope_type)

        try:
            # Create FTP connection (no authentication for DWARF or Origin)
            ftp = ftplib.FTP()  # noqa: S321  # nosec B321 -- plain FTP: the device offers nothing else (LAN-only)
            logger.debug(f"Attempting FTP connection to {ip}:21...")
            ftp.connect(ip, 21, timeout=10)

            # Anonymous login (no username/password for DWARF)
            ftp.login()
            logger.info(f"Successfully connected to FTP service at {ip}")

            try:
                if telescope_type == 'DWARF 3':
                    # Check for DWARF folder structure
                    if not self._validate_dwarf_structure(ftp):
                        ftp.quit()
                        return [], "DWARF folder structure not recognized"

                    # Get FITS files from DWARF structure
                    start_time = time.time()
                    fits_files = self._get_fits_files_from_dwarf_ftp(ftp)
                    scan_time = time.time() - start_time
                elif telescope_type == 'Celestron Origin':
                    start_time = time.time()
                    fits_files = self._get_fits_files_from_celestron_ftp(ftp, config.get('fits_path', 'RawData'))
                    scan_time = time.time() - start_time
                else:
                    ftp.quit()
                    return [], f"Unsupported FTP telescope type: {telescope_type}"

                ftp.quit()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                ftp.quit()
                logger.exception(f"Error accessing files on {ip}: {e}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"FTP connection error to {ip}: {e}")
            return [], f"FTP connection error: {e}"

    def _get_fits_files_ftps(self, telescope_type, hostname, username=None, password=None):
        """Get FITS files via FTPS protocol (iTelescope)."""
        logger.info(f"Using FTPS connection for {telescope_type}")

        if not username or not password:
            logger.error("Username and password required for iTelescope FTPS connection")
            return [], "Username and password required for iTelescope FTPS connection"

        try:
            # Create FTPS connection (FTP over TLS)
            ftps = _new_ftps_client()
            logger.debug(f"Attempting FTPS connection to {hostname}:21...")
            ftps.connect(hostname, 21, timeout=30)

            # Login with user credentials
            ftps.login(username, password)

            # Switch to secure data connection
            ftps.prot_p()
            logger.info(f"Successfully connected to FTPS service at {hostname}")

            try:
                # Get FITS files from iTelescope structure
                start_time = time.time()
                fits_files = self._get_fits_files_from_itelescope_ftps(ftps, hostname)
                scan_time = time.time() - start_time

                ftps.quit()
                logger.info(f"Found {len(fits_files)} FITS files in {scan_time:.2f} seconds")
                return fits_files, None

            except Exception as e:
                ftps.quit()
                logger.exception(f"Error accessing files on {hostname}: {e}")
                return [], f"Error accessing files: {e}"

        except Exception as e:
            logger.exception(f"FTPS connection error to {hostname}: {e}")
            return [], f"FTPS connection error: {e}"

    def _get_fits_files_from_path_smb(self, conn, share_name, target_path, telescope_type):
        """Get all FITS files from folders ending in '_sub' within the target path."""
        fits_files = []
        visited_paths = set()  # Prevent infinite loops
        max_depth = 10  # Limit recursion depth

        def scan_directory(path="", depth=0):
            # Prevent infinite recursion
            if depth > max_depth:
                logger.debug(f"Maximum depth reached at '{path}', stopping recursion")
                return

            # Prevent revisiting the same path
            if path in visited_paths:
                return
            visited_paths.add(path)

            try:
                # List files in the directory
                logger.debug(f"Scanning directory: '{path}' (depth: {depth})")
                files = conn.listPath(share_name, path or "/")

                for file_info in files:
                    if file_info.filename in ['.', '..']:
                        continue

                    item_path = os.path.join(path, file_info.filename).replace('\\', '/') if path else file_info.filename

                    if file_info.isDirectory:
                        # If we haven't found the target directory yet, keep looking
                        if not path and file_info.filename == target_path:
                            logger.debug(f"Found target directory: {target_path}")
                            scan_directory(item_path, depth + 1)
                        elif path.startswith(target_path + "/") or path == target_path:
                            # We're inside the target directory
                            # Only scan subdirectories that end with '_sub'
                            if file_info.filename.endswith('_sub'):
                                logger.debug(f"Found _sub directory: {file_info.filename}")
                                scan_directory(item_path, depth + 1)
                            else:
                                logger.debug(f"Skipping non-_sub directory: {file_info.filename}")
                        elif not path:
                            # Still looking for the target directory at root level
                            scan_directory(item_path, depth + 1)
                    else:
                        # Check if it's a FITS file and we're in a _sub folder within the target path
                        current_folder = os.path.basename(path) if path else ""
                        if ((path == target_path or path.startswith(target_path + "/")) and
                            current_folder.endswith('_sub') and
                            (file_info.filename.lower().endswith('.fits') or
                             file_info.filename.lower().endswith('.fit'))):

                            logger.debug(f"Found FITS file: {file_info.filename} in {path}")
                            fits_files.append({
                                "name": file_info.filename,
                                "path": item_path,
                                "size": file_info.file_size,
                                "date": str(file_info.last_write_time),
                                "share_name": share_name,
                                "folder_name": current_folder  # Add folder name for header processing
                            })

            except Exception as e:
                logger.debug(f"Error scanning directory '{path}': {e}")

        # Start scanning from root
        logger.debug(f"Starting scan for target directory: {target_path} (looking for folders ending in '_sub')")
        scan_directory()

        logger.debug(f"Scan complete. Found {len(fits_files)} FITS files in _sub folders.")
        return fits_files

    def _validate_dwarf_structure(self, ftp):
        """Validate that FTP root contains required DWARF folder structure."""
        try:
            files = ftp.nlst('/')
            required_folders = ['CALI_FRAME', 'DWARF_DARK']
            dwarf_raw_folders = [f for f in files if f.startswith('DWARF_RAW')]

            has_required = all(folder in files for folder in required_folders)
            has_dwarf_raw = len(dwarf_raw_folders) > 0

            if has_required and has_dwarf_raw:
                logger.info(f"Valid DWARF structure found: {required_folders} + {len(dwarf_raw_folders)} DWARF_RAW folders")
                return True
            else:
                logger.warning(f"DWARF folder structure not recognized. Found: {files}")
                return False

        except Exception as e:
            logger.exception(f"Error validating DWARF structure: {e}")
            return False

    def _get_fits_files_from_celestron_ftp(self, ftp, fits_path='RawData'):
        """FITS files on a Celestron Origin: everything under *fits_path* (the whole drive if it is missing)."""
        fits_files = []

        try:
            logger.debug(f"Scanning Celestron Origin '{fits_path}' folder")
            try:
                ftp.cwd('/')
                if fits_path:
                    ftp.cwd(fits_path)
                    logger.debug(f"Successfully accessed /{fits_path} directory")
                    ftp.cwd('/')
                    self._scan_celestron_folder(ftp, fits_path, fits_files)
                else:
                    self._scan_celestron_folder(ftp, '', fits_files)
            except ftplib.error_perm as e:
                logger.warning(f"Directory '{fits_path}' not found ({e}), scanning from root directory")
                self._scan_celestron_folder(ftp, '', fits_files)
        except Exception as e:
            logger.exception(f"Error scanning Celestron Origin FTP structure: {e}")

        return fits_files

    def _scan_celestron_folder(self, ftp, folder_path, fits_files, depth=0, max_depth=5):
        """Recursively scan Celestron Origin folders for FITS files."""
        if depth > max_depth:
            logger.debug(f"Maximum depth reached at '{folder_path}', stopping recursion")
            return

        try:
            ftp.cwd('/')
            if folder_path:
                ftp.cwd(folder_path)

            items = []
            try:
                ftp.retrlines('LIST', items.append)
            except Exception as e:
                logger.debug(f"Could not list directory {folder_path}: {e}")
                return

            for item_line in items:
                # Parse FTP LIST output
                parts = item_line.split()
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                filename = ' '.join(parts[8:])  # filenames can contain spaces

                if filename.startswith('.'):
                    continue

                item_path = f"{folder_path}/{filename}" if folder_path else filename

                if permissions.startswith('d'):
                    logger.debug(f"Scanning Celestron subdirectory: {item_path}")
                    self._scan_celestron_folder(ftp, item_path, fits_files, depth + 1, max_depth)

                elif filename.lower().endswith(('.fits', '.fit', '.fts')):
                    # The size and date come from the LIST line (cheaper than SIZE per file)
                    try:
                        size = int(parts[4])
                    except (ValueError, IndexError):
                        size = 0
                    date_str = f"{parts[5]} {parts[6]} {parts[7]}"

                    fits_files.append({
                        "name": filename,
                        "path": item_path,
                        "size": size,
                        "date": date_str,
                        "share_name": "ftp_root",
                        "folder_name": os.path.basename(folder_path) if folder_path else "root",
                        "telescope_type": "Celestron Origin",
                        "file_type": "light",
                        "object": self._extract_object_from_filename(filename),
                        "instrument": "Celestron Origin"
                    })
                    logger.debug(f"Found Celestron Origin FITS file: {item_path}")

        except Exception as e:
            logger.exception(f"Error scanning Celestron folder {folder_path}: {e}")

    def _get_fits_files_from_dwarf_ftp(self, ftp):
        """Get FITS files from DWARF telescope via FTP."""
        fits_files = []

        try:
            # Scan root directory for DWARF_RAW folders (light files)
            files = ftp.nlst('/')
            dwarf_raw_folders = [f for f in files if f.startswith('DWARF_RAW')]

            for folder in dwarf_raw_folders:
                logger.debug(f"Scanning DWARF_RAW folder: {folder}")
                self._scan_dwarf_raw_folder(ftp, folder, fits_files)

            # Scan calibration folders
            if 'CALI_FRAME' in files:
                logger.debug("Scanning CALI_FRAME folder")
                self._scan_dwarf_cali_folder(ftp, 'CALI_FRAME', fits_files)

            if 'DWARF_DARK' in files:
                logger.debug("Scanning DWARF_DARK folder")
                self._scan_dwarf_dark_folder(ftp, 'DWARF_DARK', fits_files)

        except Exception as e:
            logger.exception(f"Error scanning DWARF FTP structure: {e}")

        return fits_files

    def _scan_dwarf_raw_folder(self, ftp, folder_name, fits_files):
        """Scan a DWARF_RAW folder for light frame FITS files."""
        try:
            # Parse folder name to extract metadata
            # Expected format: DWARF_RAW_(INSTRUMEN)_(OBJECT)_EXP_(EXPTIME)_GAIN_(GAIN)_(DATE-OBS)
            folder_parts = folder_name.split("_")
            object_name = "Unknown"
            instrument = "Unknown"
            exptime = "Unknown"
            gain = "Unknown"

            if len(folder_parts) >= 8:
                try:
                    instrument = folder_parts[2]  # INSTRUMEN
                    object_name = folder_parts[3]  # OBJECT
                    exptime = folder_parts[5]  # EXPTIME (after EXP)
                    gain = folder_parts[7]  # GAIN (after GAIN)
                except IndexError:
                    logger.warning(f"Could not parse DWARF_RAW folder name: {folder_name}")

            ftp.cwd('/')
            ftp.cwd(folder_name)
            files = ftp.nlst('.')

            for file in files:
                if file.startswith('failed_'):
                    logger.debug(f"Ignoring failed image: {file}")
                    continue

                if file.lower().endswith('.fits') or file.lower().endswith('.fit'):
                    file_path = f"{folder_name}/{file}"
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": file_path,
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": folder_name,
                        "telescope_type": "DWARF 3",
                        "file_type": "light",
                        "object": object_name,
                        "instrument": instrument,
                        "exptime": exptime,
                        "gain": gain
                    })
                    logger.debug(f"Found DWARF light file: {file_path} (Object: {object_name}, Instrument: {instrument})")

        except Exception as e:
            logger.exception(f"Error scanning DWARF_RAW folder {folder_name}: {e}")

    def _scan_dwarf_cali_folder(self, ftp, folder_name, fits_files):
        """Scan CALI_FRAME folder for calibration master frames."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_name)

            # Look for bias, dark, flat folders
            cali_types = ['bias', 'dark', 'flat']
            folders = ftp.nlst('.')

            for cali_type in cali_types:
                if cali_type in folders:
                    self._scan_dwarf_cali_type_folder(ftp, f"{folder_name}/{cali_type}", cali_type, fits_files)

        except Exception as e:
            logger.exception(f"Error scanning CALI_FRAME folder: {e}")

    def _scan_dwarf_cali_type_folder(self, ftp, folder_path, cali_type, fits_files):
        """Scan a calibration type folder (bias/dark/flat) for cam_0 and cam_1 subfolders."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_path)
            folders = ftp.nlst('.')

            # Look for cam_0 (TELE) and cam_1 (WIDE) folders
            for cam_folder in ['cam_0', 'cam_1']:
                if cam_folder in folders:
                    instrument = 'TELE' if cam_folder == 'cam_0' else 'WIDE'
                    self._scan_dwarf_cam_folder(ftp, f"{folder_path}/{cam_folder}", cali_type, instrument, fits_files)

        except Exception as e:
            logger.exception(f"Error scanning calibration type folder {folder_path}: {e}")

    def _scan_dwarf_cam_folder(self, ftp, folder_path, cali_type, instrument, fits_files):
        """Scan a camera folder for FITS files."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_path)
            files = ftp.nlst('.')

            for file in files:
                if file.lower().endswith('.fits') or file.lower().endswith('.fit'):
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": f"{folder_path}/{file}",
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": os.path.basename(folder_path),
                        "telescope_type": "DWARF 3",
                        "file_type": f"master_{cali_type}",
                        "instrument": instrument,
                        "calibration_type": cali_type
                    })
                    logger.debug(f"Found DWARF {cali_type} master file: {folder_path}/{file}")

        except Exception as e:
            logger.exception(f"Error scanning camera folder {folder_path}: {e}")

    def _scan_dwarf_dark_folder(self, ftp, folder_name, fits_files):
        """Scan DWARF_DARK folder for dark library files."""
        try:
            ftp.cwd('/')
            ftp.cwd(folder_name)
            files = ftp.nlst('.')

            for file in files:
                if file.startswith('tele_') and (file.lower().endswith('.fits') or file.lower().endswith('.fit')):
                    try:
                        size = ftp.size(file)
                    except Exception:
                        size = 0

                    fits_files.append({
                        "name": file,
                        "path": f"{folder_name}/{file}",
                        "size": size,
                        "date": "Unknown",
                        "share_name": "ftp_root",
                        "folder_name": folder_name,
                        "telescope_type": "DWARF 3",
                        "file_type": "dark_library",
                        "instrument": "TELE"
                    })
                    logger.debug(f"Found DWARF dark library file: {folder_name}/{file}")

        except Exception as e:
            logger.exception(f"Error scanning DWARF_DARK folder: {e}")

    def _get_fits_files_from_itelescope_ftps(self, ftps, hostname):
        """Get all calibrated FITS files from iTelescope FTPS server."""
        fits_files = []

        try:
            # Start from root directory
            ftps.cwd('/')

            # Recursively scan all directories for files starting with 'calibrated'
            self._scan_itelescope_directory(ftps, '', fits_files, hostname)

        except Exception as e:
            logger.exception(f"Error scanning iTelescope directories: {e}")

        return fits_files

    def _scan_itelescope_directory(self, ftps, current_path, fits_files, hostname, max_depth=10, current_depth=0):
        """Recursively scan iTelescope directory structure for calibrated files."""
        if current_depth > max_depth:
            logger.debug(f"Maximum depth reached at '{current_path}', stopping recursion")
            return

        try:
            # Change to the current directory
            if current_path:
                ftps.cwd('/')
                ftps.cwd(current_path)

            # List files and directories
            items = []
            try:
                ftps.retrlines('LIST', items.append)
            except Exception as e:
                logger.debug(f"Could not list directory {current_path}: {e}")
                return

            for item_line in items:
                # Parse FTP LIST output (Unix-style)
                # Example: -rw-r--r--   1 user group      1234 Jan 01 12:00 filename.fits
                parts = item_line.split()
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                filename = ' '.join(parts[8:])  # Handle filenames with spaces

                # Skip hidden files and current/parent directory references
                if filename.startswith('.'):
                    continue

                item_path = f"{current_path}/{filename}" if current_path else filename

                if permissions.startswith('d'):
                    # It's a directory
                    if not current_path:
                        # Root level - only scan directories that start with 'T' or 't'
                        if filename.lower().startswith('t'):
                            logger.debug(f"Scanning root telescope directory: {item_path}")
                            self._scan_itelescope_directory(ftps, item_path, fits_files, hostname, max_depth, current_depth + 1)
                        else:
                            logger.debug(f"Skipping non-telescope root directory: {filename}")
                    else:
                        # Subfolder within telescope directory - scan all subdirectories
                        logger.debug(f"Scanning telescope subdirectory: {item_path}")
                        self._scan_itelescope_directory(ftps, item_path, fits_files, hostname, max_depth, current_depth + 1)

                elif filename.lower().startswith('calibrated') and filename.lower().endswith('.fit.zip'):
                    # It's a calibrated FIT zip file
                    try:
                        # Get file size
                        if current_path:
                            ftps.cwd('/')
                            ftps.cwd(current_path)
                        size = ftps.size(filename)
                    except Exception:
                        size = 0

                    # Extract date from LIST output if possible
                    try:
                        date_str = f"{parts[5]} {parts[6]} {parts[7]}"
                    except Exception:
                        date_str = "Unknown"

                    fits_files.append({
                        "name": filename,
                        "path": item_path,
                        "size": size,
                        "date": date_str,
                        "share_name": "ftps_root",
                        "folder_name": os.path.basename(current_path) if current_path else "root",
                        "telescope_type": "iTelescope",
                        "file_type": "calibrated_light_zip",
                        "object": self._extract_object_from_filename(filename),
                        "instrument": "iTelescope",
                        "hostname": hostname
                    })
                    logger.debug(f"Found iTelescope calibrated file: {item_path}")

        except Exception as e:
            logger.exception(f"Error scanning iTelescope directory {current_path}: {e}")

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
