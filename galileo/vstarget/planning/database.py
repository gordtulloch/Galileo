"""SQLite persistence for observation plans (adapted from VSTarget planning/database.py)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.vstarget.planning.models import ObservationPlan

logger = logging.getLogger(__name__)


class PlanDatabase:
    """Persists observation plans to a JSON file (simple, no external ORM needed)."""

    def __init__(self, path: "Path | str") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, plans: "list[ObservationPlan]") -> None:
        data = [
            {
                "target_name": p.target_name,
                "ra_deg": p.ra_deg,
                "dec_deg": p.dec_deg,
                "filter_configs": [asdict(fc) for fc in p.filter_configs],
            }
            for p in plans
        ]
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> "list[ObservationPlan]":
        from galileo.vstarget.planning.models import ObservationPlan, FilterConfig
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text("utf-8"))
            plans = []
            for d in data:
                plan = ObservationPlan(
                    target_name=d["target_name"],
                    ra_deg=d.get("ra_deg", 0.0),
                    dec_deg=d.get("dec_deg", 0.0),
                )
                for fc in d.get("filter_configs", []):
                    plan.filter_configs.append(FilterConfig(**fc))
                plans.append(plan)
            return plans
        except Exception:
            logger.exception("Failed to load observation plans from %s", self._path)
            return []
