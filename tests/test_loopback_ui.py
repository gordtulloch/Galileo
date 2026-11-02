# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""PROF-130 / GUIDE-100 — a loopback address is refused wherever a device or PHD2 host is typed, and a stored
one is flagged when it is loaded (TC-PROF-130, TC-GUIDE-100)."""

import pytest


@pytest.fixture
def qt_app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.requirement("TC-PROF-130")
@pytest.mark.priority("MVP")
def test_tc_prof_130_a_loopback_host_is_cleared_with_a_message_and_a_real_one_is_kept(qt_app, monkeypatch):
    """PROF-130: finishing an edit with localhost, 127.x, ::1 or 0.0.0.0 clears the field and asks for the
    real host name or LAN address; a real name or address is left alone."""
    from PySide6.QtWidgets import QLineEdit, QMessageBox

    from galileo.ui.app_window._common import guard_loopback_edit
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    edit = QLineEdit()
    guard_loopback_edit(edit)
    for bad in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "LocalHost"):  # noqa: S104
        edit.setText(bad)
        edit.editingFinished.emit()
        assert edit.text() == "", bad
    assert len(shown) == 5 and "real host name" in shown[0]
    for good in ("seestar.local", "192.168.1.50", "indi.example.org"):
        edit.setText(good)
        edit.editingFinished.emit()
        assert edit.text() == good and edit.toolTip() == "" and edit.styleSheet() == ""
    assert len(shown) == 5


@pytest.mark.requirement("TC-PROF-130")
@pytest.mark.priority("MVP")
def test_tc_prof_130_a_stored_loopback_address_is_flagged_when_loaded(qt_app):
    """PROF-130: loading a profile that already holds a loopback address marks the field and explains why,
    without changing the stored value."""
    from PySide6.QtWidgets import QLineEdit

    from galileo.ui.app_window._common import guard_loopback_edit
    edit = QLineEdit()
    guard_loopback_edit(edit)
    edit.setText("localhost")                                  # as a page does when it loads a saved profile
    assert edit.text() == "localhost" and "real host name" in edit.toolTip() and "c0392b" in edit.styleSheet()
    edit.setText("scope.local")
    assert edit.toolTip() == "" and edit.styleSheet() == ""


@pytest.mark.requirement("TC-PROF-130")
@pytest.mark.priority("MVP")
def test_tc_prof_130_every_device_page_guards_its_host_field():
    """PROF-130: every Equipment page that has a server field guards it."""
    import glob
    import pathlib
    import re
    pages = [p for p in glob.glob("galileo/ui/app_window/_*_page.py")
             if "server_edit = QLineEdit()" in pathlib.Path(p).read_text("utf-8")]
    assert len(pages) == 11
    for path in pages:
        text = pathlib.Path(path).read_text("utf-8")
        assert re.search(r"server_edit = QLineEdit\(\)\n\s+guard_loopback_edit\(server_edit\)", text), path


@pytest.mark.requirement("TC-GUIDE-100")
@pytest.mark.priority("MVP")
def test_tc_guide_100_the_phd2_host_is_guarded_and_a_stored_loopback_is_flagged(qt_app):
    """GUIDE-100: the PHD2 host field refuses loopback, and loading a saved loopback host marks it."""
    import inspect

    from galileo.ui import guider
    source = inspect.getsource(guider)
    assert "guard_loopback_edit(self.host_edit)" in source and "loopback_message(host)" in source
