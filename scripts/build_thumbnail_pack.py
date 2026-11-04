#!/usr/bin/env python3
"""Build the catalog thumbnail pack to upload to galileo-imaging.com (SKY-080).

Usage: python scripts/build_thumbnail_pack.py [--out galileo-thumbnails.zip] [--workers 4] [--limit N]

Downloads a sky-survey thumbnail (CDS hips2fits, DSS2 colour) for every object in the bundled catalog and
packs them into one ZIP. Galileo's Options > Planning > "Download Catalog Images" fetches that ZIP from
``galileo.planning.thumbnail_pack.PACK_URL`` and unpacks it into the thumbnail cache, so users make one
request instead of tens of thousands.

Images already in the local thumbnail cache are reused without a request; newly fetched ones go into that
cache too, so an interrupted run resumes where it stopped and a re-run
after a catalog update only fetches the new objects. Upload the resulting ZIP to the URL above.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path("galileo-thumbnails.zip"), help="ZIP file to write")
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel requests (default 4 — be kind to the free hips2fits service)")
    parser.add_argument("--limit", type=int, default=0, help="only the first N catalog objects (for a trial run)")
    args = parser.parse_args()

    from galileo.planning.sky_atlas import SkyAtlas
    from galileo.planning.thumbnail_pack import build_pack

    catalog = list(SkyAtlas()._catalog)
    if args.limit > 0:
        catalog = catalog[:args.limit]
    print(f"Building a thumbnail pack for {len(catalog):,} catalog objects -> {args.out}")

    started = time.monotonic()

    def progress(done: int, total: int) -> None:
        rate = done / max(time.monotonic() - started, 1e-6)
        eta = (total - done) / rate if rate else 0
        print(f"\r{done:,} / {total:,}  ({rate:.1f}/s, about {eta / 60:.0f} min left)   ", end="", flush=True)

    try:
        included, failed, from_cache = build_pack(args.out, catalog, workers=args.workers, progress=progress)
    except KeyboardInterrupt:
        sys.exit("\nInterrupted — fetched images are cached; run again to resume.")
    print(f"\nDone: {included:,} thumbnails in {args.out} ({args.out.stat().st_size / 1e6:.1f} MB), "
          f"{from_cache:,} already in the local cache (not re-downloaded), {failed:,} failed (no image available — re-run to retry them).")
    print("Upload the file to https://www.galileo-imaging.com/downloads/galileo-thumbnails.zip")


if __name__ == "__main__":
    main()
