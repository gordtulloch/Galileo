#!/usr/bin/env python3
"""Report how many times each Galileo installer has been downloaded from GitHub.

Usage: python scripts/download_stats.py [--repo OWNER/NAME] [--json]

GitHub keeps a ``download_count`` on every release asset, and the web site's download buttons link straight to the
release asset URLs, so that count covers downloads from the site and from the Releases page alike. This reads it from
the GitHub CLI when installed (``gh``), else the public API (no token needed; set GITHUB_TOKEN to lift the
60-requests/hour anonymous limit), and prints a table per
release plus per-platform and overall totals. Counts are cumulative and include re-downloads and bots; the Windows
updater and package-manager fetches are counted too.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

DEFAULT_REPO = "gordtulloch/Galileo"
INSTALLER = re.compile(r"\.(exe|dmg|AppImage)$", re.IGNORECASE)


def platform_of(name: str) -> str:
    n = name.lower()
    if n.endswith(".exe"):
        return "Windows"
    if n.endswith(".dmg"):
        return "macOS"
    if n.endswith(".appimage"):
        return "Linux aarch64" if "aarch64" in n or "arm64" in n else "Linux x86_64"
    return "Other"


def fetch_releases(repo: str) -> list[dict]:
    if shutil.which("gh"):  # authenticated, and uses the system certificate store
        out = subprocess.run(["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return [rel for page in json.loads(out.stdout) for rel in page]
    releases: list[dict] = []
    page = 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "galileo-download-stats"},
        )
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        releases += batch
        if len(batch) < 100:
            return releases
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"OWNER/NAME (default {DEFAULT_REPO})")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    args = ap.parse_args()

    rows = []  # (tag, published, asset name, platform, count)
    for rel in fetch_releases(args.repo):
        for a in rel.get("assets", []):
            if INSTALLER.search(a["name"]):
                rows.append((rel["tag_name"], (rel.get("published_at") or "")[:10], a["name"],
                             platform_of(a["name"]), a["download_count"]))

    by_platform: dict[str, int] = {}
    for *_, plat, n in rows:
        by_platform[plat] = by_platform.get(plat, 0) + n
    total = sum(by_platform.values())

    if args.json:
        json.dump({"repo": args.repo, "total": total, "by_platform": by_platform,
                   "assets": [dict(zip(("tag", "published", "file", "platform", "downloads"), r)) for r in rows]},
                  sys.stdout, indent=2)
        print()
        return

    last = None
    for tag, published, name, _plat, n in rows:
        if tag != last:
            print(f"\n{tag}  ({published})")
            last = tag
        print(f"  {n:>7,}  {name}")
    print("\nBy platform")
    for plat, n in sorted(by_platform.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>7,}  {plat}")
    print(f"\nTotal installer downloads: {total:,}")


if __name__ == "__main__":
    main()
