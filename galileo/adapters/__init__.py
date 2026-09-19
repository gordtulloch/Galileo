# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""galileo.adapters package."""

from galileo.adapters.alpaca import AlpacaAdapter, AlpacaDiscovery, get_adapter_class as get_alpaca_adapter_class
from galileo.adapters.indi import IndiAdapter, IndiCameraSimulator, get_adapter_class as get_indi_adapter_class

__all__ = [
    "AlpacaAdapter",
    "AlpacaDiscovery",
    "IndiAdapter",
    "IndiCameraSimulator",
    "get_alpaca_adapter_class",
    "get_indi_adapter_class",
]
