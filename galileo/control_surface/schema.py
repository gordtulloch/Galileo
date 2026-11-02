# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Operation argument schemas (CSURF-010, CSURF-040).

An :class:`Arg` declares one argument — type, range, unit, default, allowed values — and
:func:`validate_args` checks a request against the whole tuple *before* any service is called,
reporting the first fault with the field path so a client can mark the right input.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TYPES = frozenset({"int", "float", "str", "bool", "enum"})
_MAX_STR = 4096
_MISSING: Any = object()


class InvalidArguments(ValueError):
    """An argument that fails its schema; ``path`` names it."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class Arg:
    name: str
    type: str = "str"
    required: bool = True
    default: Any = _MISSING
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    choices: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"unknown argument type {self.type!r}")
        if self.type == "enum" and not self.choices:
            raise ValueError("an enum argument needs choices")

    def describe(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "type": self.type, "required": self.required}
        for key in ("unit", "description"):
            if getattr(self, key):
                d[key] = getattr(self, key)
        if self.default is not _MISSING:
            d["default"] = self.default
        if self.minimum is not None:
            d["min"] = self.minimum
        if self.maximum is not None:
            d["max"] = self.maximum
        if self.choices:
            d["choices"] = list(self.choices)
        return d

    def check(self, value: Any) -> Any:
        t = self.type
        if t == "bool":
            if not isinstance(value, bool):
                raise InvalidArguments(self.name, "must be true or false")
            return value
        if t in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InvalidArguments(self.name, f"must be a number{' ' + self.unit if self.unit else ''}")
            if t == "int" and (isinstance(value, float) and not value.is_integer()):
                raise InvalidArguments(self.name, "must be a whole number")
            if isinstance(value, float) and not math.isfinite(value):
                raise InvalidArguments(self.name, "must be finite")
            value = int(value) if t == "int" else float(value)
            if self.minimum is not None and value < self.minimum:
                raise InvalidArguments(self.name, f"must be at least {self.minimum:g} {self.unit}".rstrip())
            if self.maximum is not None and value > self.maximum:
                raise InvalidArguments(self.name, f"must be at most {self.maximum:g} {self.unit}".rstrip())
            return value
        if not isinstance(value, str) or len(value) > _MAX_STR:
            raise InvalidArguments(self.name, "must be text")
        if t == "enum" and value not in self.choices:
            raise InvalidArguments(self.name, f"must be one of {', '.join(self.choices)}")
        return value


def validate_args(schema: Sequence[Arg], args: Mapping[str, Any] | None) -> dict[str, Any]:
    """The arguments with defaults filled in, or :class:`InvalidArguments`."""
    given = dict(args or {})
    known = {a.name for a in schema}
    for extra in sorted(set(given) - known):
        raise InvalidArguments(extra, "is not an argument of this operation")
    out: dict[str, Any] = {}
    for a in schema:
        if a.name in given:
            out[a.name] = a.check(given[a.name])
        elif a.default is not _MISSING:
            out[a.name] = a.default
        elif a.required:
            raise InvalidArguments(a.name, "is required")
    return out


__all__ = ["Arg", "InvalidArguments", "validate_args"]
