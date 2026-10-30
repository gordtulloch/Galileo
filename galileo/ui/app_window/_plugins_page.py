# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Plugins settings page (PLUG-030, PLUG-090, PLUG-100, PLUG-110, PLUG-120)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._common import QWidget
import contextlib

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._state import AppWindowState


class AppWindowPluginsPageMixin:
    def _build_plugins_settings_page(self: AppWindowState) -> QWidget:  # type: ignore[return]
        """Options > Plugins: installed list, Install from file, and Marketplace tab."""
        try:
            from PySide6.QtCore import Qt, QThread, Signal
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import (
                QCheckBox, QFileDialog, QFrame, QHBoxLayout,
                QLabel, QMessageBox, QPushButton, QScrollArea,
                QTabWidget, QVBoxLayout, QWidget, QProgressBar, )
        except ImportError:
            from ._common import QWidget as _W
            return _W()  # type: ignore[return-value]

        from galileo.plugins import PluginInstallError, PluginManager, is_newer_version
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

        def _make_icon_pixmap(icon_data: bytes) -> QPixmap | None:
            """Render icon bytes (PNG or SVG) to a 48×48 QPixmap."""
            try:
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtCore import QByteArray
                from PySide6.QtGui import QPainter
                renderer = QSvgRenderer(QByteArray(icon_data))
                if renderer.isValid():
                    px = QPixmap(48, 48)
                    px.fill(Qt.GlobalColor.transparent)
                    p = QPainter(px)
                    renderer.render(p)
                    p.end()
                    return px
            except ImportError:
                pass
            px = QPixmap()
            if px.loadFromData(icon_data):
                return px.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return None

        _client = MarketplaceClient()
        # Latest marketplace entry per plugin name; drives the "Update available" tags (PLUG-190).
        _latest: dict[str, MarketplaceEntry] = {}

        def _update_entry(name: str, installed_version: str) -> MarketplaceEntry | None:
            """The marketplace entry for *name* when it is newer than *installed_version*."""
            entry = _latest.get(name)
            if entry is not None and is_newer_version(entry.version, installed_version):
                return entry
            return None

        def _update_tag() -> QLabel:
            tag = QLabel("Update available")
            tag.setStyleSheet(
                "border: none; border-radius: 4px; padding: 1px 6px; font-size: 11px;"
                " font-weight: bold; color: #ffffff; background: #d9822b;"
            )
            return tag

        # ------------------------------------------------------------------
        # Tab 1 — Installed
        # ------------------------------------------------------------------
        installed_tab = QWidget()
        installed_layout = QVBoxLayout(installed_tab)
        installed_layout.setContentsMargins(12, 12, 12, 12)
        installed_layout.setSpacing(8)

        installed_scroll = QScrollArea()
        installed_scroll.setWidgetResizable(True)
        installed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        installed_layout.addWidget(installed_scroll)

        restart_banner = QLabel(
            "⚠ Restart Galileo to apply changes to one or more plugins."
        )
        restart_banner.setObjectName("WarningBanner")
        restart_banner.setVisible(False)
        installed_layout.addWidget(restart_banner)

        installed_status = QLabel("")
        installed_status.setObjectName("StatusHint")
        installed_status.setWordWrap(True)
        installed_status.setVisible(False)
        installed_layout.addWidget(installed_status)

        install_btn = QPushButton("Install from file…")
        install_btn.setToolTip("Select a plugin ZIP file to install")
        installed_layout.addWidget(install_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        def _refresh_installed() -> None:
            mgr = _mgr()

            container = QWidget()
            cl = QVBoxLayout(container)
            cl.setSpacing(8)
            cl.setContentsMargins(2, 2, 2, 2)
            cl.setAlignment(Qt.AlignmentFlag.AlignTop)

            if mgr is not None:
                for record in mgr.list_installed():
                    card = QFrame()
                    card.setObjectName("MarketplaceCard")
                    card.setStyleSheet(
                        "QFrame#MarketplaceCard {"
                        "  border: 1px solid palette(mid);"
                        "  border-radius: 8px;"
                        "  padding: 6px 8px;"
                        "}"
                    )
                    card_outer = QHBoxLayout(card)
                    card_outer.setSpacing(10)

                    icon_lbl = QLabel("★")
                    icon_lbl.setFixedSize(48, 48)
                    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    icon_lbl.setStyleSheet("font-size: 24px; border: none;")
                    card_outer.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

                    right_col = QVBoxLayout()
                    right_col.setSpacing(3)

                    header_row = QHBoxLayout()
                    name_lbl = QLabel(f"<b>{record.manifest.name}</b>")
                    name_lbl.setStyleSheet("border: none; font-size: 13px;")
                    header_row.addWidget(name_lbl)
                    header_row.addStretch()

                    plugin_name = record.manifest.name

                    toggle = QCheckBox("Enabled")
                    toggle.setChecked(record.enabled)
                    toggle.setStyleSheet("border: none;")
                    remove_btn = QPushButton("Remove")
                    remove_btn.setFixedWidth(70)

                    def _on_toggle(checked: bool, name: str = plugin_name) -> None:
                        m = _mgr()
                        if m:
                            m.set_enabled(name, checked)
                            restart_banner.setVisible(True)

                    def _on_remove(checked: bool = False, name: str = plugin_name) -> None:
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
                    newer = _update_entry(plugin_name, record.manifest.version)
                    if newer is not None:
                        header_row.addWidget(_update_tag())
                        update_btn = QPushButton("Update")
                        update_btn.setFixedWidth(70)
                        update_btn.setToolTip(f"Update to v{newer.version} without restarting")
                        update_btn.clicked.connect(
                            lambda _checked=False, e=newer: _do_market_install(e, updating=True)
                        )
                        header_row.addWidget(update_btn)
                    header_row.addWidget(toggle)
                    header_row.addWidget(remove_btn)
                    right_col.addLayout(header_row)

                    tier_label = (
                        "First-party" if record.manifest.tier == "first_party"
                        else "Third-party"
                    )
                    meta_parts = [
                        p for p in [
                            f"v{record.manifest.version}" if record.manifest.version else "",
                            tier_label,
                            record.manifest.author,
                        ] if p
                    ]
                    meta_lbl = QLabel("  ·  ".join(meta_parts))
                    meta_lbl.setStyleSheet("border: none; color: palette(mid);")
                    right_col.addWidget(meta_lbl)

                    card_outer.addLayout(right_col)
                    cl.addWidget(card)

            installed_scroll.setWidget(container)

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
                installed_status.setText("Plugin installed — it is available now, no restart needed.")
                installed_status.setVisible(True)
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

        market_scroll = QScrollArea()
        market_scroll.setWidgetResizable(True)
        market_scroll.setFrameShape(QFrame.Shape.NoFrame)
        market_scroll.setVisible(False)
        market_layout.addWidget(market_scroll)

        market_progress = QProgressBar()
        market_progress.setRange(0, 0)  # indeterminate
        market_progress.setVisible(False)
        market_layout.addWidget(market_progress)

        refresh_btn = QPushButton("Refresh")
        market_layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignLeft)

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

        def _remember_latest(entries: list) -> None:
            _latest.clear()
            _latest.update({e.name: e for e in entries})
            _refresh_installed()

        def _populate_market(entries: list, error: str) -> None:
            market_progress.setVisible(False)
            if not error:
                _remember_latest(entries)
            if error:
                market_status.setText(
                    f"Could not reach galileo-imaging.com — {error}\nCheck your connection and Refresh."
                )
                market_status.setVisible(True)
                market_scroll.setVisible(False)
                return

            market_status.setVisible(False)
            market_scroll.setVisible(True)

            mgr = _mgr()
            installed_versions: dict[str, str] = {}
            if mgr:
                installed_versions = {r.manifest.name: r.manifest.version for r in mgr.list_installed()}

            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setSpacing(8)
            container_layout.setContentsMargins(2, 2, 2, 2)
            container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            for entry in entries:
                card = QFrame()
                card.setObjectName("MarketplaceCard")
                card.setStyleSheet(
                    "QFrame#MarketplaceCard {"
                    "  border: 1px solid palette(mid);"
                    "  border-radius: 8px;"
                    "  padding: 6px 8px;"
                    "}"
                )
                card_outer = QHBoxLayout(card)
                card_outer.setSpacing(10)

                # Icon
                icon_lbl = QLabel()
                icon_lbl.setFixedSize(48, 48)
                icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_lbl.setStyleSheet("border: none;")
                px = _make_icon_pixmap(entry.icon_data) if entry.icon_data else None
                if px:
                    icon_lbl.setPixmap(px)
                else:
                    icon_lbl.setText("★")
                    icon_lbl.setStyleSheet("font-size: 24px; border: none;")
                card_outer.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

                # Right column: name/meta/description + install button
                right_col = QVBoxLayout()
                right_col.setSpacing(3)

                header_row = QHBoxLayout()
                name_lbl = QLabel(f"<b>{entry.name}</b>")
                name_lbl.setStyleSheet("border: none; font-size: 13px;")
                header_row.addWidget(name_lbl)
                header_row.addStretch()

                if entry.name in installed_versions:
                    if _update_entry(entry.name, installed_versions[entry.name]) is not None:
                        header_row.addWidget(_update_tag())
                    inst_lbl = QLabel("Installed")
                    inst_lbl.setStyleSheet("border: none; color: palette(mid);")
                    header_row.addWidget(inst_lbl)
                else:
                    dl_btn = QPushButton("Install")
                    dl_btn.setFixedWidth(70)

                    def _on_market_install(
                        checked: bool = False, e: MarketplaceEntry = entry
                    ) -> None:
                        _do_market_install(e)

                    dl_btn.clicked.connect(_on_market_install)
                    header_row.addWidget(dl_btn)

                right_col.addLayout(header_row)

                tier_label = "First-party" if entry.tier == "first_party" else "Third-party"
                meta_parts = [
                    p for p in [
                        f"v{entry.version}" if entry.version else "",
                        tier_label,
                        entry.author,
                    ] if p
                ]
                meta_lbl = QLabel("  ·  ".join(meta_parts))
                meta_lbl.setStyleSheet("border: none; color: palette(mid);")
                right_col.addWidget(meta_lbl)

                desc_text = entry.description_long or entry.description
                if desc_text:
                    desc_lbl = QLabel(desc_text)
                    desc_lbl.setWordWrap(True)
                    desc_lbl.setStyleSheet("border: none;")
                    right_col.addWidget(desc_lbl)

                card_outer.addLayout(right_col)
                container_layout.addWidget(card)

            market_scroll.setWidget(container)

        class _DownloadInstallThread(QThread):
            progress = Signal(int, int)
            done = Signal(bool, str)

            def __init__(
                self, client: MarketplaceClient, entry: MarketplaceEntry, dest: str
            ) -> None:
                super().__init__()
                self._client = client
                self._entry = entry
                self._dest = dest

            def run(self) -> None:
                ok = self._client.download(
                    self._entry, self._dest,
                    progress_callback=lambda r, t: self.progress.emit(r, t),
                )
                self.done.emit(ok, self._dest)

        _dl_thread: _DownloadInstallThread | None = None

        def _do_market_install(entry: MarketplaceEntry, updating: bool = False) -> None:
            nonlocal _dl_thread
            import tempfile
            import os
            tmp_path = os.path.join(
                tempfile.gettempdir(), f"{entry.name}-{entry.version}.zip"
            )
            verb = "Updating" if updating else "Downloading"

            def _say(text: str) -> None:
                for label in (market_status, installed_status):
                    label.setText(text)
                    label.setVisible(True)

            market_progress.setRange(0, 0)
            market_progress.setVisible(True)
            _say(f"{verb} {entry.name}…")

            _dl_thread = _DownloadInstallThread(_client, entry, tmp_path)

            def _on_dl_done(ok: bool, path: str) -> None:
                market_progress.setVisible(False)
                if not ok:
                    _say(f"Download of '{entry.name}' failed or was cancelled.")
                    return
                mgr = _mgr()
                if mgr is None:
                    _say("Plugin manager not available.")
                    return
                try:
                    # Loads (or replaces) the plugin in the running app; the window rebuilds the
                    # sidebar and menus from the manager's change notification (PLUG-190).
                    if updating:
                        mgr.update(path)
                    else:
                        mgr.install(path)
                    _say(f"'{entry.name}' {'updated' if updating else 'installed'} "
                         f"(v{entry.version}) — ready to use, no restart needed.")
                    _refresh_installed()
                    _fetch_thread_start(force=False)
                except PluginInstallError as exc:
                    _say(f"{'Update' if updating else 'Install'} failed: {exc}")
                finally:
                    import os as _os
                    with contextlib.suppress(OSError):
                        _os.unlink(path)

            _dl_thread.done.connect(_on_dl_done, Qt.ConnectionType.QueuedConnection)
            _dl_thread.start()

        def _fetch_thread_start(force: bool = False) -> None:
            nonlocal _fetch_thread
            market_scroll.setVisible(False)
            market_progress.setRange(0, 0)
            market_progress.setVisible(True)
            market_status.setText("Loading plugin list…")
            market_status.setVisible(True)
            _fetch_thread = _FetchThread(_client, force=force)
            _fetch_thread.done.connect(_populate_market, Qt.ConnectionType.QueuedConnection)
            _fetch_thread.start()

        refresh_btn.clicked.connect(lambda: _fetch_thread_start(force=True))

        class _LatestThread(QThread):
            """Looks up the latest marketplace versions in the background so the Installed tiles
            can be tagged without opening the Marketplace tab (PLUG-190)."""
            done = Signal(list, str)

            def __init__(self, client: MarketplaceClient) -> None:
                super().__init__()
                self._client = client

            def run(self) -> None:
                entries, err = self._client.fetch()
                self.done.emit(entries, err)

        _latest_thread = _LatestThread(_client)
        _latest_thread.done.connect(lambda entries, err: None if err else _remember_latest(entries), Qt.ConnectionType.QueuedConnection)
        page._latest_thread = _latest_thread   # keep the thread object alive
        _latest_thread.start()
        tabs.addTab(market_tab, "Marketplace")

        # Kick off the marketplace fetch when the tab is first shown.
        def _on_tab_changed(idx: int) -> None:
            if idx == 1 and not market_scroll.isVisible() and not market_progress.isVisible():
                _fetch_thread_start()

        tabs.currentChanged.connect(_on_tab_changed)

        return page
