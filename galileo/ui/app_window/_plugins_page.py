# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Plugins settings page (PLUG-030, PLUG-090, PLUG-100, PLUG-110, PLUG-120)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._common import QWidget

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._state import AppWindowState


class AppWindowPluginsPageMixin:
    def _build_plugins_settings_page(self: AppWindowState) -> QWidget:  # type: ignore[return]
        """Options > Plugins: installed list, Install from file, and Marketplace tab."""
        try:
            from PySide6.QtCore import Qt, QThread, Signal, QObject
            from PySide6.QtWidgets import (
                QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
                QLabel, QMessageBox, QPushButton, QStackedWidget, QTabWidget,
                QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
                QProgressBar, QSizePolicy,
            )
        except ImportError:
            from ._common import QWidget as _W
            return _W()  # type: ignore[return-value]

        from galileo.plugins import PluginInstallError, PluginManager
        from galileo.plugins.marketplace import MarketplaceClient, MarketplaceEntry

        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        heading = QLabel("Plugins")
        heading.setObjectName("PageTitle")
        root.addWidget(heading)

        tabs = QTabWidget()
        root.addWidget(tabs)

        # ------------------------------------------------------------------
        # Helper: access PluginManager from AppWindow state
        # ------------------------------------------------------------------
        def _mgr() -> PluginManager | None:
            return getattr(self, "_plugin_manager", None)

        # ------------------------------------------------------------------
        # Tab 1 — Installed
        # ------------------------------------------------------------------
        installed_tab = QWidget()
        installed_layout = QVBoxLayout(installed_tab)
        installed_layout.setContentsMargins(12, 12, 12, 12)
        installed_layout.setSpacing(8)

        installed_table = QTableWidget(0, 5)
        installed_table.setHorizontalHeaderLabels(["Name", "Version", "Tier", "Author", "Enabled"])
        installed_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        installed_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        installed_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        installed_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        installed_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        installed_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        installed_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        installed_table.setAlternatingRowColors(True)
        installed_layout.addWidget(installed_table)

        restart_banner = QLabel(
            "⚠ Restart Galileo to apply changes to one or more plugins."
        )
        restart_banner.setObjectName("WarningBanner")
        restart_banner.setVisible(False)
        installed_layout.addWidget(restart_banner)

        install_btn = QPushButton("Install from file…")
        install_btn.setToolTip("Select a plugin ZIP file to install")
        installed_layout.addWidget(install_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        def _refresh_installed() -> None:
            mgr = _mgr()
            installed_table.setRowCount(0)
            if mgr is None:
                return
            for record in mgr.list_installed():
                row = installed_table.rowCount()
                installed_table.insertRow(row)
                installed_table.setItem(row, 0, QTableWidgetItem(record.manifest.name))
                installed_table.setItem(row, 1, QTableWidgetItem(record.manifest.version))
                tier_label = "First-party" if record.manifest.tier == "first_party" else "Third-party"
                installed_table.setItem(row, 2, QTableWidgetItem(tier_label))
                installed_table.setItem(row, 3, QTableWidgetItem(record.manifest.author))

                enabled_cell = QWidget()
                cell_layout = QHBoxLayout(enabled_cell)
                cell_layout.setContentsMargins(4, 0, 4, 0)
                toggle = QCheckBox()
                toggle.setChecked(record.enabled)
                remove_btn = QPushButton("Remove")
                remove_btn.setFixedWidth(70)

                plugin_name = record.manifest.name

                def _on_toggle(checked: bool, name: str = plugin_name) -> None:
                    m = _mgr()
                    if m:
                        m.set_enabled(name, checked)
                        restart_banner.setVisible(True)

                def _on_remove(name: str = plugin_name) -> None:
                    m = _mgr()
                    if m is None:
                        return
                    confirm = QMessageBox.question(
                        page,
                        "Remove plugin",
                        f"Remove '{name}'? This cannot be undone.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if confirm != QMessageBox.StandardButton.Yes:
                        return
                    needs_restart = not m.remove(name)
                    if needs_restart:
                        restart_banner.setVisible(True)
                    _refresh_installed()

                toggle.toggled.connect(_on_toggle)
                remove_btn.clicked.connect(_on_remove)
                cell_layout.addWidget(toggle)
                cell_layout.addWidget(remove_btn)
                installed_table.setCellWidget(row, 4, enabled_cell)

        def _on_install_from_file() -> None:
            path, _ = QFileDialog.getOpenFileName(
                page, "Select plugin ZIP", "", "Plugin packages (*.zip)"
            )
            if not path:
                return
            mgr = _mgr()
            if mgr is None:
                QMessageBox.warning(page, "Plugin Manager", "Plugin manager not available.")
                return
            try:
                mgr.install(path)
                _refresh_installed()
                tabs.setCurrentIndex(0)
            except PluginInstallError as exc:
                QMessageBox.critical(page, "Install failed", str(exc))

        install_btn.clicked.connect(_on_install_from_file)
        _refresh_installed()
        tabs.addTab(installed_tab, "Installed")

        # ------------------------------------------------------------------
        # Tab 2 — Marketplace
        # ------------------------------------------------------------------
        market_tab = QWidget()
        market_layout = QVBoxLayout(market_tab)
        market_layout.setContentsMargins(12, 12, 12, 12)
        market_layout.setSpacing(8)

        market_status = QLabel("Loading plugin list…")
        market_status.setObjectName("StatusHint")
        market_layout.addWidget(market_status)

        market_table = QTableWidget(0, 5)
        market_table.setHorizontalHeaderLabels(["Name", "Version", "Tier", "Author", ""])
        market_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        market_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        market_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        market_table.setAlternatingRowColors(True)
        market_table.setVisible(False)
        market_layout.addWidget(market_table)

        market_progress = QProgressBar()
        market_progress.setRange(0, 0)  # indeterminate
        market_progress.setVisible(False)
        market_layout.addWidget(market_progress)

        refresh_btn = QPushButton("Refresh")
        market_layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        _client = MarketplaceClient()

        class _FetchThread(QThread):
            done = Signal(list, str)

            def __init__(self, client: MarketplaceClient, force: bool = False) -> None:
                super().__init__()
                self._client = client
                self._force = force

            def run(self) -> None:
                if self._force:
                    entries, err = self._client.refresh()
                else:
                    entries, err = self._client.fetch()
                self.done.emit(entries, err)

        _fetch_thread: _FetchThread | None = None

        def _populate_market(entries: list, error: str) -> None:
            market_progress.setVisible(False)
            market_table.setRowCount(0)
            if error:
                market_status.setText(
                    f"Could not reach galileo-imaging.com — {error}\nCheck your connection and Refresh."
                )
                market_status.setVisible(True)
                market_table.setVisible(False)
                return

            market_status.setVisible(False)
            market_table.setVisible(True)
            mgr = _mgr()
            installed_names: set[str] = set()
            if mgr:
                installed_names = {r.manifest.name for r in mgr.list_installed()}

            for entry in entries:
                row = market_table.rowCount()
                market_table.insertRow(row)
                market_table.setItem(row, 0, QTableWidgetItem(entry.name))
                market_table.setItem(row, 1, QTableWidgetItem(entry.version))
                tier_label = "First-party" if entry.tier == "first_party" else "Third-party"
                market_table.setItem(row, 2, QTableWidgetItem(tier_label))
                market_table.setItem(row, 3, QTableWidgetItem(entry.author))

                if entry.name in installed_names:
                    lbl = QLabel("Installed")
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    market_table.setCellWidget(row, 4, lbl)
                else:
                    dl_btn = QPushButton("Install")
                    dl_btn.setFixedWidth(70)

                    def _on_market_install(checked: bool = False, e: MarketplaceEntry = entry) -> None:
                        _do_market_install(e)

                    dl_btn.clicked.connect(_on_market_install)
                    market_table.setCellWidget(row, 4, dl_btn)

        class _DownloadInstallThread(QThread):
            progress = Signal(int, int)
            done = Signal(bool, str)

            def __init__(self, client: MarketplaceClient, entry: MarketplaceEntry, dest: str) -> None:
                super().__init__()
                self._client = client
                self._entry = entry
                self._dest = dest

            def run(self) -> None:
                import threading
                ok = self._client.download(
                    self._entry, self._dest,
                    progress_callback=lambda r, t: self.progress.emit(r, t),
                )
                self.done.emit(ok, self._dest)

        _dl_thread: _DownloadInstallThread | None = None

        def _do_market_install(entry: MarketplaceEntry) -> None:
            nonlocal _dl_thread
            import tempfile, os
            tmp_path = os.path.join(tempfile.gettempdir(), f"{entry.name}-{entry.version}.zip")
            market_progress.setRange(0, 0)
            market_progress.setVisible(True)
            market_status.setText(f"Downloading {entry.name}…")
            market_status.setVisible(True)

            _dl_thread = _DownloadInstallThread(_client, entry, tmp_path)

            def _on_dl_done(ok: bool, path: str) -> None:
                market_progress.setVisible(False)
                if not ok:
                    market_status.setText(f"Download of '{entry.name}' failed or was cancelled.")
                    return
                mgr = _mgr()
                if mgr is None:
                    market_status.setText("Plugin manager not available.")
                    return
                try:
                    mgr.install(path)
                    market_status.setText(f"'{entry.name}' installed successfully.")
                    _refresh_installed()
                    _fetch_thread_start(force=True)
                except PluginInstallError as exc:
                    market_status.setText(f"Install failed: {exc}")
                finally:
                    import os as _os
                    try:
                        _os.unlink(path)
                    except OSError:
                        pass

            _dl_thread.done.connect(_on_dl_done)
            _dl_thread.start()

        def _fetch_thread_start(force: bool = False) -> None:
            nonlocal _fetch_thread
            market_table.setVisible(False)
            market_progress.setRange(0, 0)
            market_progress.setVisible(True)
            market_status.setText("Loading plugin list…")
            market_status.setVisible(True)
            _fetch_thread = _FetchThread(_client, force=force)
            _fetch_thread.done.connect(_populate_market)
            _fetch_thread.start()

        refresh_btn.clicked.connect(lambda: _fetch_thread_start(force=True))
        tabs.addTab(market_tab, "Marketplace")

        # Kick off the marketplace fetch when the tab is first shown.
        def _on_tab_changed(idx: int) -> None:
            if idx == 1 and market_table.rowCount() == 0 and not market_progress.isVisible():
                _fetch_thread_start()

        tabs.currentChanged.connect(_on_tab_changed)

        return page
