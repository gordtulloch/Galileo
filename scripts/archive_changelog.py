#!/usr/bin/env python3
"""Archive the [Unreleased] section of CHANGELOG.md as a versioned release.

Usage: python scripts/archive_changelog.py <version> [YYYY-MM-DD]

Moves everything under ``## [Unreleased]`` into ``docs/changelog/<version>.md``, leaves ``[Unreleased]`` empty and adds
a row at the top of the Releases table in CHANGELOG.md. Refuses to run when [Unreleased] is empty or the archive exists.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
ARCHIVE_DIR = ROOT / "docs" / "changelog"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    version = sys.argv[1].removeprefix("v")
    when = sys.argv[2] if len(sys.argv) > 2 else datetime.now().astimezone().date().isoformat()
    archive = ARCHIVE_DIR / f"{version}.md"
    if archive.exists():
        sys.exit(f"{archive} already exists; refusing to overwrite")

    raw = CHANGELOG.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    m = re.search(r"^## \[Unreleased\]\n(.*?)^## Releases\n", text, re.DOTALL | re.MULTILINE)
    if not m or not m.group(1).strip():
        sys.exit("nothing under [Unreleased] to archive")
    body = m.group(1).strip("\n")

    archive.write_text(
        f"# Changelog: {version} ({when})\n\n"
        f"Shipped as [v{version}](https://github.com/gordtulloch/Galileo/releases/tag/v{version}). "
        f"Back to the [current changelog](../../CHANGELOG.md).\n\n{body}\n",
        encoding="utf-8", newline="\n",
    )

    row = (f"| {version} | {when} | [Changelog](docs/changelog/{version}.md), "
           f"[GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v{version}) |\n")
    text = text[:m.start()] + "## [Unreleased]\n\n## Releases\n" + text[m.end():]
    text = re.sub(r"(\|---\|---\|---\|\n)", lambda g: g.group(1) + row, text, count=1)
    CHANGELOG.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"archived to {archive.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
