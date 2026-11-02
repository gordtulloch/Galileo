# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Replication specs for the configuration tables (REPL-030).

The database links these tables by integer ids that differ on every node, so on the wire a parent is named
by its natural key instead: an Observatory by its name, a Pier by ``[observatory name, pier name]``. ``to_wire``
turns an ``observatory_id`` into ``observatory`` and a ``pier_id`` into ``pier``; ``from_wire`` turns them
back into this node's ids, or raises :class:`UnresolvedParent` when the parent has not arrived yet (specs are
applied in dependency order, so that is a genuine error). Secrets (a plate-solver web key) never leave in the
default wire form, and a value that describes one machine's hardware is left on that machine.

``scheduler_jobs`` stays pending: the scheduler is being reworked.
"""

from __future__ import annotations

from typing import Any

from galileo.replication.registry import ReplicableRegistry, ReplicableSpec, Row

OBS_REF = "(SELECT name FROM observatories WHERE id = OLD.observatory_id)"
PIER_REF = ("json_array((SELECT o.name FROM observatories o JOIN piers p ON p.observatory_id = o.id "
            "WHERE p.id = OLD.pier_id), (SELECT name FROM piers WHERE id = OLD.pier_id))")


class UnresolvedParent(LookupError):
    """A row refers to a parent this node does not have."""


def _db():
    from galileo.library.models.base import db
    db.connect(reuse_if_open=True)
    return db


def observatory_ref(observatory_id: int) -> str | None:
    row = _db().execute_sql("SELECT name FROM observatories WHERE id = ?", (observatory_id,)).fetchone()
    return None if row is None else str(row[0])


def pier_ref(pier_id: int) -> list[str] | None:
    row = _db().execute_sql(
        "SELECT o.name, p.name FROM piers p JOIN observatories o ON o.id = p.observatory_id WHERE p.id = ?",
        (pier_id,)).fetchone()
    return None if row is None else [str(row[0]), str(row[1])]


def observatory_id(ref: Any) -> int:
    row = _db().execute_sql("SELECT id FROM observatories WHERE name = ?", (ref,)).fetchone()
    if row is None:
        raise UnresolvedParent(f"no Observatory named {ref!r}")
    return int(row[0])


def pier_id(ref: Any) -> int:
    try:
        obs, name = ref
    except (TypeError, ValueError):
        raise UnresolvedParent(f"not a Pier reference: {ref!r}") from None
    row = _db().execute_sql(
        "SELECT p.id FROM piers p JOIN observatories o ON o.id = p.observatory_id WHERE o.name = ? AND p.name = ?",
        (obs, name)).fetchone()
    if row is None:
        raise UnresolvedParent(f"no Pier {name!r} in Observatory {obs!r}")
    return int(row[0])


def _via_observatory(row: Row) -> Row:
    out = dict(row)
    ref = observatory_ref(out.pop("observatory_id"))
    if ref is None:
        raise UnresolvedParent("the Observatory this row belongs to no longer exists")
    out["observatory"] = ref
    return out


def _via_pier(row: Row) -> Row:
    out = dict(row)
    ref = pier_ref(out.pop("pier_id"))
    if ref is None:
        raise UnresolvedParent("the Pier this row belongs to no longer exists")
    out["pier"] = ref
    return out


def _from_observatory(row: Row) -> Row:
    out = dict(row)
    out["observatory_id"] = observatory_id(out.pop("observatory"))
    return out


def _from_pier(row: Row) -> Row:
    out = dict(row)
    out["pier_id"] = pier_id(out.pop("pier"))
    return out


# table -> (natural key on the wire, the SQL tombstone key expressions, depends_on, to_wire, from_wire, extras)
_SPECS: dict[str, dict[str, Any]] = {
    "observatories": {"key": ("name",), "exprs": ["OLD.name"], "deps": ()},
    "session_templates": {"key": ("name",), "exprs": ["OLD.name"], "deps": ()},
    "piers": {"key": ("observatory", "name"), "exprs": [OBS_REF, "OLD.name"], "deps": ("observatories",),
              "to": _via_observatory, "from": _from_observatory},
    "horizon_points": {"key": ("observatory", "azimuth_deg"), "exprs": [OBS_REF, "OLD.azimuth_deg"],
                       "deps": ("observatories",), "to": _via_observatory, "from": _from_observatory},
    "observatory_safety_rules": {"key": ("observatory", "slot", "parameter"),
                                 "exprs": [OBS_REF, "OLD.slot", "OLD.parameter"], "deps": ("observatories",),
                                 "to": _via_observatory, "from": _from_observatory},
    "safety_device_configs": {"key": ("observatory", "category", "slot"),
                              "exprs": [OBS_REF, "OLD.category", "OLD.slot"], "deps": ("observatories",),
                              "to": _via_observatory, "from": _from_observatory},
    "optical_tubes": {"key": ("pier", "position"), "exprs": [PIER_REF, "OLD.position"], "deps": ("piers",),
                      "to": _via_pier, "from": _from_pier},
    "device_configs": {"key": ("pier", "category", "slot"), "exprs": [PIER_REF, "OLD.category", "OLD.slot"],
                       "deps": ("piers",), "to": _via_pier, "from": _from_pier,
                       # The retained focuser position and emergency position are readings of one machine's hardware.
                       "node_local": frozenset({"focuser_position"})},
    "autofocus_settings": {"key": ("pier",), "exprs": [PIER_REF], "deps": ("piers",), "to": _via_pier,
                           "from": _from_pier},
    "solver_settings": {"key": ("pier",), "exprs": [PIER_REF], "deps": ("piers",), "to": _via_pier,
                        "from": _from_pier, "secret": frozenset({"nova_api_key"}),
                        # Paths to programs and databases belong to the machine they are installed on.
                        "node_local": frozenset({"executable", "astrometry_executable", "tetra3_database"})},
    "filter_offsets": {"key": ("pier", "filter_name"), "exprs": [PIER_REF, "OLD.filter_name"], "deps": ("piers",),
                       "to": _via_pier, "from": _from_pier},
}

PAYLOAD_COLUMNS: dict[str, tuple[str, ...]] = {
    "observatories": ("latitude", "longitude", "timezone", "physical_address", "owner", "elevation_m",
                      "notification_type", "email_address", "cell_number"),
    "session_templates": ("blocks_json",),
    "piers": ("connect_on_startup",),
    "horizon_points": ("altitude_deg",),
    "observatory_safety_rules": ("label", "unit", "safety_related", "operator", "threshold"),
    "safety_device_configs": ("driver", "server", "port", "device_name"),
    "optical_tubes": ("name", "focal_length_mm", "aperture_mm", "optical_system", "image_reversed",
                      "image_inverted", "associated_devices"),
    "device_configs": ("driver", "server", "port", "device_name", "pixel_size_um", "sensor_width_px",
                       "sensor_height_px", "sensor_name", "bayer_pattern", "max_well_depth", "panel_type",
                       "flip_enabled", "flip_ha_deg", "alt_limits_enabled", "min_alt", "max_alt", "alt_tracking_only",
                       "ha_limits_enabled", "max_ha_hours", "default_gain", "default_offset", "emergency_focus",
                       "focuser_mode", "travel_min", "travel_max"),
    "autofocus_settings": ("step_size", "num_points", "exposure_s", "backlash_compensation"),
    "solver_settings": ("fov_hint_deg", "search_radius_deg", "downsample", "backend", "nova_api_key"),
    "filter_offsets": ("is_primary", "measurement_1", "measurement_2", "measurement_3", "measurement_4",
                       "offset_steps"),
}

NATURAL_KEYS = {t: d["key"] for t, d in _SPECS.items()}
TOMBSTONE_KEY_EXPRS = {t: d["exprs"] for t, d in _SPECS.items()}
#: Tables that have been put under tracking by migration 037 (``app_settings`` was done by 034).
TRACKED_BY_037 = tuple(_SPECS)


def register_config_specs(registry: ReplicableRegistry) -> None:
    for table, d in _SPECS.items():
        if registry.get(table) is not None:
            continue
        kwargs: dict[str, Any] = {}
        if "to" in d:
            kwargs["to_wire"], kwargs["from_wire"] = d["to"], d["from"]
        registry.register(ReplicableSpec(
            table, d["key"], depends_on=d["deps"], node_local_fields=d.get("node_local", frozenset()),
            secret_fields=d.get("secret", frozenset()), **kwargs))


__all__ = ["NATURAL_KEYS", "PAYLOAD_COLUMNS", "TOMBSTONE_KEY_EXPRS", "TRACKED_BY_037", "UnresolvedParent",
           "observatory_id", "observatory_ref", "pier_id", "pier_ref", "register_config_specs"]
