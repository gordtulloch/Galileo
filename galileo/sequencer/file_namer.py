"""File-naming macro expansion for captured frames (SEQ-020)."""

from __future__ import annotations

import re
from pathlib import Path


class FileNamer:
    """Expands a pattern string containing {key} macros into a file name.

    Supported macros: ``{target}``, ``{filter}``, ``{date}``,
    ``{frame_number}`` (accepts format spec, e.g. ``{frame_number:04d}``),
    ``{frame_type}``, ``{binning}``, ``{exposure}``, ``{instrument}``.
    """

    def __init__(self, pattern: str = "{target}_{filter}_{date}_{frame_number:04d}.fits") -> None:
        self.pattern = pattern

    def format(self, **kwargs) -> str:
        """Return the expanded file name for the given keyword values."""
        return self.pattern.format_map(_FormatMap(kwargs))

    def make_path(self, output_dir: "Path | str", **kwargs) -> Path:
        return Path(output_dir) / self.format(**kwargs)


class _FormatMap(dict):
    """dict subclass that returns a placeholder for missing keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
