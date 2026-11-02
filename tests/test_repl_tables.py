# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""REPL — the configuration tables are replicable (TC-REPL-010/020/030/040 for Observatories, Piers, devices and
the rest). ``test_repl.py`` covers the mechanism on ``app_settings``; these tests cover what a table with parents
needs: tracking, tombstone keys made of names, and a wire form that survives different ids on another node."""

import json

import pytest

from galileo.library.models.base import db
from galileo.replication import registry as global_registry
from galileo.replication import register_defaults, tracking
from galileo.replication.registry import PENDING_REGISTRATION
from galileo.replication.specs import (
    NATURAL_KEYS,
    TRACKED_BY_037,
    UnresolvedParent,
    observatory_id,
)


def _one(sql, *params):
    return db.execute_sql(sql, params).fetchone()


@pytest.fixture
def farm(settings_db):
    """One Observatory with two Piers, a tube, a camera, solver settings (with a secret) and a template."""
    register_defaults()
    x = db.execute_sql
    x("INSERT INTO observatories (name, latitude, longitude, timezone) VALUES ('Home', 45.0, -75.0, 'America/Toronto')")
    oid = _one("SELECT id FROM observatories WHERE name = 'Home'")[0]
    x("INSERT INTO piers (observatory_id, name, connect_on_startup) VALUES (?, 'Pier A', 0)", (oid,))
    x("INSERT INTO piers (observatory_id, name, connect_on_startup) VALUES (?, 'Pier B', 0)", (oid,))
    pa = _one("SELECT id FROM piers WHERE name = 'Pier A'")[0]
    x("INSERT INTO optical_tubes (pier_id, position, name, focal_length_mm, aperture_mm, optical_system, "
      "image_reversed, image_inverted, associated_devices) VALUES (?, 1, 'RC8', 1600, 200, 'RC', 0, 0, '[]')", (pa,))
    x("INSERT INTO device_configs (pier_id, category, slot, driver, server, port, device_name, "
      "bayer_pattern, focuser_position) VALUES (?, 'camera', '1', 'indi', 'indi.lan', 7624, 'ZWO', 'RGGB', 5120)", (pa,))
    x("INSERT INTO solver_settings (pier_id, backend, nova_api_key) VALUES (?, 'astap', 'SECRET-KEY')", (pa,))
    x("INSERT INTO session_templates (name, blocks_json) VALUES ('M42', '[]')")
    return {"oid": oid, "pa": pa}


@pytest.mark.requirement("TC-REPL-040")
@pytest.mark.priority("MVP")
def test_tc_repl_040_every_configuration_table_but_the_scheduler_is_registered_and_tracked(settings_db):
    """REPL-040 / REPL-010: all eleven configuration tables carry the tracking columns and triggers; the only
    table still pending is the scheduler's."""
    register_defaults()
    assert {"scheduler_jobs"} == PENDING_REGISTRATION and set(global_registry.pending(db.get_tables())) == {"scheduler_jobs"}
    triggers = {r[0] for r in db.execute_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()}
    for table in TRACKED_BY_037:
        assert set(tracking.TRACKED_COLUMNS) <= {c.name for c in db.get_columns(table)}, table
        assert {f"repl_{table}_{s}" for s in ("ins", "upd", "del")} <= triggers, table
        assert global_registry.get(table).natural_key == NATURAL_KEYS[table]
    assert global_registry.unclassified_tables(db.get_tables()) == []
    order = [s.table for s in global_registry.specs()]
    assert order.index("observatories") < order.index("piers") < order.index("optical_tubes")
    assert order.index("piers") < order.index("device_configs")


