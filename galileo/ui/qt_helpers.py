"""Small helpers for Qt calls whose stubs say ``X | None`` but which cannot be ``None`` where we call them.

PySide6's stubs mark many accessors Optional (``QTableWidget.item``, ``QComboBox.lineEdit``, ``QLayout.itemAt``,
``QApplication.instance``...). Where the surrounding code guarantees a value, :func:`need` narrows the type and fails
with a clear error instead of an ``AttributeError: 'NoneType'`` deep in a slot.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLayout, QWidget

T = TypeVar("T")


def need(value: T | None, what: str = "value") -> T:
    """Return *value*, raising ``RuntimeError`` if it is ``None``."""
    if value is None:
        raise RuntimeError(f"Unexpected missing Qt {what}")
    return value


def layout_widget(layout: QLayout, index: int) -> QWidget | None:
    """The widget at *index* of *layout*, or ``None`` for a spacer, nested layout or empty slot."""
    item = layout.itemAt(index)
    return item.widget() if item is not None else None


def take_widget(layout: QLayout, index: int = 0) -> QWidget | None:
    """Remove the item at *index* from *layout* and return its widget (``None`` for non-widget items)."""
    item = layout.takeAt(index)
    return item.widget() if item is not None else None
