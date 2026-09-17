"""UI theming — light/dark themes and panel layout persistence (UI-010 … UI-030)."""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class Theme(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ThemeManager:
    """Manages application-wide theme and accent colour (UI-010, UI-030)."""

    def __init__(self) -> None:
        self._theme = Theme.DARK
        self._accent_color = "#3399FF"

    def available_themes(self) -> list[Theme]:
        return [Theme.LIGHT, Theme.DARK]

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._apply()

    @property
    def current_theme(self) -> Theme:
        return self._theme

    def set_accent_color(self, hex_color: str) -> None:
        self._accent_color = hex_color
        self._apply()

    @property
    def accent_color(self) -> str:
        return self._accent_color

    def _apply(self) -> None:
        """Apply theme to the Qt application stylesheet (no-op when Qt unavailable)."""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            # Stylesheet application would go here
        except ImportError:
            pass


class LayoutManager:
    """Persists imaging-tab panel layouts across restarts (UI-020)."""

    def __init__(self, config_path: "Path | str | None" = None) -> None:
        if config_path is None:
            from galileo.platform import get_config_dir
            config_path = get_config_dir() / "panel_layouts.json"
        self._path = Path(config_path)
        self._data: dict = {}
        self._load()

    def save_layout(self, panel_id: str, layout: dict) -> None:
        self._data[panel_id] = layout
        self._flush()

    def load_layout(self, panel_id: str) -> dict:
        return dict(self._data.get(panel_id, {}))

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text("utf-8"))
            except Exception:
                pass