@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_edits_to_configuration_rows_are_tracked(farm):
    """REPL-010: a new row is dirty; after a sync an edit sets dirty and keeps the base revision; applying
    replicated rows is not an edit."""
    assert _one("SELECT dirty, modified FROM piers WHERE name = 'Pier A'")[0] == 1
    tracking.mark_clean("piers", "name = ?", ("Pier A",), rev=9)
    assert _one("SELECT dirty, rev FROM piers WHERE name = 'Pier A'") == (0, 9)
    db.execute_sql("UPDATE piers SET connect_on_startup = 1 WHERE name = 'Pier A'")
    assert _one("SELECT dirty, base_rev FROM piers WHERE name = 'Pier A'") == (1, 9)
    tracking.mark_clean("optical_tubes", "name = ?", ("RC8",), rev=4)
    db.execute_sql("UPDATE optical_tubes SET focal_length_mm = 1600 WHERE name = 'RC8'")        # unchanged value
    assert _one("SELECT dirty FROM optical_tubes WHERE name = 'RC8'")[0] == 0
    with tracking.apply_mode():
        db.execute_sql("UPDATE optical_tubes SET focal_length_mm = 1700 WHERE name = 'RC8'")
    assert _one("SELECT dirty FROM optical_tubes WHERE name = 'RC8'")[0] == 0


@pytest.mark.requirement("TC-REPL-020")
@pytest.mark.priority("MVP")
def test_tc_repl_020_a_deleted_row_is_named_by_its_parents_not_by_ids(farm):
    """REPL-020: a tombstone's key is made of names (Observatory, Pier), so another node can find the row
    although its ids differ."""
    db.execute_sql("DELETE FROM optical_tubes WHERE name = 'RC8'")
    db.execute_sql("DELETE FROM device_configs WHERE category = 'camera'")
    db.execute_sql("DELETE FROM piers WHERE name = 'Pier B'")
    db.execute_sql("DELETE FROM session_templates WHERE name = 'M42'")
    keys = {(t["table"], json.dumps(t["key"])) for t in tracking.tombstones()}
    assert ("optical_tubes", json.dumps([["Home", "Pier A"], 1])) in keys
    assert ("device_configs", json.dumps([["Home", "Pier A"], "camera", "1"])) in keys
    assert ("piers", json.dumps(["Home", "Pier B"])) in keys
    assert ("session_templates", json.dumps(["M42"])) in keys


