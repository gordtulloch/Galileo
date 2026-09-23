# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""ACP observing script exporter (adapted from VSTarget planning/script_exporter.py)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.vstarget.planning.models import ObservationPlan


def export_acp_script(plans: "list[ObservationPlan]", output_path: "Path | str") -> None:
    """Write an iTelescope ACP .txt plan from *plans*, sorted by RA (VST-060)."""
    sorted_plans = sorted(plans, key=lambda p: p.ra_deg)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for plan in sorted_plans:
        for fc in plan.filter_configs:
            lines.append(f"#filter {fc.filter_name}")
            lines.append(f"#count {fc.count}")
            lines.append(f"#interval {fc.interval_s}")
            lines.append(f"#binning {fc.binning}")
        ra_h = plan.ra_deg / 15.0
        lines.append(f"#TARGET {plan.target_name}\t{ra_h:.10f}\t{plan.dec_deg:.10f}")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
