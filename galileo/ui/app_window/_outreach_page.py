# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Outreach (LINK-190): open, extend and end an outreach event, and show its QR codes."""

from __future__ import annotations

import logging
from typing import Any

from ._common import _new_form_layout, QWidget

logger = logging.getLogger(__name__)

REFRESH_MS = 1000


def describe_event(status: dict[str, Any]) -> str:
    """One readable line for the event status label."""
    if not status.get("open"):
        return "No event is open. Nothing is offered to visitors."
    minutes, seconds = divmod(int(status["remaining_s"]), 60)
    return (f"Event open: {minutes} min {seconds:02d} s left, {status['guests']} visitor(s) now "
            f"(most at once: {status['peak']}), offering {', '.join(status['piers'].values())}.")


class AppWindowOutreachPageMixin:
    def _build_outreach_settings_page(self) -> QWidget:
        """Options > Outreach: let visitors on a guest Wi-Fi watch the live image from their phones."""
        from PySide6.QtCore import QByteArray, Qt, QTimer
        from PySide6.QtSvgWidgets import QSvgWidget
        from PySide6.QtWidgets import (
            QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
            QPushButton, QSpinBox, QVBoxLayout,
        )
        from galileo.connect_link.host import get_host
        from galileo.connect_link.outreach import PASSPHRASE_SECRET, OutreachError, OutreachOptions, qr_svg

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        heading = QLabel("Outreach")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        intro = QLabel("Let visitors at a star party watch the live image on their own phones. An outreach event is "
                       "off until you open it, lasts a set time, and only reaches devices on the guest Wi-Fi.")
        intro.setObjectName("StatusHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        status = QLabel()
        status.setWordWrap(True)
        layout.addWidget(status)

        # --- the event ------------------------------------------------------------------------------
        event_box = QGroupBox("Event")
        event_row = QHBoxLayout(event_box)
        duration = QSpinBox()
        duration.setRange(5, 1440)
        duration.setSuffix(" min")
        duration.setProperty("helpKey", "Event duration")
        event_row.addWidget(QLabel("Event duration"))
        event_row.addWidget(duration)
        open_btn, extend_btn, end_btn = QPushButton("Open event"), QPushButton("Extend"), QPushButton("End event")
        eject_btn, secret_btn = QPushButton("Eject all guests"), QPushButton("New secret")
        for b in (open_btn, extend_btn, end_btn, eject_btn, secret_btn):
            event_row.addWidget(b)
        event_row.addStretch(1)
        layout.addWidget(event_box)

        # --- the QR codes -------------------------------------------------------------------------------
        display_box = QGroupBox("Event display")
        display_layout = QHBoxLayout(display_box)
        layout.addWidget(display_box)

        # --- options --------------------------------------------------------------------------------------
        box = QGroupBox("Options")
        form = _new_form_layout(box)
        ssid = QLineEdit()
        form.addRow("Wi-Fi network name", ssid)
        passphrase = QLineEdit()
        passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        passphrase.setPlaceholderText("Kept in the system keychain; leave blank to keep the saved one")
        form.addRow("Wi-Fi passphrase", passphrase)
        subnets = QLineEdit()
        subnets.setPlaceholderText("e.g. 192.168.50.0/24")
        form.addRow("Allowed networks", subnets)
        default_duration = QSpinBox()
        default_duration.setRange(5, 1440)
        default_duration.setSuffix(" min")
        form.addRow("Default duration", default_duration)
        cap = QSpinBox()
        cap.setRange(1, 500)
        form.addRow("Guest limit", cap)
        size = QSpinBox()
        size.setRange(160, 1024)
        size.setSuffix(" px")
        form.addRow("Image size", size)
        quality = QSpinBox()
        quality.setRange(30, 80)
        form.addRow("Image quality", quality)
        piers = QListWidget()
        piers.setMaximumHeight(110)
        form.addRow("Piers offered", piers)
        surfaces = QListWidget()
        surfaces.setMaximumHeight(80)
        form.addRow("Surfaces", surfaces)
        save_btn = QPushButton("Save")
        form.addRow(save_btn)
        layout.addWidget(box)
        layout.addStretch(1)

        host_ref: dict[str, Any] = {}

        def host():
            if "h" not in host_ref:
                host_ref["h"] = get_host()
            return host_ref["h"]

        def warn(text: str) -> None:
            QMessageBox.warning(inner, "Outreach", text)

        def load() -> None:
            o = OutreachOptions.load()
            ssid.setText(o.ssid)
            subnets.setText(", ".join(o.subnets))
            duration.setValue(o.default_duration_min)
            default_duration.setValue(o.default_duration_min)
            cap.setValue(o.guest_cap)
            size.setValue(o.preview_size)
            quality.setValue(o.preview_quality)
            piers.clear()
            try:
                from galileo.library.models.base import db
                from galileo.library.models.observatory import PierRecord
                db.connect(reuse_if_open=True)
                for rec in PierRecord.select():
                    item = QListWidgetItem(f"{rec.observatory.name} / {rec.name}")
                    item.setData(Qt.ItemDataRole.UserRole, str(rec.id))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if str(rec.id) in o.piers else Qt.CheckState.Unchecked)
                    piers.addItem(item)
            except Exception:
                logger.debug("No Piers to offer", exc_info=True)
            surfaces.clear()
            for name in sorted(host().service.outreach._surfaces):
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name in o.surfaces else Qt.CheckState.Unchecked)
                surfaces.addItem(item)

        def checked(widget: QListWidget, role: bool) -> tuple[str, ...]:
            out = []
            for i in range(widget.count()):
                item = widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    out.append(str(item.data(Qt.ItemDataRole.UserRole)) if role else item.text())
            return tuple(out)

        def on_save() -> None:
            try:
                OutreachOptions(
                    ssid.text(), tuple(p.strip() for p in subnets.text().split(",") if p.strip()),
                    default_duration.value(), cap.value(), size.value(), quality.value(),
                    checked(piers, True), checked(surfaces, False)).save()
                if passphrase.text():
                    from galileo.connect_link.secrets_store import KeyringSecretStore
                    KeyringSecretStore().set(PASSPHRASE_SECRET, passphrase.text())
                    passphrase.clear()
            except OutreachError as exc:
                warn(str(exc))
                return                                  # keep what the user typed so they can correct it
            except Exception as exc:
                logger.exception("Could not save the outreach options")
                warn(f"The options could not be saved: {exc}")
                return
            load()
            refresh()

        def show_display() -> None:
            while display_layout.count():
                taken = display_layout.takeAt(0)
                w = taken.widget() if taken is not None else None
                if w is not None:
                    w.deleteLater()
            if not host().event_status().get("open"):
                return
            shown = host().event_display()
            items = [("Wi-Fi", shown["wifi"])] if shown["wifi"] else []
            items += [(s["surface"], s["payload"]) for s in shown["surfaces"]]
            for caption, payload in items:
                column = QVBoxLayout()
                svg = QSvgWidget()
                svg.load(QByteArray(qr_svg(payload).encode("utf-8")))
                svg.setFixedSize(180, 180)
                column.addWidget(svg)
                column.addWidget(QLabel(caption))
                holder = QWidget()
                holder.setLayout(column)
                display_layout.addWidget(holder)
            display_layout.addStretch(1)

        shown_for: dict[str, Any] = {"secret": None}

        def refresh() -> None:
            try:
                st = host().event_status()
                status.setText(describe_event(st))
                is_open = bool(st.get("open"))
                open_btn.setEnabled(not is_open)
                for b in (extend_btn, end_btn, eject_btn, secret_btn):
                    b.setEnabled(is_open)
                marker = id(host().service.outreach._event) if is_open else None
                if marker != shown_for["secret"]:
                    shown_for["secret"] = marker
                    show_display()
            except Exception as exc:
                logger.exception("Could not refresh the outreach page")
                status.setText(f"Outreach is unavailable: {exc}")

        def guarded(action) -> None:
            try:
                action()
            except OutreachError as exc:
                warn(str(exc))
            except Exception as exc:
                logger.exception("Outreach action failed")
                warn(f"That did not work: {exc}")
            shown_for["secret"] = "refresh"          # noqa: S105 - a redraw marker, not a secret; redraws the QR codes
            refresh()

        open_btn.clicked.connect(lambda: guarded(lambda: host().open_event("owner", duration.value())))
        extend_btn.clicked.connect(lambda: guarded(lambda: host().extend_event(30)))
        end_btn.clicked.connect(lambda: guarded(host().close_event))
        eject_btn.clicked.connect(lambda: guarded(host().eject_guests))
        secret_btn.clicked.connect(lambda: guarded(host().reissue_secret))
        save_btn.clicked.connect(on_save)

        timer = QTimer(inner)
        timer.setInterval(REFRESH_MS)

        def tick() -> None:
            if inner.isVisible():
                refresh()

        timer.timeout.connect(tick)
        timer.start()
        inner._outreach = {  # type: ignore[attr-defined]
            "refresh": refresh, "status": status, "open": open_btn, "extend": extend_btn, "end": end_btn,
            "eject": eject_btn, "secret": secret_btn, "save": save_btn, "duration": duration, "ssid": ssid,
            "subnets": subnets, "cap": cap, "piers": piers, "display": display_layout, "load": load,
            "passphrase": passphrase,
        }
        load()
        refresh()
        return inner
