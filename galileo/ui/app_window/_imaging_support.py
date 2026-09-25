# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Shared helpers the Imaging page and sequencer/scheduler frame-capture paths both need: device-connection state, FITS header context, and mount slew-to-object handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from galileo.exceptions import MountParkedError, SlewObstructedError

from ._common import _camera_slot_label, _camera_backend_key_for_slot, _parse_alpaca_device_number, _PARKED_MESSAGE, _OBSTRUCTED_MESSAGE

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # See _state.py: every method below takes an explicit `self:
    # AppWindowState` type so mypy can resolve calls into every
    # *other* mixin's attributes/methods -- mypy's documented
    # pattern for mixin classes. No runtime effect; this class's
    # actual base stays plain `object`.
    from ._state import AppWindowState


class AppWindowImagingSupportMixin:
    def camera_not_connected_message(self: AppWindowState) -> str:
        """Why a screen can't capture: which camera the top-bar selector is on, and what to do."""
        from galileo.observatory import get_device_config
        name = _camera_slot_label(self._active_camera_slot)
        if self._current_pier is not None:
            try:
                cfg = get_device_config(self._current_pier, "camera", slot=self._active_camera_slot)
            except Exception:
                cfg = None
            if cfg is None:
                return (f"No {name} is configured for this Pier. Set one up on Equipment > Camera, "
                        "then choose it in the Camera selector at the top of the window.")
            if cfg.device_name:
                name = f"{name} ({cfg.device_name})"
        return (f"{name} is selected but not connected. Connect it on Equipment > Camera, or pick "
                "another camera in the Camera selector at the top of the window.")

    def _imaging_frame_context(self: AppWindowState) -> dict:
        """What the Imaging page knows about the rig, as FITS header values for
        ``ImagingService.frame_context`` (IMG-150): telescope and camera, optics, the site, where the
        mount is pointing and what it is aiming at, and the focuser position. Whatever can't be found
        is left out; nothing here may stop a capture."""
        import asyncio
        from galileo.ui.imaging import format_dec_dms, format_ra_hms

        context: dict = {}
        tube = self.active_optical_tube()
        if tube is not None:
            context.update(telescope=tube.name, focal_length_mm=tube.focal_length_mm or None,
                           aperture_mm=tube.aperture_mm or None)
        camera_backend = self._camera_backends.get(_camera_backend_key_for_slot(self._active_camera_slot))
        pier = self._current_pier
        camera_cfg = None
        if pier is not None:
            from galileo.observatory import get_device_config
            try:
                camera_cfg = get_device_config(pier, "camera", slot=self._active_camera_slot)
            except Exception:
                logger.exception("Could not load the camera's configuration for the FITS header")
        if camera_cfg is not None:
            context.update(instrument=camera_cfg.device_name or camera_cfg.sensor_name,
                           pixel_size_x_um=camera_cfg.pixel_size_um, pixel_size_y_um=camera_cfg.pixel_size_um,
                           bayer_pattern=camera_cfg.bayer_pattern)
        context.setdefault("instrument", getattr(camera_backend, "device_name", None))

        site_lat = site_long = None
        if pier is not None:
            try:
                observatory = pier.observatory
                site_lat, site_long = observatory.latitude, observatory.longitude
                context.update(site=observatory.name, observer=observatory.owner)
            except Exception:
                logger.exception("Could not read the Observatory for the FITS header")

        pointing = None
        mount = (self._device_pages.get("mount") or {}).get("adapter")
        if mount is not None:
            try:
                status = asyncio.run(mount.get_status()) or {}
                ra_hours, dec = status.get("right_ascension"), status.get("declination")
                if ra_hours is not None and dec is not None:
                    from galileo.platesolve import mount_frame_to_j2000
                    pointing = mount_frame_to_j2000(ra_hours * 15.0, dec, status.get("equatorial_system"))
                context["pier_side"] = status.get("side_of_pier")
                if site_lat is None:
                    site_lat, site_long = status.get("site_latitude"), status.get("site_longitude")
            except Exception:
                logger.warning("Could not read the mount's position for the FITS header", exc_info=True)
        context.update(site_lat_deg=site_lat, site_long_deg=site_long)

        target = self.current_object()
        if target is not None:
            context.update(objctra=format_ra_hms(target.ra_deg), objctdec=format_dec_dms(target.dec_deg))
        aim = pointing or ((target.ra_deg, target.dec_deg) if target is not None else None)
        if aim is not None:
            context.update(ra_deg=aim[0], dec_deg=aim[1])

        focuser = ((self._device_pages.get("focuser") or {}).get("get_adapter") or (lambda: None))()
        position = getattr(focuser, "position", None)
        if isinstance(position, int) and position > 0:
            context["focus_position"] = position
        return {key: value for key, value in context.items() if value not in (None, "")}

    def _mount_to_object(self: AppWindowState, action: str, obj: dict) -> bool:
        """Point the current Pier's mount at a Star Atlas *obj*: ``"goto"`` slews
        to it, ``"sync"`` tells the mount it is already pointing there. Uses the
        connection made on the Equipment > Mount page (which is reset whenever
        the Pier changes) and reports the outcome on the status bar. Returns
        whether the command was sent."""
        import asyncio
        import datetime as dt
        from galileo.planning import star_atlas as sa

        verb = "Goto" if action == "goto" else "Sync"
        adapter = (self._device_pages.get("mount") or {}).get("adapter")
        if adapter is None:
            logger.warning("Mount %s to %s not sent: no mount is connected", action, obj["name"])
            self._window.statusBar().showMessage(
                f"{verb}: no mount is connected — connect it on Equipment > Mount.", 6000)
            return False
        if obj["alt"] < 0:
            logger.warning("Mount %s to %s not sent: it is below the horizon (alt %.1f°)", action, obj["name"], obj["alt"])
            self._window.statusBar().showMessage(
                f"{verb}: {obj['name']} is below the horizon at this time and place.", 6000)
            return False
        ra_deg, dec_deg = obj["ra_deg"], obj["dec_deg"]      # the atlas holds J2000
        try:
            if (asyncio.run(adapter.get_status()) or {}).get("equatorial_system") != "J2000":
                # Every other mount takes coordinates of date (JNow).
                jd = sa.julian_date(dt.datetime.now(dt.UTC).replace(tzinfo=None))
                ra_deg, dec_deg = (float(v) for v in sa.precess_from_j2000(ra_deg, dec_deg, jd))
            if action == "goto":
                asyncio.run(adapter.slew_to_coordinates(ra_deg, dec_deg))
            else:
                asyncio.run(adapter.sync_to_coordinates(ra_deg, dec_deg))
        except MountParkedError:
            self._window.statusBar().showMessage(f"{verb}: {_PARKED_MESSAGE}", 6000)
            return False
        except SlewObstructedError:
            self._window.statusBar().showMessage(f"{verb}: {_OBSTRUCTED_MESSAGE}", 6000)
            return False
        except Exception:
            logger.exception("Mount %s to %s failed", action, obj["name"])
            self._window.statusBar().showMessage(f"{verb} to {obj['name']} failed — see log.", 6000)
            return False
        logger.info("Mount: %s to %s (RA %.4fh Dec %.4f°)", action, obj["name"], ra_deg / 15.0, dec_deg)
        self._window.statusBar().showMessage(
            f"Slewing the mount to {obj['name']}." if action == "goto" else f"Mount synced to {obj['name']}.", 4000)
        if action == "goto":
            self._track_when_slew_finishes(adapter, obj)
        return True

    def _connect_device_adapter(self: AppWindowState, category, driver: str, server: str, port: int, device_name: str):
        """Instantiate and connect one device backend for *category*, or
        return ``None`` (having logged why) on failure. Shared by any
        Equipment page that needs a live per-device connection — the
        Camera page's auto-connect and the Focuser page's per-panel Connect
        and status polling."""
        import asyncio
        try:
            adapter = self._make_adapter(category, driver, server, port, device_name)
            asyncio.run(adapter.connect())
        except Exception:
            logger.exception("Could not connect %s %r at %s:%s", category, device_name, server, port)
            return None
        return adapter

    @staticmethod
    def _make_adapter(category, driver: str, server: str, port: int, device_name: str):
        """Instantiate (without connecting) the INDI or Alpaca backend for one
        scanned device. *device_name* is the scan-result label: an INDI device
        name, or an Alpaca ``"Name (#N)"`` label carrying the device number."""
        if driver == "INDI":
            from galileo.adapters.indi import get_adapter_class
            return get_adapter_class(category)(host=server, port=port, device_name=device_name)
        from galileo.adapters.alpaca import get_adapter_class
        kwargs = {}
        device_number = _parse_alpaca_device_number(device_name)
        if device_number is not None:
            kwargs["device_number"] = device_number
        return get_adapter_class(category)(host=server, port=port, **kwargs)

    def _lookup_driver_info(self: AppWindowState, category, driver: str, server: str, port: int, device_name: str) -> dict:
        """Read one device's driver name/version *without connecting it* (see
        ``DeviceBackend.get_driver_info``), for the Equipment pages' "Driver
        info" row as soon as a device is picked. Returns ``{}`` if no device is
        chosen or the lookup fails (logged; the row then shows a dash)."""
        if not device_name:
            return {}
        import asyncio
        try:
            adapter = self._make_adapter(category, driver, server or "localhost", port, device_name)
            return asyncio.run(adapter.get_driver_info()) or {}
        except Exception:
            logger.exception("Could not read driver info for %r at %s:%s", device_name, server, port)
            return {}

    @staticmethod
    def _build_driver_info_row() -> tuple:
        """The "Driver info" / "Driver version" pair every Equipment page
        shows (laid out as on the Filter Wheel page). Returns ``(layout,
        apply)`` where ``apply(info)`` fills it from a ``get_driver_info()``
        dict — a dash for anything missing, or for ``None``/``{}`` when
        nothing is known yet."""
        from PySide6.QtWidgets import QHBoxLayout, QFormLayout, QLabel

        row = QHBoxLayout()
        info_form = QFormLayout()
        info_value = QLabel("—")
        info_form.addRow("Driver info", info_value)
        row.addLayout(info_form)
        version_form = QFormLayout()
        version_value = QLabel("—")
        version_form.addRow("Driver version", version_value)
        row.addLayout(version_form)
        row.addStretch(1)

        def apply(info: dict | None) -> None:
            info = info or {}
            info_value.setText(info.get("driver_info") or "—")
            version_value.setText(info.get("driver_version") or "—")

        return row, apply

    def _connect_camera_device(self: AppWindowState, slot_label: str, driver: str, server: str, port: int, device_name: str) -> None:
        """Connect one camera device — shared by the Camera page's Primary
        and any additional camera panels, which share a connection
        (driver/server/port) but are otherwise independent devices, each
        connected separately."""
        from galileo.core.devices import DeviceCategory
        adapter = self._connect_device_adapter(DeviceCategory.CAMERA, driver, server, port, device_name)
        if adapter is None:
            self._window.statusBar().showMessage(
                f"Could not connect to saved {slot_label} {device_name!r} — see log.", 6000
            )
            return
        self._camera_backends[slot_label] = adapter
        self._refresh_camera_combo()      # the selector shows which cameras are connected
        self._window.statusBar().showMessage(f"Connected to {slot_label} {device_name!r}.", 4000)
