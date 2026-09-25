# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""
galileo.commands.link_sessions - Command line utility for linking calibration sessions to light sessions

This script links calibration sessions (bias, dark, flat) to light sessions based on
matching telescope and imager combinations. For each light session, it finds the most
recent calibration sessions that match the telescope and imager.

Usage:
    python -m galileo.commands.link_sessions [options]

Options:
    -h, --help      Show help message
    -v, --verbose   Enable verbose logging
    -c, --config    Path to configuration file (default: library.ini in the Galileo config folder)

Examples:
    python -m galileo.commands.link_sessions
    python -m galileo.commands.link_sessions -v
    python -m galileo.commands.link_sessions -c /path/to/config.ini
"""

import argparse
import logging
import os
import sys
from datetime import datetime



from galileo.library.core import fitsProcessing
from galileo.library.database import setup_database

from galileo.commands._common import get_log_path, load_config
from galileo.library.config import get_config_path

def setup_logging(verbose=False):
    """Setup logging configuration."""
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'linksessions.log')

    # Configure logging - using central library.log
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(get_log_path(), mode='a', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger(__name__)

def main():
    """Main function to parse arguments and run session linking."""
    parser = argparse.ArgumentParser(
        description="Link calibration sessions to light sessions based on telescope and imager matching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m galileo.commands.link_sessions                     # Link sessions with default config
    python -m galileo.commands.link_sessions -v                 # Link sessions with verbose output
    python -m galileo.commands.link_sessions -c config.ini      # Link sessions with custom config file
        """
    )

    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('-c', '--config', default=None,
                        help='Path to configuration file (default: library.ini in the Galileo config folder)')

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.verbose)

    try:
        logger.info("Starting session linking process")
        logger.info(f"Config file: {get_config_path()}")

        try:
            load_config(args.config)
        except FileNotFoundError as e:
            logger.error(str(e))
            sys.exit(1)

        # Initialize database
        logger.info("Setting up database connection")
        setup_database()

        # Create processing instance
        logger.info("Initializing FITS processing")
        fits_processor = fitsProcessing()

        # Define progress callback for non-interactive mode
        def progress_callback(current, total, session_name):
            if args.verbose:
                logger.info(f"Processing session {current}/{total}: {session_name}")
            return True  # Always continue in non-interactive mode

        # Run session linking
        logger.info("Starting session linking...")
        start_time = datetime.now()

        updated_sessions = fits_processor.linkSessions(progress_callback=progress_callback)

        end_time = datetime.now()
        processing_time = end_time - start_time

        # Log results
        logger.info(f"Session linking completed in {processing_time}")
        logger.info(f"Successfully linked {len(updated_sessions)} light sessions with calibration sessions")

        if args.verbose and updated_sessions:
            logger.info("Updated session IDs:")
            for session_id in updated_sessions:
                logger.info(f"  - {session_id}")

        print("Session linking completed successfully!")
        print(f"Updated {len(updated_sessions)} light sessions with calibration links")
        print(f"Processing time: {processing_time}")

    except KeyboardInterrupt:
        logger.info("Session linking cancelled by user")
        print("Session linking cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during session linking: {e}")
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
