"""Galileo copyright and licence notice.

Single source of truth for the copyright text shown to users (splash screen)
and available to anything else that needs it (About dialog, CLI ``--version``).
"""

from __future__ import annotations

from galileo import __author__, __license__

COPYRIGHT_YEAR = "2025-2026"
COPYRIGHT_HOLDER = __author__

#: One-line notice, e.g. for the splash screen.
COPYRIGHT_NOTICE = f"Copyright © {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}"

#: Licence line shown under the copyright notice.
LICENSE_NOTICE = f"Licensed under {__license__}"

#: Full multi-line notice (copyright plus licence).
FULL_NOTICE = f"{COPYRIGHT_NOTICE}\n{LICENSE_NOTICE}"
