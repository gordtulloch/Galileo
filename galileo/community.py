# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Community & support links (SUP-010 .. SUP-030).

Pure Python (no Qt): builds the URLs the Help area opens in the user's browser. Nothing is
sent from the application -- the user reviews and submits the prefilled form on GitHub
themselves, so this works on an offline observatory machine and adds no telemetry.
"""

from __future__ import annotations

import platform
from urllib.parse import urlencode

REPO_URL = "https://github.com/gordtulloch/Galileo"
DISCUSSIONS_URL = f"{REPO_URL}/discussions"

# Discussion category slugs; the categories themselves are created in the repo settings.
CATEGORY_QA = "q-a"
CATEGORY_IDEAS = "ideas"
CATEGORY_SHOW = "show-and-tell"


def diagnostics(screen: str | None = None) -> dict[str, str]:
    """Non-sensitive facts that make a bug report actionable (version, OS, Python, screen)."""
    from galileo import __version__

    info = {
        "version": __version__,
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
    }
    if screen:
        info["screen"] = screen
    return info


def ask_url(category: str = CATEGORY_QA) -> str:
    """Start a new Discussion in *category* (Q&A by default)."""
    return f"{DISCUSSIONS_URL}/new?{urlencode({'category': category})}"


def idea_url() -> str:
    """Start a new Discussion in the Ideas category (feature requests)."""
    return ask_url(CATEGORY_IDEAS)


def report_problem_url(screen: str | None = None) -> str:
    """The bug-report issue form with version, OS, Python and the current screen prefilled.

    The query keys are the field ids in ``.github/ISSUE_TEMPLATE/bug_report.yml``.
    """
    params = {"template": "bug_report.yml", **diagnostics(screen)}
    return f"{REPO_URL}/issues/new?{urlencode(params)}"
