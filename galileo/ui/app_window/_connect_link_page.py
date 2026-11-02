# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Connect Link (LINK-250): the listener's state, pairing approvals and paired peers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ._common import _new_form_layout, QWidget

logger = logging.getLogger(__name__)

REFRESH_MS = 2000


def describe_status(status: dict[str, Any]) -> str:
    """One readable line for the page's status label."""
    if status["running"]:
        return f"Listening on {status['host']}:{status['port']} for {', '.join(status['plugins'])}."
    if not status["enabled"]:
        return "Off. Nothing is listening and nothing is advertised."
    if not status["plugins"]:
        return ("Enabled, but no installed plugin uses it yet, so nothing is listening. "
                "Install NodeConnect, MobileConnect or WebConnect.")
    return "Enabled but not listening. See the log."


def describe_time(stamp: float | None) -> str:
    return "never" if not stamp else datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")  # noqa: DTZ006 - local


class AppWindowConnectLinkPageMixin:
    def _build_connect_link_settings_page(self) -> QWidget:
        """Options > Connect Link: turn the link on, set its port and lifetimes, approve pairing requests
        (each shown with its confirmation code) and revoke or delete paired devices."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import (
            QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
            QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
        )
        from galileo.connect_link.host import get_host
        from galileo.connect_link.service import LinkSettings, SettingsError

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        heading = QLabel("Connect Link")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        intro = QLabel("The encrypted link other computers, phones and browsers use to reach this one. "
                       "It is off until you turn it on, and it only listens while a plugin that needs it is installed.")
        intro.setObjectName("StatusHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        status_label = QLabel()
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        # --- Listener ------------------------------------------------------------------------------
        box = QGroupBox("Listener")
        form = _new_form_layout(box)
        enable = QCheckBox("Enable Connect Link")
        form.addRow(enable)
        port = QSpinBox()
        port.setRange(1024, 65535)
        form.addRow("Port", port)
        expiry = QSpinBox()
        expiry.setRange(30, 3600)
        expiry.setSuffix(" s")
        form.addRow("Pairing request lifetime", expiry)
        retention = QSpinBox()
        retention.setRange(1, 3650)
        retention.setSuffix(" days")
        form.addRow("Keep the audit log for", retention)
        advertise = QCheckBox("Advertise on the network")
        form.addRow(advertise)
        apply_btn = QPushButton("Apply")
        form.addRow(apply_btn)
        fingerprint = QLabel()
        fingerprint.setTextInteractionFlags(fingerprint.textInteractionFlags().TextSelectableByMouse)
        fingerprint.setWordWrap(True)
        form.addRow("Certificate fingerprint", fingerprint)
        layout.addWidget(box)

        # --- Pairing requests -----------------------------------------------------------------------
        pending_box = QGroupBox("Pairing requests")
        pending_layout = QVBoxLayout(pending_box)
        pending = QTableWidget(0, 4)
        pending.setHorizontalHeaderLabels(["Device", "Plugin", "Code", "From"])
        pending.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        pending.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        pending.horizontalHeader().setStretchLastSection(True)
        pending_layout.addWidget(pending)
        row = QHBoxLayout()
        approve_btn, reject_btn = QPushButton("Approve…"), QPushButton("Reject")
        row.addWidget(approve_btn)
        row.addWidget(reject_btn)
        row.addStretch(1)
        pending_layout.addLayout(row)
        layout.addWidget(pending_box)

        # --- Paired devices ---------------------------------------------------------------------------
        peers_box = QGroupBox("Paired devices")
        peers_layout = QVBoxLayout(peers_box)
        peers = QTableWidget(0, 6)
        peers.setHorizontalHeaderLabels(["Device", "Plugin", "Kind", "Permissions", "Last contact", "Status"])
        peers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        peers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        peers.horizontalHeader().setStretchLastSection(True)
        peers_layout.addWidget(peers)
        row2 = QHBoxLayout()
        revoke_btn, delete_btn = QPushButton("Revoke"), QPushButton("Delete")
        row2.addWidget(revoke_btn)
        row2.addWidget(delete_btn)
        row2.addStretch(1)
        peers_layout.addLayout(row2)
        layout.addWidget(peers_box)
        layout.addStretch(1)

        # --- behaviour --------------------------------------------------------------------------------
        host_ref: dict[str, Any] = {}

        def host():
            if "h" not in host_ref:
                host_ref["h"] = get_host()
            return host_ref["h"]

        def load_settings() -> None:
            s = host().settings()
            for widget, value in ((port, s.port), (expiry, s.pairing_expiry_s), (retention, s.audit_retention_days)):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
            for check, value in ((enable, s.enabled), (advertise, s.advertise)):
                check.blockSignals(True)
                check.setChecked(value)
                check.blockSignals(False)

        def refresh() -> None:
            try:
                _refresh()
            except Exception as exc:                # the page is built with every other; it must never break them
                logger.exception("Could not refresh the Connect Link page")
                status_label.setText(f"Connect Link is unavailable: {exc}")

        def _refresh() -> None:
            h = host()
            status_label.setText(describe_status(h.status()))
            fingerprint.setText(h.fingerprint() if h.status()["running"] or h.settings().enabled else "(made when first needed)")
            reqs = h.pending()
            pending.setRowCount(len(reqs))
            for i, r in enumerate(reqs):
                for c, text in enumerate((r.name, r.plugin, r.code, r.source)):
                    item = QTableWidgetItem(text)
                    if c == 0:
                        item.setData(256, r.request_id)         # Qt.UserRole
                    pending.setItem(i, c, item)
            people = h.peers()
            peers.setRowCount(len(people))
            for i, p in enumerate(people):
                state = "revoked" if p.revoked_at else "active"
                cells = (p.name, p.plugin, p.kind or "", ", ".join(sorted(p.permissions)), describe_time(p.last_contact), state)
                for c, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if c == 0:
                        item.setData(256, p.peer_id)
                    peers.setItem(i, c, item)
            approve_btn.setEnabled(bool(reqs))
            reject_btn.setEnabled(bool(reqs))
            revoke_btn.setEnabled(bool(people))
            delete_btn.setEnabled(bool(people))

        def current_id(table: QTableWidget) -> str:
            rows = table.selectionModel().selectedRows()
            row_index = rows[0].row() if rows else (0 if table.rowCount() == 1 else -1)
            item = table.item(row_index, 0) if row_index >= 0 else None
            return str(item.data(256)) if item is not None else ""

        def warn(text: str) -> None:
            QMessageBox.warning(inner, "Connect Link", text)

        def on_enable(checked: bool) -> None:
            try:
                host().set_enabled(checked)
            except Exception as exc:
                logger.exception("Could not change Connect Link")
                warn(f"Connect Link could not be {'started' if checked else 'stopped'}: {exc}")
            refresh()

        def on_apply() -> None:
            current = host().settings()
            new = LinkSettings(enable.isChecked(), port.value(), expiry.value(), retention.value(),
                               advertise.isChecked(), current.bind_host)
            try:
                host().apply_settings(new)
            except SettingsError as exc:
                warn(str(exc))
            except Exception as exc:
                logger.exception("Could not apply the Connect Link settings")
                warn(f"The settings could not be applied: {exc}")
            refresh()

        def on_approve() -> None:
            rid = current_id(pending)
            req = next((r for r in host().pending() if r.request_id == rid), None)
            if req is None:
                return
            declared = sorted(host().service.peers.declared(req.plugin))
            dialog = QDialog(inner)
            dialog.setWindowTitle("Approve device")
            dlg_layout = QVBoxLayout(dialog)
            dlg_layout.addWidget(QLabel(f"Pair “{req.name}” ({req.plugin})?\nCheck that its code is {req.code}."))
            boxes = []
            for permission in declared:
                check = QCheckBox(permission)
                check.setChecked(not permission.startswith("config."))
                dlg_layout.addWidget(check)
                boxes.append(check)
            if not declared:
                dlg_layout.addWidget(QLabel("This plugin has not said what it may be given."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            dlg_layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                host().approve(rid, [b.text() for b in boxes if b.isChecked()])
            except Exception as exc:
                warn(f"Could not approve it: {exc}")
            refresh()

        def on_reject() -> None:
            rid = current_id(pending)
            if rid:
                host().reject(rid)
            refresh()

        def on_revoke() -> None:
            pid = current_id(peers)
            if pid:
                host().revoke(pid)
            refresh()

        def on_delete() -> None:
            pid = current_id(peers)
            if pid and QMessageBox.question(
                    inner, "Delete device",
                    "Delete this paired device? It will have to pair again.") == QMessageBox.StandardButton.Yes:
                host().delete(pid)
            refresh()

        enable.toggled.connect(on_enable)
        apply_btn.clicked.connect(on_apply)
        approve_btn.clicked.connect(on_approve)
        reject_btn.clicked.connect(on_reject)
        revoke_btn.clicked.connect(on_revoke)
        delete_btn.clicked.connect(on_delete)

        timer = QTimer(inner)
        timer.setInterval(REFRESH_MS)

        def tick() -> None:
            if inner.isVisible():
                refresh()

        timer.timeout.connect(tick)
        timer.start()
        inner._connect_link = {  # type: ignore[attr-defined]
            "refresh": refresh, "load": load_settings, "enable": enable, "port": port, "expiry": expiry,
            "retention": retention, "advertise": advertise, "apply": apply_btn, "approve": approve_btn,
            "reject": reject_btn, "revoke": revoke_btn, "delete": delete_btn, "pending": pending,
            "peers": peers, "status": status_label, "fingerprint": fingerprint, "host": host,
        }
        load_settings()
        refresh()
        return inner
