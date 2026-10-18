# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""INDI adapter(s) for filter wheel devices."""

from __future__ import annotations

from galileo.adapters import indi_client as ic
from galileo.adapters.indi._base import IndiAdapter
from galileo.core.devices import DeviceCategory


class IndiFWAdapter(IndiAdapter):
    """Filter wheel via ``INDI::FilterWheel`` (``FILTER_SLOT`` is 1-based on
    the wire; this adapter's ``position`` is 0-based like the Alpaca one)."""

    def __init__(self, host: str = "localhost", port: int = 7624, **kwargs) -> None:
        super().__init__(DeviceCategory.FILTER_WHEEL, host, port, **kwargs)
        self.filter_names: list[str] = []
        self.position = 0
        self.is_moving = False

    def _on_connected(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        names = self._client.find_property(self.device_name, lambda p: p.name == "FILTER_NAME") if self._client else None
        if names is not None:
            self.filter_names = [str(el.value) for el in names.elements.values()]
        slot = self._num("FILTER_SLOT", "FILTER_SLOT_VALUE")
        if slot is not None:
            self.position = int(slot) - 1

    async def move_to(self, index: int) -> None:
        self._log_interaction("move_to", index=index)
        seq0 = self._c().blob_seq(self.device_name, "FILTER_SLOT")
        self._set_num("FILTER_SLOT", {"FILTER_SLOT_VALUE": index + 1})
        self.position = index
        await self._wait_not_busy("FILTER_SLOT", 60.0, "filter change", after_seq=seq0)

    async def get_status(self) -> dict:
        self._refresh()
        self.is_moving = self._state("FILTER_SLOT") == ic.BUSY
        return {**self._driver_info(), "filter_names": list(self.filter_names), "position": self.position}
