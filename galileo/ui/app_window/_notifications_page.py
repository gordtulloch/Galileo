# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Options > Notifications: e-mail / SMS delivery settings (NOTIF-020, NOTIF-030, NOTIF-050).

Settings are saved as they change (``galileo.notify_settings``); the SMTP password goes to the
OS credential store, not the settings file (NFR-SEC-030). The session runner reads the saved
settings each time it builds a notification service, so changes apply to the next run.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from ._common import _new_form_layout, QWidget

logger = logging.getLogger(__name__)

# NotificationEvent value -> label shown on the page (and its inline-help heading).
EVENT_LABELS = {
    "sequence_complete": "Session complete",
    "sequence_error": "Session error",
    "safety_abort": "Safety abort",
    "autofocus_complete": "Autofocus complete",
    "meridian_flip": "Meridian flip",
    "session_message": "Session message",
}

_SECURITY_LABELS = {"none": "None", "starttls": "STARTTLS", "ssl": "SSL/TLS"}
_DEFAULT_PORTS = {"none": 25, "starttls": 587, "ssl": 465}


def run_test_send(kind: str, settings: dict[str, Any], password: str, contacts: Any = None) -> str:
    """Send one test message through the *kind* (``"email"``/``"sms"``) channel built from
    *settings*. Returns "" on success, else a message saying why it could not be sent."""
    from galileo.notify import NotificationEvent, _Notification
    from galileo.notify_settings import build_channels

    channel = next((c for k, c in build_channels(settings, contacts, password) if k == kind), None)
    if channel is None:
        if kind == "email":
            return "Enter an e-mail address and tick Send e-mail alerts first."
        return "Enter a phone number and tick Send text-message alerts first."
    note = _Notification(NotificationEvent.SESSION_MESSAGE, "Test message from Galileo.")
    try:
        asyncio.run(channel.deliver(note))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


