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


# Palette tokens sampled from N.I.N.A.'s default dark theme, so Galileo's
# shell reads as visually consistent with the imaging-software family it
# follows (UI-010). Accent is user-customizable (UI-030); everything else is
# fixed per theme.
_PALETTE = {
    Theme.DARK: {
        "bg": "#263238",
        "surface": "#2a2c31",
        "surface_alt": "#1c2126",
        "border": "#37474f",
        "text": "#d7dadd",
        "text_dim": "#8a949c",
        "text_bright": "#ffffff",
    },
    Theme.LIGHT: {
        "bg": "#eef1f3",
        "surface": "#e2e6e9",
        "surface_alt": "#d3d8db",
        "border": "#b7bec3",
        "text": "#20262a",
        "text_dim": "#5b656b",
        "text_bright": "#000000",
    },
}


class ThemeManager:
    """Manages application-wide theme and accent colour (UI-010, UI-030)."""

    def __init__(self) -> None:
        self._theme = Theme.DARK
        self._accent_color = "#12877b"  # N.I.N.A.-style teal

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

    def palette(self) -> dict:
        """Return the colour tokens for the current theme (SYSTEM resolves to DARK)."""
        return _PALETTE[self._theme if self._theme in _PALETTE else Theme.DARK]

    def stylesheet(self) -> str:
        """Build the Qt stylesheet for the current theme + accent colour."""
        p = self.palette()
        accent = self._accent_color
        return f"""
        QWidget {{
            background: {p['bg']};
            color: {p['text']};
            font-size: 9pt;
            selection-background-color: {accent};
        }}
        QMainWindow, QStackedWidget, QWidget#ContentArea, QWidget#EquipmentPage {{
            background: {p['bg']};
        }}
        QWidget#Sidebar, QWidget#SecondarySidebar {{
            background: {p['surface']};
        }}
        QWidget#Sidebar {{ border-right: 1px solid {p['border']}; }}
        QWidget#SecondarySidebar {{ border-right: 1px solid {p['border']}; }}
        QWidget#CriteriaPanel {{ border-right: 1px solid {p['border']}; }}
        QWidget#TopBar {{
            background: {p['surface']};
            border-bottom: 1px solid {p['border']};
        }}
        QPlainTextEdit#LogPane {{
            background: {p['surface_alt']};
            color: {p['text_dim']};
            border: 1px solid {p['border']};
            border-radius: 3px;
        }}
        QLabel#CriteriaHeading {{
            font-size: 10.5pt;
            font-weight: 600;
            color: {p['text_bright']};
        }}
        QToolButton#NavButton {{
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            color: {p['text_dim']};
            padding: 10px 2px 8px 2px;
        }}
        QToolButton#NavButton:hover {{
            color: {p['text_bright']};
            background: rgba(255, 255, 255, 15);
        }}
        QToolButton#NavButton:checked {{
            color: {accent};
            border-left: 3px solid {accent};
            background: rgba(255, 255, 255, 8);
        }}
        QToolButton#SecondaryNavButton {{
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            color: {p['text_dim']};
            padding: 8px 2px 6px 2px;
        }}
        QToolButton#SecondaryNavButton:hover {{
            color: {p['text_bright']};
            background: rgba(255, 255, 255, 12);
        }}
        QToolButton#SecondaryNavButton:checked {{
            color: {accent};
            border-left: 3px solid {accent};
            background: rgba(255, 255, 255, 6);
        }}
        QLabel#PageTitle {{
            font-size: 15.75pt;
            font-weight: 600;
            color: {p['text_bright']};
        }}
        QLabel#PageSubtitle {{
            color: {p['text_dim']};
        }}
        QStatusBar#StatusBar {{
            background: {p['surface']};
            color: {p['text_dim']};
            border-top: 1px solid {p['border']};
        }}
        QPushButton {{
            background: {p['surface_alt']};
            border: 1px solid {p['border']};
            border-radius: 3px;
            padding: 5px 12px;
        }}
        QPushButton:hover {{ border-color: {accent}; }}
        QPushButton#AccentButton {{
            background: {accent};
            color: {p['text_bright']};
            border: none;
            font-weight: 600;
        }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {p['surface_alt']};
            border: 1px solid {p['border']};
            border-radius: 3px;
            padding: 3px 6px;
        }}
        QFrame#DeviceSlotPanel {{
            border: 1px solid {p['border']};
            border-radius: 4px;
            background: {p['surface']};
        }}
        QTabWidget::pane {{ border: 1px solid {p['border']}; }}
        QTabBar::tab:selected {{ color: {accent}; }}
        QScrollBar:vertical {{
            background: {p['bg']};
            width: 10px;
        }}
        QScrollBar::handle:vertical {{
            background: {p['border']};
            border-radius: 4px;
            min-height: 24px;
        }}
        QToolTip {{
            background: {p['surface']};
            color: {p['text']};
            border: 1px solid {p['border']};
        }}
        """

    def _apply(self) -> None:
        """Apply theme to the Qt application stylesheet (no-op when Qt unavailable)."""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            app.setStyleSheet(self.stylesheet())
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
