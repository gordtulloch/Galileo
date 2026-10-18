# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Renders the Solve page's results: the solve table, the solution panel, the log and the frame label."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem
from galileo.platesolve import j2000_to_mount_frame


_LOG_TAIL_LINES = 300


_ARCSEC_PER_RAD_UM_MM = 206.265  # plate scale in ″/px = 206.265 × pixel size (µm) / focal length (mm)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget as _MixinBase  # type checkers see a widget (it is mixed into one)
else:
    _MixinBase = object




class SolveResultsMixin(_MixinBase):
    """Renders the Solve page's results: the solve table, the solution panel, the log and the frame label."""

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:
            """Type checking only: the attributes this mixin uses are supplied by the class it is mixed into."""

    def refresh_view(self) -> None:
        """Bring every widget up to date with the recorded solves. Called only while the page is on screen."""
        self._render_table()
        self.error_plot.set_points([(r.d_ra_arcsec, r.d_dec_arcsec) for r in self._rows
                                    if r.d_ra_arcsec is not None and r.d_dec_arcsec is not None])
        self._render_solution()
        self._update_frame_label()

    def _render_table(self) -> None:
        from galileo.ui.app_window import _format_dms, _format_hms
        table = self.table
        table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            if row.ra_deg is not None and row.dec_deg is not None:
                ra, dec = j2000_to_mount_frame(row.ra_deg, row.dec_deg, None)
                ra_text, dec_text = _format_hms(ra / 15.0), _format_dms(dec)
            else:
                ra_text = dec_text = ""
            status = {"solving": "…", "solved": "✔", "failed": "✘"}[row.status]
            cells = [
                ra_text, dec_text, row.name, status,
                "" if row.d_ra_arcsec is None else f"{row.d_ra_arcsec:+.1f}″",
                "" if row.d_dec_arcsec is None else f"{row.d_dec_arcsec:+.1f}″",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if column != 2 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if column == 3 and row.status == "failed":
                    item.setToolTip(row.reason)
                table.setItem(i, column, item)
        table.scrollToBottom()

    def _render_solution(self) -> None:
        from galileo.ui.app_window import _format_dms, _format_hms
        values = self.solution
        row = next((r for r in reversed(self._rows) if r.status == "solved"), None)
        if row is None or row.ra_deg is None or row.dec_deg is None:
            for label in values.values():
                label.setText("—")
            return
        ra, dec = j2000_to_mount_frame(row.ra_deg, row.dec_deg, None)
        values["ra"].setText(_format_hms(ra / 15.0))
        values["dec"].setText(_format_dms(dec))
        error = row.error_arcsec
        values["err"].setText("—" if error is None else
                              f"{error:.1f}″  (dRA {row.d_ra_arcsec:+.1f}″, dDE {row.d_dec_arcsec:+.1f}″)")
        scale = row.scale_arcsec_px
        values["pix"].setText(f"{scale:.2f}″" if scale else "—")
        values["pa"].setText(f"{row.rotation_deg:.2f}°" if row.rotation_deg is not None else "—")
        if scale and row.width_px and row.height_px:
            values["fov"].setText(f"{row.width_px * scale / 60:.1f}′ × {row.height_px * scale / 60:.1f}′")
        else:
            values["fov"].setText("—")

        focal, aperture, pixel_um = self._optics()
        expected_scale = _ARCSEC_PER_RAD_UM_MM * pixel_um / focal if focal and pixel_um else None
        solved_focal = _ARCSEC_PER_RAD_UM_MM * pixel_um / scale if scale and pixel_um else None
        values["ratio"].setText(f"{scale / expected_scale:.2f}x" if scale and expected_scale else "—")
        values["fl"].setText(
            "—" if solved_focal is None else
            f"{solved_focal:.1f}" + (f" ({focal:g})" if focal else ""))
        if solved_focal and aperture:
            values["fnum"].setText(f"{solved_focal / aperture:.1f}" + (f" ({focal / aperture:.1f})" if focal else ""))
        else:
            values["fnum"].setText("—")

    def _refresh_log(self) -> None:
        from galileo.diagnostics import get_recent_log_lines
        self._window.set_log_pane_text(self.log_pane, "\n".join(get_recent_log_lines(_LOG_TAIL_LINES)))

    def _update_frame_label(self) -> None:
        latest = self._rows[-1] if self._rows else None
        if latest is None:
            self.frame_label.setText("No frame yet")
            return
        import os
        state = {"solving": "solving…", "solved": "solved", "failed": "failed"}[latest.status]
        self.frame_label.setText(f"{os.path.basename(latest.fits_path)} — {state}")

    def _show_latest_frame(self) -> None:
        """Bring the image up to date after being hidden."""
        if self._latest_path and self._shown_path != self._latest_path:
            self._load_preview_async(self._latest_path)
