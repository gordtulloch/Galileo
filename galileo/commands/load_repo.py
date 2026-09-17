"""CLI: repository scan and ingest (LIB-010, LIB-130, EXT-140)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Galileo: Scan a FITS repository and update the catalog."
    )
    parser.add_argument("repo_dir", help="Root directory of the FITS repository")
    parser.add_argument("--db", default=None, help="Path to the Galileo database file")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive mode")
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir)
    if not repo_dir.is_dir():
        print(f"Error: {repo_dir} is not a directory", file=sys.stderr)
        return 1

    from galileo.library.database import init_db
    from galileo.library.repository import Repository

    init_db(args.db)
    repo = Repository(root=repo_dir)
    print(f"Scanning {repo_dir} …")
    repo.scan()
    count = repo.entry_count()
    print(f"Scanned {count} FITS file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
