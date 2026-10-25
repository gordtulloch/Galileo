# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Shared behaviour of the Darks and Flats Assistant dialogs.

Both assistants are modeless and kept per Pier: a run goes on in the background while the
dialog is hidden (Hide button, title-bar X, ESC, or switching Piers), the Imaging page's
Darks…/Flats… button shows it is running, and pressing that button again brings the same
dialog back showing its live progress. Nothing here blocks the UI thread, so other Piers
stay usable while an assistant is open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import _QDialogBase

if TYPE_CHECKING:
    from ._state import AppWindowState


class _AssistantDialog(_QDialogBase):
    """A modeless ``QDialog`` that hides instead of closing while ``running`` is set.

    A run underway on a background thread is still updating this dialog's widgets through
    connected signals, so the dialog must outlive the run; hiding keeps it (and the run)
    alive, and a later close — once idle — deletes it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import Qt
        self.running = False
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def reject(self) -> None:
        if self.running:
            self.hide()
            return
        super().reject()


def reopen_assistant(app: AppWindowState, kind: str, pier_key: str | None) -> bool:
    """Bring the *kind* ("darks" / "flats") dialog of this Pier back to the front if one is
    open (hidden or not). Returns False when there is none, so the caller builds a new one."""
    dialog = app._assistant_dialogs.get((kind, pier_key))
    if dialog is None:
        return False
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return True


def register_assistant(app: AppWindowState, kind: str, pier_key: str | None, dialog: _AssistantDialog) -> None:
    """Track *dialog* as this Pier's *kind* assistant until it is closed, and keep the Imaging
    page button's "(running)" marker in step with it."""
    registry = app._assistant_dialogs
    registry[(kind, pier_key)] = dialog

    def forget(*_args) -> None:
        if registry.get((kind, pier_key)) is dialog:
            del registry[(kind, pier_key)]
        refresh_assistant_buttons(app)

    dialog.finished.connect(forget)
    dialog.destroyed.connect(forget)


def refresh_assistant_buttons(app: AppWindowState) -> None:
    """Mark the Imaging page's Darks…/Flats… button "(running)" when the selected Pier's
    assistant of that kind has a run going — it may be hidden, so this is the cue to reopen."""
    from galileo.current_object import pier_key
    key = pier_key(app._current_pier)
    for kind, button in app._assistant_buttons.items():
        dialog = app._assistant_dialogs.get((kind, key))
        base = button.text().removesuffix(" (running)")
        running = dialog is not None and dialog.running
        button.setText(f"{base} (running)" if running else base)


def hide_assistants_on_pier_change(app: AppWindowState) -> None:
    """Called when the selected Pier changes: hide every assistant that has a run going (it
    carries on in the background) and close the idle ones, since their fields (camera, filter
    wheel, flat panel) were read for the Pier that has just been left."""
    for dialog in list(app._assistant_dialogs.values()):
        if dialog.running:
            dialog.hide()
        else:
            dialog.reject()     # not close(): that does nothing for a dialog already hidden
