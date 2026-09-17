"""Variable star target planner service (VST-010 … VST-090)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galileo.vstarget.planning.database import PlanDatabase

logger = logging.getLogger(__name__)


class VariableStarPlanner:
    """Manages AAVSO target download, observation plans, and ACP script export (VST-010 … VST-090)."""

    def __init__(self) -> None:
        from galileo.vstarget.planning.aavso_client import AavsoTargetToolClient
        from galileo.vstarget.planning.simbad_client import SimbadClient
        self._aavso_client = AavsoTargetToolClient()
        self._simbad = SimbadClient()
        self._targets: list = []
        self._plans: list = []
        self._location = None
        self._scheduler = None
        self._db: "PlanDatabase | None" = None

    # --- Target management -----------------------------------------------

    async def sync_from_aavso(self, section: str = "") -> None:
        """Download targets from the AAVSO Target Tool API (VST-010)."""
        from galileo.vstarget.planning.models import AavsoTarget
        raw = await self._aavso_client.fetch_targets(section=section)
        targets = []
        for d in raw:
            targets.append(AavsoTarget(
                name=d.get("name", ""),
                ra_deg=float(d.get("ra", 0)),
                dec_deg=float(d.get("dec", 0)),
                section=d.get("section", section),
            ))
        if section:
            self._targets = [t for t in self._targets if t.section != section] + targets
        else:
            self._targets = targets

    def get_targets(self, section: str = "") -> list:
        if section:
            return [t for t in self._targets if t.section == section]
        return list(self._targets)

    def sorted_targets(self, key: str = "priority") -> list:
        return sorted(self._targets, key=lambda t: getattr(t, key, 0))

    def get_observable_tonight(self, date: str | None = None) -> list:
        """Filter to targets observable from the configured location (VST-030)."""
        if self._location is None:
            return list(self._targets)
        from galileo.planning.visibility import is_observable_tonight
        return [
            t for t in self._targets
            if is_observable_tonight(t.ra_deg, t.dec_deg, self._location, date)
        ]

    def import_from_file(self, path: "Path | str") -> None:
        """Load targets from a delimited text file (VST-040)."""
        import csv
        from galileo.vstarget.planning.models import AavsoTarget
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self._targets.append(AavsoTarget(
                    name=row.get("name", ""),
                    ra_deg=float(row.get("ra", 0)),
                    dec_deg=float(row.get("dec", 0)),
                ))

    def set_location(self, location) -> None:
        self._location = location

    # --- Observation plans -----------------------------------------------

    def save_plan(self, plan) -> None:
        self._plans.append(plan)
        if self._db:
            self._db.save(self._plans)

    def load_plans(self) -> list:
        if self._db:
            self._plans = self._db.load()
        return list(self._plans)

    def set_persistence(self, path: "Path | str") -> None:
        from galileo.vstarget.planning.database import PlanDatabase
        self._db = PlanDatabase(path)

    # --- Script export (VST-060) -----------------------------------------

    def export_acp_script(self, plans: list, output_path: "Path | str") -> None:
        from galileo.vstarget.planning.script_exporter import export_acp_script
        export_acp_script(plans, output_path)

    # --- Simbad fallback (VST-080) ----------------------------------------

    async def resolve_target(self, name: str) -> dict:
        return await self._simbad.lookup(name)

    # --- Scheduler integration (VST-090) ---------------------------------

    async def submit_to_scheduler(self, plan) -> None:
        if self._scheduler is None:
            return
        from galileo.scheduler import SchedulerJob
        job = SchedulerJob(
            name=plan.target_name,
            target_ra=getattr(plan, "ra_deg", 0.0),
            target_dec=getattr(plan, "dec_deg", 0.0),
        )
        self._scheduler.add_job(job)