@pytest.mark.requirement("TC-REPL-020")
@pytest.mark.priority("MVP")
def test_tc_repl_020_deleting_an_observatory_cascades_without_error(farm):
    """REPL-020: removing an Observatory removes its Piers and their rows; whatever tombstones that leaves
    include the Observatory's own, named by its name."""
    db.execute_sql("PRAGMA foreign_keys = ON")
    db.execute_sql("DELETE FROM observatories WHERE name = 'Home'")
    assert ("observatories", ["Home"]) in [(t["table"], t["key"]) for t in tracking.tombstones()]
    assert _one("SELECT COUNT(*) FROM piers")[0] == 0


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_wire_form_names_parents_and_leaves_secrets_and_machine_details_behind(farm):
    """REPL-030: ids become names on the wire; the solver web key is withheld by default; a retained focuser
    position and program paths stay on their machine."""
    pier = global_registry.get("piers")
    row = {"id": farm["pa"], "observatory_id": farm["oid"], "name": "Pier A", "connect_on_startup": 0,
           "rev": 3, "modified": 1.5, "dirty": 1, "base_rev": 2}
    wire = pier.wire(row)
    assert wire == {"observatory": "Home", "name": "Pier A", "connect_on_startup": 0, "rev": 3, "modified": 1.5}
    assert pier.key_of(wire) == '["Home", "Pier A"]'
    cols = [c[1] for c in db.execute_sql("PRAGMA table_info(solver_settings)").fetchall()]
    solver = dict(zip(cols, _one("SELECT * FROM solver_settings"), strict=True))
    solver.update(executable="C:/astap/astap.exe", tetra3_database="/data/t3.npz")
    sw = global_registry.get("solver_settings").wire(solver)
    assert "nova_api_key" not in sw and "executable" not in sw and "tetra3_database" not in sw
    assert sw["pier"] == ["Home", "Pier A"] and sw["backend"] == "astap"
    assert global_registry.get("solver_settings").wire(solver, include_secrets=True)["nova_api_key"] == "SECRET-KEY"
    cfg_cols = [c[1] for c in db.execute_sql("PRAGMA table_info(device_configs)").fetchall()]
    cfg = global_registry.get("device_configs").wire(dict(zip(cfg_cols, _one("SELECT * FROM device_configs"), strict=True)))
    assert "focuser_position" not in cfg and cfg["server"] == "indi.lan" and cfg["pier"] == ["Home", "Pier A"]


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_rows_survive_a_round_trip_into_a_database_with_different_ids(farm):
    """REPL-030: the whole configuration, taken to wire form and applied (in dependency order, with tracking
    suspended) to a database where the ids differ, arrives intact and clean."""
    wires = []
    for spec in global_registry.specs():
        if spec.table == "app_settings":
            continue
        cols = [c[1] for c in db.execute_sql(f"PRAGMA table_info({spec.table})").fetchall()]
        for r in db.execute_sql(f"SELECT * FROM {spec.table}").fetchall():  # noqa: S608
            wires.append((spec, spec.wire(dict(zip(cols, r, strict=True)))))
    assert {s.table for s, _ in wires} >= {"observatories", "piers", "optical_tubes", "device_configs",
                                            "solver_settings", "session_templates"}
    for table in reversed(TRACKED_BY_037):
        db.execute_sql(f"DELETE FROM {table}")  # noqa: S608
    db.execute_sql("INSERT INTO observatories (name) VALUES ('Padding 1'), ('Padding 2')")      # shift the ids
    from galileo.replication.registry import ReplicableSpec
    with tracking.apply_mode():
        for spec, wire in wires:
            assert isinstance(spec, ReplicableSpec)
            row = spec.from_wire({k: v for k, v in wire.items() if k not in ("rev", "modified")})
            cols = ", ".join(row)
            db.execute_sql(f"INSERT INTO {spec.table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))  # noqa: S608
    assert observatory_id("Home") != farm["oid"]                                # different ids on this node
    assert _one("SELECT focal_length_mm FROM optical_tubes WHERE name = 'RC8'")[0] == 1600
    assert _one("SELECT server, port FROM device_configs")[0:2] == ("indi.lan", 7624)
    assert _one("SELECT backend, nova_api_key FROM solver_settings")[0] == "astap"
    assert _one("SELECT blocks_json FROM session_templates WHERE name = 'M42'")[0] == "[]"
    assert _one("SELECT COUNT(*) FROM piers p JOIN observatories o ON o.id = p.observatory_id WHERE o.name = 'Home'")[0] == 2
    assert _one("SELECT COUNT(*) FROM piers WHERE dirty = 1")[0] == 0           # applying is not an edit


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_a_row_whose_parent_is_missing_is_refused_not_misfiled(settings_db):
    """REPL-030: from_wire raises when the Observatory or Pier it names is not here."""
    register_defaults()
    with pytest.raises(UnresolvedParent):
        global_registry.get("piers").from_wire({"observatory": "Nowhere", "name": "X"})
    with pytest.raises(UnresolvedParent):
        global_registry.get("optical_tubes").from_wire({"pier": ["Nowhere", "X"], "position": 1})
    with pytest.raises(UnresolvedParent):
        global_registry.get("optical_tubes").from_wire({"pier": "not a ref", "position": 1})
    with pytest.raises(UnresolvedParent):
        observatory_id("Nowhere")


@pytest.mark.requirement("TC-REPL-070")
@pytest.mark.priority("MVP")
def test_tc_repl_070_migration_037_survives_a_replay(settings_db):
    """REPL-070: replaying migration 037 over existing triggers and columns changes nothing and does not fail."""
    from galileo.library.database import run_migrations
    db.execute_sql("DELETE FROM migratehistory WHERE name = '037_track_configuration_tables'")
    run_migrations()
    db.execute_sql("INSERT INTO session_templates (name, blocks_json) VALUES ('again', '[]')")
    assert _one("SELECT dirty FROM session_templates WHERE name = 'again'")[0] == 1
