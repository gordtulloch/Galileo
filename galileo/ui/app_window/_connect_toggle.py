# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect/Disconnect toggle for an Equipment page's per-device button.

The top bar's Connect button already flips to Disconnect once the Pier's devices are connected; the
per-device buttons do the same through this helper, whether the connection was made from the button,
the top bar, a Pier switch or start-up. :func:`galileo.ui.app_window._observatory_pier` re-syncs them
all through each page's ``sync_connect`` entry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def install_connect_toggle(
    btn: Any, is_connected: Callable[[], bool], connect: Callable[[], None], disconnect: Callable[[], None],
) -> Callable[[], None]:
    """Make *btn* connect when idle and disconnect when connected; return the function that syncs its label."""
    def sync() -> None:
        btn.setText("Disconnect" if is_connected() else "Connect")

    def clicked() -> None:
        (disconnect if is_connected() else connect)()
        sync()

    btn.clicked.connect(clicked)
    sync()
    return sync
