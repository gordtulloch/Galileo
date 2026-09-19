# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""
galileo.commands.sync_repo - Command line utility to synchronize repository database with existing files

This script scans the repository folder for existing FITS and XISF files and updates the database
to match the actual files on disk. It does not move any files but ensures the database accurately
reflects what's currently in the repository.

Usage:
    python -m galileo.commands.sync_repo [options]

Options:
    -h, --help      Show this help message and exit
    -v, --verbose   Enable verbose logging
    -c, --config    Path to configuration file (default: library.ini in the Galileo config folder)
    -r, --repo      Override repository folder path
    -n, --clear     Clear database before sync (recommended for clean sync)

Requirements:
    - library.ini configuration file (Options > Library)
    - Valid repository folder path
    - Write permissions to repository folder

Example:
    # Sync repository with default settings
    python -m galileo.commands.sync_repo
    
    # Sync with verbose output and clear database first
    python -m galileo.commands.sync_repo -v -n
    
    # Sync with custom config file
    python -m galileo.commands.sync_repo -c /path/to/config.ini
    
    # Sync specific repository folder
    python -m galileo.commands.sync_repo -r /path/to/repository
"""

import sys
import os
import argparse
import logging
import configparser
from datetime import datetime



from galileo.library.core import fitsProcessing
from galileo.library.database import setup_database

from galileo.commands._common import get_log_path, load_config

def setup_logging(verbose=False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Configure logging - using central library.log
    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[
            logging.FileHandler(get_log_path(), mode='a', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

def validate_paths(repo_folder):
    """Validate repository folder path."""
    if not os.path.exists(repo_folder):
        raise FileNotFoundError(f"Repository folder does not exist: {repo_folder}")
    
    # Check write permissions
    if not os.access(repo_folder, os.W_OK):
        raise PermissionError(f"No write permission for repository folder: {repo_folder}")

def main():
    """Main function to sync repository database from command line."""
    parser = argparse.ArgumentParser(
        description="Synchronize repository database with existing FITS and XISF files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m galileo.commands.sync_repo                     # Sync with default settings
    python -m galileo.commands.sync_repo -v                  # Verbose output
    python -m galileo.commands.sync_repo -c custom.ini       # Custom config file
    python -m galileo.commands.sync_repo -r /path/to/repo    # Override repository folder
    python -m galileo.commands.sync_repo -n                  # Clear database before sync
        """
    )
    
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('-c', '--config', default=None,
                        help='Path to configuration file (default: library.ini in the Galileo config folder)')
    parser.add_argument('-r', '--repo',
                        help='Override repository folder path')
    parser.add_argument('-n', '--clear', action='store_true',
                        help="Clear database before sync (recommended for clean sync)")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    try:
        logger.info("=== Galileo Repository Sync Starting ===")
        logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        
        # Load configuration
        logger.info(f"Loading configuration from: {args.config or 'library.ini'}")
        config = load_config(args.config)
        
        # Get repository folder path
        repo_folder = args.repo or config.get('DEFAULT', 'repo', fallback='.')
        
        # Convert to absolute path
        repo_folder = os.path.abspath(repo_folder)
        
        logger.info(f"Repository folder: {repo_folder}")
        logger.info(f"Clear database: {args.clear}")
        
        # Validate paths
        validate_paths(repo_folder)
        
        # Setup database
        logger.info("Setting up database...")
        setup_database()
        
        # If clear mode requested, clear the database tables first
        if args.clear:
            logger.info("Clear mode detected - clearing database tables...")
            try:
                from galileo.library.models import fitsFile, fitsSession, Mapping, Masters
                
                # Clear all tables in dependency order
                logger.info("Clearing fitsFile table...")
                fitsFile.delete().execute()
                
                logger.info("Clearing fitsSession table...")
                fitsSession.delete().execute()
                               
                logger.info("Database tables cleared successfully for sync.")
                
            except Exception as e:
                logger.error(f"Error clearing database tables: {e}")
                raise
        
        # Create processor instance
        processor = fitsProcessing()
        
        # Override repository folder path if specified
        if args.repo:
            processor.repoFolder = repo_folder
        
        # Process files - scan the repository folder instead of source folder
        logger.info("Starting repository sync...")
        
        result = processor.registerFitsImages(
            moveFiles=False,  # Never move files during sync
            progress_callback=None,  # Disabled for non-interactive use
            source_folder=repo_folder  # Use repository folder as source
        )
        
        # Handle the new tuple return format (registered_files, duplicate_count)
        if isinstance(result, tuple):
            registered_files, duplicate_count = result
        else:
            # Backward compatibility for old return format
            registered_files = result
            duplicate_count = 0
        
        # Report results
        logger.info(f"=== Repository Sync Complete ===")
        logger.info(f"Files synchronized: {len(registered_files)}")
        if duplicate_count > 0:
            logger.info(f"Duplicate files skipped: {duplicate_count}")
        
        if len(registered_files) == 0:
            if duplicate_count > 0:
                logger.warning(f"No new FITS/XISF files synchronized! {duplicate_count} duplicate files were skipped.")
            else:
                logger.warning("No FITS or XISF files found to synchronize!")
            return 1
        else:
            logger.info("Repository sync completed successfully!")
            return 0
            
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user (Ctrl+C)")
        return 1
    except Exception as e:
        logger.error(f"Error during repository sync: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())