# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""CLI: Google Cloud Storage sync (LIB-120, LIB-130, EXT-140)."""

from __future__ import annotations

import argparse
import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Galileo: Synchronise the FITS repository with Google Cloud Storage."
    )
    parser.add_argument("--bucket", required=True, help="GCS bucket name")
    parser.add_argument("--credentials", default="", help="Path to GCS service-account JSON key")
    parser.add_argument("--profile", default="backup_only",
                        choices=["complete", "backup_only", "on_demand"],
                        help="Sync profile (default: backup_only)")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive mode")
    args = parser.parse_args(argv)

    from galileo.library.cloud import CloudSyncService

    svc = CloudSyncService(bucket_name=args.bucket, credentials_path=args.credentials)
    result = asyncio.run(svc.sync(profile=args.profile))
    print(f"Sync complete — uploaded={result['uploaded']}, downloaded={result['downloaded']}, skipped={result['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
