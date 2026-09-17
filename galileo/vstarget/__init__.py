"""galileo.vstarget package — variable star planning and analysis (VST, VST-AN).

Delivered as first-party pre-loaded plugins (PLUG-060).
"""

from __future__ import annotations

from galileo.plugins import PluginBase
from galileo.vstarget.analysis import VariableStarAnalysis
from galileo.vstarget.analysis.exposure import ExposureTimeCalculator
from galileo.vstarget.analysis.finder_chart import FinderChartRenderer
from galileo.vstarget.analysis.photometry import PhotometryResult, StandardFieldObservation
from galileo.vstarget.planning import VariableStarPlanner
from galileo.vstarget.planning.models import (
    AavsoTarget,
    ObservationPlan,
    TransformationCoefficients,
)


class VSTPlugin(PluginBase):
    """Variable star planning plugin (pre-loaded, PLUG-060)."""
    name = "VSTPlugin"
    version = "1.0.0"
    api_version = "1"
    panel_level = "primary"
    panel_label = "Variable Stars"

    def activate(self, ctx) -> None:
        pass

    def deactivate(self) -> None:
        pass


class VSTAnalysisPlugin(PluginBase):
    """Variable star analysis plugin (pre-loaded, PLUG-060)."""
    name = "VSTAnalysisPlugin"
    version = "1.0.0"
    api_version = "1"
    panel_level = "secondary"
    panel_label = "VS Analysis"

    def activate(self, ctx) -> None:
        pass

    def deactivate(self) -> None:
        pass


__all__ = [
    "AavsoTarget",
    "ExposureTimeCalculator",
    "FinderChartRenderer",
    "ObservationPlan",
    "PhotometryResult",
    "StandardFieldObservation",
    "TransformationCoefficients",
    "VSTAnalysisPlugin",
    "VSTPlugin",
    "VariableStarAnalysis",
    "VariableStarPlanner",
]
