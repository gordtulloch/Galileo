# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Data models for variable star target planning (adapted from VSTarget planning/models.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AavsoTarget:
    """One variable-star target from the AAVSO Target Tool."""
    name: str
    ra_deg: float
    dec_deg: float
    section: str = ""
    priority: int = 3
    solar_conjunction: bool = False
    magnitude_range: str = ""
    type_code: str = ""
    notes: str = ""


@dataclass
class FilterConfig:
    """Per-filter exposure parameters for an observation plan."""
    filter_name: str
    exposure_s: float
    count: int
    interval_s: float = 120.0
    binning: int = 1


@dataclass
class ObservationPlan:
    """Observation plan for one variable star target."""
    target_name: str
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    filter_configs: list[FilterConfig] = field(default_factory=list)

    def add_filter_config(
        self,
        filter_name: str,
        exposure_s: float,
        count: int,
        interval_s: float = 120.0,
        binning: int = 1,
    ) -> None:
        self.filter_configs.append(FilterConfig(
            filter_name=filter_name,
            exposure_s=exposure_s,
            count=count,
            interval_s=interval_s,
            binning=binning,
        ))

    def __str__(self) -> str:
        return self.target_name


@dataclass
class TransformationCoefficients:
    """Photometric transformation coefficients for one telescope/filter set (VST-AN-060)."""
    Tbv: float = 0.0
    Tvr: float = 0.0
    Tr: float = 0.0
    Tv: float = 0.0
    Tb: float = 0.0
