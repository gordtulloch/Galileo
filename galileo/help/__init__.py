# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""In-app help content (HELP-010 .. HELP-060): loading, parsing and lookup.

Help is plain Markdown, one file per screen, in ``galileo/help/content/``
(plugins add their own directories with :func:`register_dir`). This module has
no Qt dependency; ``galileo.ui.help`` renders it.

File format::

    <!-- order: 40 -->              optional sort position in the topic list
    # Focuser                       the screen's title
    Overview paragraph(s).          shown at the top; also the "overview" topic

    ## Position (target)            one ``##`` section per control
    One-sentence summary.           first paragraph = the control's tooltip
    Further detail, any Markdown.

A section's *key* is the slug of its heading (``position-target``). The UI
resolves a control to a key from its form-row label, its button text or its
``objectName``, so writing help for a control is just adding a heading whose
text matches the control's label -- no code change. Screen ids are dotted
(``equipment.focuser``); a lookup that misses falls back to the parent
(``equipment``) and finally to ``common`` (controls shared by many screens,
such as Driver / Server / Port).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path

COMMON = "common"
OVERVIEW = "overview"

_extra_dirs: list[Path] = []


def register_dir(path: str | Path) -> None:
    """Add a directory of ``<screen_id>.md`` files (e.g. a plugin's help)."""
    p = Path(path)
    if p not in _extra_dirs:
        _extra_dirs.append(p)
        _load.cache_clear()
        screen_ids.cache_clear()


def slug(text: str) -> str:
    """Normalise a label to a section key: ``"Position (target):"`` -> ``"position-target"``."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    body: str  # Markdown, heading excluded

    @property
    def aliases(self) -> tuple[str, ...]:
        """Extra keys from a ``<!-- keys: a, b -->`` comment on the section's first line.

        For a control whose group-qualified key (``telescope-coordinates-jnow-ra``)
        would make an ugly heading: keep the heading human and list the key here.
        """
        m = re.match(r"\s*<!--\s*keys:\s*([^>]*?)\s*-->", self.body)
        return tuple(slug(a) for a in m.group(1).split(",") if slug(a)) if m else ()

    @property
    def text(self) -> str:
        """The body without the ``keys`` comment."""
        return re.sub(r"^\s*<!--\s*keys:[^>]*-->\s*", "", self.body)

    @property
    def summary(self) -> str:
        """The first paragraph as plain text -- used as the control's tooltip."""
        para = self.text.strip().split("\n\n", 1)[0]
        para = re.sub(r"`([^`]*)`", r"\1", para)
        para = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", para)
        para = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", para)
        return " ".join(para.split())


@dataclass(frozen=True)
class HelpDoc:
    screen_id: str
    title: str
    order: int
    markdown: str
    sections: dict[str, Section] = field(default_factory=dict)

    def get(self, key: str) -> Section | None:
        return self.sections.get(key)

    def topics(self) -> list[Section]:
        """Each section once, in file order (``sections`` also holds alias keys)."""
        return [s for k, s in self.sections.items() if k == s.key]


def _candidate_dirs() -> list[Path]:
    dirs = [Path(str(resources.files("galileo.help") / "content"))]
    return dirs + _extra_dirs


def _parse(screen_id: str, text: str) -> HelpDoc:
    order = 100
    m = re.match(r"\s*<!--\s*order:\s*(\d+)\s*-->\s*", text)
    if m:
        order = int(m.group(1))
        text = text[m.end():]
    lines = text.splitlines()
    title = screen_id
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
    sections: dict[str, Section] = {}
    current: tuple[str, list[str]] | None = None
    intro: list[str] = []

    def close() -> None:
        if current is not None:
            heading, body = current
            section = Section(slug(heading), heading, "\n".join(body).strip())
            sections.setdefault(section.key, section)
            for alias in section.aliases:
                sections.setdefault(alias, section)

    for line in lines[1:] if lines and lines[0].startswith("# ") else lines:
        if line.startswith("## "):
            close()
            current = (line[3:].strip(), [])
        elif current is None:
            intro.append(line)
        else:
            current[1].append(line)
    close()
    intro_text = "\n".join(intro).strip()
    if intro_text:
        sections.setdefault(OVERVIEW, Section(OVERVIEW, title, intro_text))
    clean = re.sub(r"[ \t]*<!--\s*keys:[^>]*-->[ \t]*\n?", "", text)  # alias comments are for lookup, not display
    return HelpDoc(screen_id, title, order, clean, sections)


@cache
def _load(screen_id: str) -> HelpDoc | None:
    for d in _candidate_dirs():
        f = d / f"{screen_id}.md"
        if f.is_file():
            return _parse(screen_id, f.read_text(encoding="utf-8"))
    return None


def load(screen_id: str) -> HelpDoc | None:
    """The help document for *screen_id*, or None if that screen has none."""
    return _load(screen_id)


@cache
def screen_ids() -> tuple[str, ...]:
    """Every screen id with help, sorted by each document's ``order`` then title."""
    ids = {f.stem for d in _candidate_dirs() if d.is_dir() for f in d.glob("*.md")}
    docs = [d for d in (load(i) for i in ids) if d is not None]
    return tuple(d.screen_id for d in sorted(docs, key=lambda d: (d.order, d.title.lower())))


def _chain(screen_id: str) -> list[str]:
    """``equipment.focuser`` -> [``equipment.focuser``, ``equipment``, ``common``]."""
    parts = screen_id.split(".") if screen_id else []
    chain = [".".join(parts[:i]) for i in range(len(parts), 0, -1)]
    return [*chain, COMMON]


def resolve(screen_id: str, key: str) -> tuple[HelpDoc, Section] | None:
    """Find the section for *key* on *screen_id*, falling back to parent screens then ``common``."""
    for sid in _chain(screen_id):
        doc = load(sid)
        if doc is not None and (sec := doc.get(key)) is not None:
            return doc, sec
    return None


def search(query: str) -> list[tuple[HelpDoc, Section]]:
    """Sections (any screen) whose title or body contains every word of *query*."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    hits = []
    for sid in screen_ids():
        doc = load(sid)
        if doc is None:
            continue
        for sec in doc.topics():
            hay = f"{sec.title}\n{sec.body}".lower()
            if all(w in hay for w in words):
                hits.append((doc, sec))
    return hits