class AppWindowNotificationsPageMixin:
    def _build_notifications_settings_page(self) -> QWidget:
        """Options > Notifications: e-mail and text-message alert delivery."""
        from PySide6.QtCore import QObject, Qt, Signal
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QGroupBox, QLabel, QLineEdit, QPushButton, QScrollArea,
            QSpinBox, QVBoxLayout,
        )
        from galileo.notify_settings import (
            SECURITY_CHOICES, get_smtp_password, load_notify_settings, save_notify_settings,
            set_smtp_password,
        )

        settings = load_notify_settings()

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel("Notification settings")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        intro = QLabel(
            "Where Galileo sends alerts when a session finishes, fails or is stopped for safety. "
            "If the Observatory has its own contact details, those recipients are used instead of "
            "the addresses below."
        )
        intro.setObjectName("StatusHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        def _line(key: str, placeholder: str = "") -> QLineEdit:
            edit = QLineEdit(str(settings.get(key, "")))
            edit.setPlaceholderText(placeholder)
            edit.editingFinished.connect(lambda: _store(key, edit.text().strip()))
            return edit

        def _store(key: str, value: Any) -> None:
            settings[key] = value
            save_notify_settings(settings)

        # --- E-mail -------------------------------------------------------------------------
        email_box = QGroupBox("E-mail")
        email_form = _new_form_layout(email_box)
        email_enabled = QCheckBox("Send e-mail alerts")
        email_enabled.setChecked(bool(settings["email_enabled"]))
        email_enabled.toggled.connect(lambda v: _store("email_enabled", bool(v)))
        email_form.addRow(email_enabled)
        email_address = _line("email_address", "you@example.com")
        email_form.addRow("E-mail address", email_address)
        smtp_host = _line("smtp_host", "smtp.example.com")
        email_form.addRow("SMTP server", smtp_host)
        smtp_port = QSpinBox()
        smtp_port.setRange(1, 65535)
        smtp_port.setValue(int(settings["smtp_port"]))
        smtp_port.valueChanged.connect(lambda v: _store("smtp_port", int(v)))
        email_form.addRow("Port", smtp_port)
        security = QComboBox()
        for choice in SECURITY_CHOICES:
            security.addItem(_SECURITY_LABELS[choice], choice)
        security.setCurrentIndex(max(security.findData(settings["smtp_security"]), 0))

        def _security_changed(_index: int) -> None:
            choice = security.currentData()
            _store("smtp_security", choice)
            # Offer the conventional port when the old one was another mode's default.
            if smtp_port.value() in _DEFAULT_PORTS.values():
                smtp_port.setValue(_DEFAULT_PORTS[choice])

        security.currentIndexChanged.connect(_security_changed)
        email_form.addRow("Security", security)
        smtp_user = _line("smtp_username", "leave blank if the server needs no login")
        email_form.addRow("Username", smtp_user)
        smtp_password = QLineEdit(get_smtp_password())
        smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        smtp_password.setToolTip("Stored in your operating system's credential store, not in a file.")
        smtp_password.editingFinished.connect(lambda: set_smtp_password(smtp_password.text()))
        email_form.addRow("Password", smtp_password)
        from_address = _line("from_address", "defaults to the username or e-mail address")
        email_form.addRow("From address", from_address)
        test_email = QPushButton("Send test e-mail")
        email_form.addRow(test_email)
        layout.addWidget(email_box)

        # --- SMS ----------------------------------------------------------------------------
        sms_box = QGroupBox("Text message (SMS)")
        sms_form = _new_form_layout(sms_box)
        sms_enabled = QCheckBox("Send text-message alerts")
        sms_enabled.setChecked(bool(settings["sms_enabled"]))
        sms_enabled.toggled.connect(lambda v: _store("sms_enabled", bool(v)))
        sms_form.addRow(sms_enabled)
        phone = _line("phone_number", "5551234567")
        sms_form.addRow("Phone number", phone)
        gateway = _line("sms_gateway", "vtext.com")
        gateway.setToolTip(
            "Your carrier's e-mail-to-SMS gateway: a domain such as vtext.com (the message goes to "
            "<phone number>@vtext.com), or an address using {number} for the phone number. "
            "Sent through the SMTP server above."
        )
        sms_form.addRow("SMS gateway", gateway)
        test_sms = QPushButton("Send test text")
        sms_form.addRow(test_sms)
        layout.addWidget(sms_box)

        # --- Events -------------------------------------------------------------------------
        events_row = QWidget()
        from PySide6.QtWidgets import QHBoxLayout
        events_layout = QHBoxLayout(events_row)
        events_layout.setContentsMargins(0, 0, 0, 0)
        for kind, title in (("email", "E-mail alerts for"), ("sms", "Text alerts for")):
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            disabled = set(settings[f"{kind}_disabled_events"])
            for value, label in EVENT_LABELS.items():
                check = QCheckBox(label)
                check.setChecked(value not in disabled)

                def _toggled(on: bool, kind=kind, value=value) -> None:
                    current = set(settings[f"{kind}_disabled_events"])
                    current.discard(value) if on else current.add(value)
                    _store(f"{kind}_disabled_events", sorted(current))

                check.toggled.connect(_toggled)
                box_layout.addWidget(check)
            events_layout.addWidget(box)
        layout.addWidget(events_row)

        status = QLabel("")
        status.setObjectName("StatusHint")
        status.setWordWrap(True)
        layout.addWidget(status)
        layout.addStretch(1)

        # --- Test send (off the UI thread: SMTP can take its full timeout) -----------------------
        class _Result(QObject):
            done = Signal(str, str)

        result = _Result(inner)
        result.done.connect(lambda kind, error: _finish(kind, error))
        buttons = {"email": test_email, "sms": test_sms}

        def _finish(kind: str, error: str) -> None:
            buttons[kind].setEnabled(True)
            noun = "e-mail" if kind == "email" else "text message"
            status.setText(f"Test {noun} failed: {error}" if error else f"Test {noun} sent.")

        def _test(kind: str) -> None:
            snapshot = dict(settings)
            snapshot.update(
                email_address=email_address.text().strip(), smtp_host=smtp_host.text().strip(),
                smtp_port=smtp_port.value(), smtp_security=security.currentData(),
                smtp_username=smtp_user.text().strip(), from_address=from_address.text().strip(),
                phone_number=phone.text().strip(), sms_gateway=gateway.text().strip(),
                email_enabled=True, sms_enabled=True,
            )
            password = smtp_password.text()
            contacts = None
            observatory = getattr(self, "_current_observatory", None)
            if observatory is not None:
                contacts = getattr(observatory, "contact_details", None)
            buttons[kind].setEnabled(False)
            status.setText("Sending test message…")

            def _work() -> None:
                try:
                    error = run_test_send(kind, snapshot, password, contacts)
                except Exception as exc:  # never leave the button disabled
                    error = f"{type(exc).__name__}: {exc}"
                result.done.emit(kind, error)

            threading.Thread(target=_work, name="galileo-notify-test", daemon=True).start()

        test_email.clicked.connect(lambda: _test("email"))
        test_sms.clicked.connect(lambda: _test("sms"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        return scroll
