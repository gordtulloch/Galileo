# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Community & support links (SUP-010 .. SUP-030): URL building and the repository's issue/discussion forms."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from galileo import __version__, community

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.requirement("TC-SUP-010")
@pytest.mark.priority("P2")
def test_tc_sup_010_ask_and_idea_urls_target_discussion_categories():
    """SUP-010: Ask / Suggest open a new GitHub Discussion in the Q&A / Ideas category."""
    for url, slug in ((community.ask_url(), "q-a"), (community.idea_url(), "ideas")):
        parsed = urlparse(url)
        assert url.startswith(community.DISCUSSIONS_URL + "/new")
        assert parse_qs(parsed.query) == {"category": [slug]}


@pytest.mark.requirement("TC-SUP-020")
@pytest.mark.priority("P2")
def test_tc_sup_020_report_problem_prefills_diagnostics():
    """SUP-020: Report a problem prefills version, OS, Python and the current screen, and nothing identifying."""
    q = parse_qs(urlparse(community.report_problem_url("imaging.flats")).query)
    assert q["template"] == ["bug_report.yml"]
    assert q["version"] == [__version__]
    assert q["screen"] == ["imaging.flats"]
    assert set(q) == {"template", "version", "os", "python", "screen"}
    assert "screen" not in parse_qs(urlparse(community.report_problem_url()).query)


@pytest.mark.requirement("TC-SUP-030")
@pytest.mark.priority("P2")
def test_tc_sup_030_issue_form_fields_match_prefill_keys():
    """SUP-030: every prefilled query key is a field id in the bug-report form, and blank issues are disabled."""
    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    for key in ("version", "os", "python", "screen"):
        assert f"id: {key}\n" in form
    config = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
    assert "blank_issues_enabled: false" in config
    for slug in ("q-a", "ideas", "show-and-tell"):
        assert (ROOT / ".github" / "DISCUSSION_TEMPLATE" / f"{slug}.yml").is_file()
