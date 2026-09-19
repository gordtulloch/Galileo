# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Library screens — the Library section's Images, Sessions, Mappings, Dedup and Cloud pages.

Ported from AstroFiler's Qt widgets. Each screen is a plain ``QWidget`` built by
``galileo.ui.library.pages`` and hosted under the Library section of the main window;
the library settings page (Options > Library) is ``config_widget.ConfigWidget``.
"""
