# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gord Tulloch
"""Write narration-only text for each video script and report its running time.

Usage: python docs/scripts/extract_narration.py [--wpm 150]
"""

import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def split_script(text: str) -> tuple[list[str], int]:
    """Return the spoken paragraphs and the total seconds of PAUSE directions."""
    spoken: list[str] = []
    pause = 0
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r">\s*PAUSE:\s*(\d+)", line)
        if match:
            pause += int(match.group(1))
        elif line and not line.startswith((">", "#", "Target running time", "Parts:")):
            spoken.append(line)
    return spoken, pause


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wpm", type=int, default=150, help="narrator speed, words per minute")
    args = parser.parse_args()

    out_dir = HERE / "narration"
    out_dir.mkdir(exist_ok=True)
    for script in sorted(HERE.glob("[0-9][0-9]-*.md")):
        spoken, pause = split_script(script.read_text(encoding="utf-8"))
        (out_dir / f"{script.stem}.txt").write_text("\n\n".join(spoken) + "\n", encoding="utf-8")
        words = sum(len(p.split()) for p in spoken)
        speech = words / args.wpm
        print(f"{script.stem:40} {words:6} words  speech {speech:5.1f} min  "
              f"pauses {pause / 60:5.1f} min  total {speech + pause / 60:5.1f} min")


if __name__ == "__main__":
    main()
