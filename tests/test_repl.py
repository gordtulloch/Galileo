# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""REPL — replication support (TC-REPL-010 .. 080) and the loopback guard (TC-PROF-130, TC-GUIDE-100).

Change tracking is done by database triggers (migration 034), so these tests write through every
path the application uses: the settings store, ``save`` and a bulk ``update``."""

import importlib
import pkgutil

import pytest

from galileo import settings_store
from galileo.net import LoopbackGuard
from galileo.replication import SyncStore, busy, registry, tracking
from galileo.session_exec import RunState, SessionExecutor

KEY = {"namespace": "imaging", "key": "gain", "scope": ""}


def _row(namespace, key, scope=""):
    from galileo.library.models.app_setting import AppSettingRecord as R
    return R.get((R.namespace == namespace) & (R.key == key) & (R.scope == scope))


@pytest.fixture(autouse=True)
def _spoke():
    tracking.configure(is_master=lambda: False)
    yield
    tracking.configure(is_master=lambda: False)


@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_every_write_path_marks_the_row_dirty_and_keeps_base_rev(settings_db):
    """REPL-010: a local write sets dirty and modified through the settings store, save and a bulk
    update alike; base_rev is the revision the edit started from and survives a second edit."""
    from galileo.library.models.app_setting import AppSettingRecord as R
    settings_store.set_setting("imaging", "gain", 100)
    r = _row("imaging", "gain")
    assert (r.dirty, r.rev, r.base_rev) == (1, 0, 0) and r.modified > 1e9
    tracking.configure(is_master=lambda: True)
    assert tracking.mark_clean("app_settings", KEY, tracking.commit_rev("app_settings"))
    r = _row("imaging", "gain")
    assert (r.dirty, r.rev, r.base_rev) == (0, 1, 1)
    settings_store.set_setting("imaging", "gain", 120)                          # upsert path
    r = _row("imaging", "gain")
    assert (r.dirty, r.base_rev) == (1, 1)
    r.value = "130"
    r.save()                                                                    # ORM path
    assert _row("imaging", "gain").base_rev == 1                                # still the original base
    tracking.mark_clean("app_settings", KEY, 5)
    R.update(value="140").where(R.key == "gain").execute()                      # bulk update path
    r = _row("imaging", "gain")
    assert (r.dirty, r.base_rev) == (1, 5)
    assert [d["key"] for d in tracking.dirty_rows("app_settings")] == ["gain"]
    tracking.mark_clean("app_settings", KEY, 6)
    settings_store.set_setting("imaging", "gain", 140)                          # same value: not a change
    assert _row("imaging", "gain").dirty == 0


@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_applying_received_rows_does_not_mark_them_dirty(settings_db):
    """REPL-010: rows written inside tracking.applying() (a bulk apply from the Master) stay clean
    and leave no tombstone, and the suppression ends with the block even on error."""
    from galileo.library.models.app_setting import AppSettingRecord as R
    with tracking.applying():
        R.insert(namespace="guiding", key="aggr", scope="", value="7", rev=9, base_rev=9).execute()
    r = _row("guiding", "aggr")
    assert (r.dirty, r.rev) == (0, 9)
    with pytest.raises(RuntimeError), tracking.applying():
        R.delete().where(R.key == "aggr").execute()
        raise RuntimeError
    assert tracking.tombstones("app_settings") == []
    settings_store.set_setting("guiding", "other", 1)                           # tracking is back on
    assert _row("guiding", "other").dirty == 1


@pytest.mark.requirement("TC-REPL-020")
@pytest.mark.priority("MVP")
def test_tc_repl_020_deletion_leaves_a_tombstone_until_released(settings_db):
    """REPL-020: deleting a row records table, natural key, revision and time; it is kept until released."""
    settings_store.set_setting("planning", "min_alt", 20, scope="pier1")
    tracking.configure(is_master=lambda: True)
    tracking.mark_clean("app_settings", {"namespace": "planning", "key": "min_alt", "scope": "pier1"},
                        tracking.commit_rev("app_settings"))
    assert settings_store.delete_setting("planning", "min_alt", scope="pier1")
    (t,) = tracking.tombstones("app_settings")
    assert t["natural_key"] == ["planning", "min_alt", "pier1"] and t["rev"] == 1 and t["deleted_at"] > 1e9
    assert tracking.tombstones("app_settings", after_id=t["id"]) == []
    assert tracking.release_tombstones("app_settings", t["id"]) == 1 and tracking.tombstones("app_settings") == []


def _spec(name, deps=(), key=("id",)):
    def ident(row):
        return row
    return registry.ReplicableSpec(name, key, ident, ident, depends_on=deps)


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_registry_orders_by_dependency_and_takes_later_tables():
    """REPL-030: specs() returns dependencies first; a table registered later (a plugin's) is included;
    a table without a natural key, a duplicate, a cycle and a missing dependency are refused."""
    try:
        registry.register(_spec("zz_child", ("zz_parent",)))
        registry.register(_spec("zz_parent"))
        names = [s.table for s in registry.specs()]
        assert names.index("zz_parent") < names.index("zz_child") and "app_settings" in names
        with pytest.raises(registry.RegistryError):
            registry.register(_spec("zz_parent"))
        with pytest.raises(registry.RegistryError):
            registry.register(_spec("zz_bad", key=()))
        registry.register(_spec("zz_a", ("zz_b",)))
        registry.register(_spec("zz_b", ("zz_a",)))
        with pytest.raises(registry.RegistryError, match="cycle"):
            registry.specs()
        registry.unregister("zz_a")
        registry.unregister("zz_b")
        registry.register(_spec("zz_orphan", ("zz_missing",)))
        with pytest.raises(registry.RegistryError, match="not registered"):
            registry.specs()
    finally:
        for n in ("zz_child", "zz_parent", "zz_a", "zz_b", "zz_orphan", "zz_bad"):
            registry.unregister(n)


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_settings_wire_round_trip_and_node_local_rows_are_excluded(settings_db):
    """REPL-030: app_settings converts to and from the wire; the link's own settings never replicate."""
    settings_store.set_setting("imaging", "bin", {"x": 2})
    spec = registry.get("app_settings")
    wire = spec.to_wire(tracking.dirty_rows("app_settings")[0])
    assert wire["value"] == {"x": 2} and spec.from_wire(wire)["value"] == '{"x": 2}'
    assert spec.key_of(spec.from_wire(wire)) == {"namespace": "imaging", "key": "bin", "scope": ""}
    assert spec.exclude_row({"namespace": "connect_link"}) and not spec.exclude_row({"namespace": "imaging"})


@pytest.mark.requirement("TC-REPL-040")
@pytest.mark.priority("MVP")
def test_tc_repl_040_every_table_is_registered_or_declared():
    """REPL-040: a table that is neither replicable nor declared not-configuration (nor, visibly,
    pending registration) fails here, so adding a configuration table forces a decision."""
    import galileo.library.models as models
    from galileo.library.models.base import BaseModel
    for m in pkgutil.iter_modules(models.__path__):
        importlib.import_module("galileo.library.models." + m.name)

    def walk(c):
        for s in c.__subclasses__():
            yield s
            yield from walk(s)
    tables = {c._meta.table_name for c in walk(BaseModel)}
    assert registry.unregistered_configuration_tables(tables) == set()
    assert registry.unregistered_configuration_tables(tables | {"brand_new_settings"}) == {"brand_new_settings"}
    assert {s.table for s in registry.specs()} <= tables    # every spec names a real table
    assert {"piers", "device_configs", "solver_settings"} <= {s.table for s in registry.specs()}


@pytest.mark.requirement("TC-REPL-050")
@pytest.mark.priority("MVP")
def test_tc_repl_050_settings_changed_event_reaches_subscribers():
    """REPL-050: SettingsChangedEvent names the tables and is delivered on the bus."""
    from galileo.bus import EventBus, SettingsChangedEvent
    bus, seen = EventBus(), []
    bus.subscribe(SettingsChangedEvent, lambda e: seen.append(e.tables))
    bus.publish(SettingsChangedEvent("replication", tables=["app_settings"]))
    assert seen == [["app_settings"]]


@pytest.mark.requirement("TC-REPL-060")
@pytest.mark.priority("MVP")
def test_tc_repl_060_busy_while_a_session_runs_and_on_idle_fires_once():
    """REPL-060: is_busy() is true from the start of a session until it ends and on_idle waits for it."""
    ex = SessionExecutor.__new__(SessionExecutor)
    ex.log, ex.errors, ex.name, ex._on_progress = [], [], "t", None
    fired = []
    assert not busy.is_busy()
    busy.on_idle(lambda: fired.append("now"))                    # idle: immediately
    ex._set_state(RunState.RUNNING)
    assert busy.is_busy()
    busy.on_idle(lambda: fired.append("later"))
    ex._set_state(RunState.PAUSED)
    assert busy.is_busy() and fired == ["now"]
    ex._set_state(RunState.COMPLETED)
    assert not busy.is_busy() and fired == ["now", "later"]
    busy.tracker.acquire("calibration")                           # a calibration run counts too
    assert busy.is_busy()
    busy.tracker.release("calibration")
    ex._set_state(RunState.STOPPED)
    assert fired == ["now", "later"]                               # one-shot


@pytest.mark.requirement("TC-REPL-070")
@pytest.mark.priority("MVP")
def test_tc_repl_070_sync_store_queues_snapshots_reports_transfers_and_state(settings_db):
    """REPL-070: the core-owned sync tables are reachable through one interface."""
    s = SyncStore(clock=lambda: 1000.0)
    a = s.outbox_add("n1", "app_settings", ["a", "b", ""], "upsert", {"v": 1}, rev=3)
    s.outbox_add("n2", "app_settings", ["x", "y", ""], "delete", None)
    claimed = s.outbox_claim("n1")
    assert [c["id"] for c in claimed] == [a] and claimed[0]["natural_key"] == ["a", "b", ""]
    assert s.outbox_claim("n1") == []                                  # claimed once
    assert s.outbox_release("n1") == 1 and len(s.outbox_claim("n1")) == 1
    assert s.outbox_ack([a]) == 1 and s.outbox_claim("n1") == []
    i = s.inbox_add("n1", "app_settings", ["a", "b", ""], "upsert", {"v": 2})
    assert [r["id"] for r in s.inbox_pending()] == [i]
    s.inbox_mark([i], "applied")
    assert s.inbox_pending() == []
    s.snapshot_save("run1", {"rows": [1]}, "before")
    assert s.snapshot_get("run1")[0]["data"] == {"rows": [1]} and s.snapshot_delete("run1") == 1
    s.report_start("run1", "n1")
    s.report_finish("run1", "ok", {"applied": 3})
    assert s.reports()[0]["summary"] == {"applied": 3} and s.reports()[0]["outcome"] == "ok"
    assert s.transfer_add("n1", "ab" * 32, "pull", "f.fits", 10, priority=1)
    assert not s.transfer_add("n1", "ab" * 32, "pull")                 # once per hash
    s.transfer_add("n1", "cd" * 32, "pull", priority=5)
    nxt = s.transfer_next("n1", "pull")
    assert nxt["sha256"] == "cd" * 32
    s.transfer_set(nxt["id"], "done")
    assert s.transfer_next("n1", "pull")["sha256"] == "ab" * 32
    s.peer_set("n1", "last_rev", 42)
    assert s.peer_get("n1", "last_rev") == 42 and s.peer_get("n1", "nope", "d") == "d"
    s.peer_set("n1", "last_rev", 43)
    s.peer_forget("n1")
    assert s.peer_get("n1", "last_rev") is None and s.transfer_next("n1", "pull") is None


@pytest.mark.requirement("TC-REPL-080")
@pytest.mark.priority("MVP")
def test_tc_repl_080_only_the_master_issues_revisions_serially(settings_db):
    """REPL-080: revisions are issued per table in sequence, and a spoke refuses."""
    with pytest.raises(tracking.NotMasterError):
        tracking.commit_rev("app_settings")
    tracking.configure(is_master=lambda: True)
    assert [tracking.commit_rev("app_settings") for _ in range(3)] == [1, 2, 3]
    assert tracking.commit_rev("other_table") == 1 and tracking.current_rev("app_settings") == 3
    with pytest.raises(ValueError):
        tracking.commit_rev("x; DROP TABLE app_settings")


@pytest.mark.requirement("TC-PROF-130")
@pytest.mark.priority("MVP")
@pytest.mark.parametrize("address,expected", [
    ("localhost", True), ("LOCALHOST:7624", True), ("127.0.0.1", True), ("127.1.2.3", True),
    ("::1", True), ("[::1]:4400", True), ("0.0.0.0", True), ("http://localhost:11111/", True),  # noqa: S104
    ("pi.localhost", True),
    ("192.168.1.20", False), ("stellarmate.local", False), ("10.0.0.5:7624", False),
    ("http://192.168.1.2:11111", False), ("", False),
])
def test_tc_prof_130_loopback_guard(address, expected):
    """PROF-130 / GUIDE-100: only addresses that mean this machine are refused; names are not resolved."""
    assert LoopbackGuard.is_loopback(address) is expected


# -- the equipment tables (linked by database ids) ---------------------------------------------
def _equipment():
    from galileo.library.models import (
        DeviceConfigRecord, ObservatoryRecord, PierRecord, SolverSettingsRecord,
    )
    obs = ObservatoryRecord.create(name="Home")
    pier = PierRecord.create(observatory=obs, name="Pier 1")
    dev = DeviceConfigRecord.create(pier=pier, category="camera", slot="primary", driver="d", server="s", port=7624)
    return obs, pier, dev, SolverSettingsRecord.create(pier=pier, executable="C:/astap.exe", nova_api_key="SECRET")


def _clean_all():
    with tracking.applying():
        for t in ("observatories", "piers", "device_configs", "solver_settings"):
            from galileo.library.models.base import db
            db.execute_sql(f"UPDATE {t} SET dirty = 0")  # noqa: S608 - identifiers are constants or validated


@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_equipment_rows_are_tracked_but_runtime_focuser_position_is_not(settings_db):
    """REPL-010: equipment rows are marked dirty by ORM writes; a focuser's moving position is runtime
    state and does not mark the device row dirty, a real setting change does."""
    _, _, dev, _ = _equipment()
    assert {d["name"] for d in tracking.dirty_rows("piers")} == {"Pier 1"}
    _clean_all()
    dev.focuser_position = 12345
    dev.save()
    assert tracking.dirty_rows("device_configs") == []
    dev.port = 7625
    dev.save()
    assert [d["port"] for d in tracking.dirty_rows("device_configs")] == [7625]


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_equipment_keys_are_names_not_ids_and_local_fields_stay_home(settings_db):
    """REPL-030: a device row is keyed by observatory, pier, category and slot; node-local paths and
    secrets are not on the wire; the key round-trips to the local row; a missing parent is refused."""
    _, pier, dev, _ = _equipment()
    spec = registry.get("device_configs")
    row = tracking.dirty_rows("device_configs")[0]
    wire = spec.to_wire(row)
    assert wire["key"] == ["Home", "Pier 1", "camera", "primary"] and "pier_id" not in wire["fields"]
    assert "focuser_position" not in wire["fields"] and wire["fields"]["driver"] == "d"
    assert spec.key_of(row) == {"observatory": "Home", "pier": "Pier 1", "category": "camera", "slot": "primary"}
    assert spec.find_local(wire["key"])["id"] == dev.id
    assert spec.from_wire(wire)["pier_id"] == pier.id
    sw = registry.get("solver_settings").to_wire(tracking.dirty_rows("solver_settings")[0])
    assert "executable" not in sw["fields"] and "nova_api_key" not in sw["fields"] and "backend" in sw["fields"]
    elsewhere = {**wire, "key": ["Other", "Pier 1", "camera", "primary"]}
    with pytest.raises(registry.RegistryError):
        spec.from_wire(elsewhere)
    assert spec.find_local(["Other", "Pier 1", "camera", "primary"]) is None
    order = [s.table for s in registry.specs()]
    assert order.index("observatories") < order.index("piers") < order.index("device_configs")


@pytest.mark.requirement("TC-REPL-020")
@pytest.mark.priority("MVP")
def test_tc_repl_020_equipment_tombstones_carry_names_and_a_cascade_leaves_only_the_parents(settings_db):
    """REPL-020: deleting a device leaves a name-keyed tombstone; deleting its pier leaves the pier's
    tombstone and none for the rows removed with it."""
    _, pier, dev, _ = _equipment()
    dev.delete_instance()
    assert [t["natural_key"] for t in tracking.tombstones("device_configs")] == [["Home", "Pier 1", "camera", "primary"]]
    from galileo.library.models import DeviceConfigRecord
    DeviceConfigRecord.create(pier=pier, category="mount", slot="primary", driver="d", server="s", port=1)
    pier.delete_instance(recursive=False)
    assert [t["natural_key"] for t in tracking.tombstones("piers")] == [["Home", "Pier 1"]]
    assert len(tracking.tombstones("device_configs")) == 1                       # the cascade added none


@pytest.mark.requirement("TC-REPL-080")
@pytest.mark.priority("MVP")
def test_tc_repl_080_deletions_get_revisions_and_are_released_only_when_acknowledged(settings_db):
    """REPL-020 / REPL-080: on the Master a tombstone is committed with a revision from the table's
    counter, is offered to spokes asking for changes since an earlier revision, can be recorded for a
    deletion arbitrated from a node, and is released only up to the acknowledged revision."""
    settings_store.set_setting("a", "k", 1)
    tracking.configure(is_master=lambda: True)
    tracking.mark_clean("app_settings", {"namespace": "a", "key": "k", "scope": ""}, tracking.commit_rev("app_settings"))
    settings_store.delete_setting("a", "k")
    assert tracking.tombstones("app_settings", committed_after_rev=0) == []            # not committed yet
    assert tracking.commit_tombstones("app_settings") == 1
    (t,) = tracking.tombstones("app_settings", committed_after_rev=0)
    assert t["rev"] == 2 and t["committed"] == 1
    assert tracking.tombstones("app_settings", committed_after_rev=2) == []            # a spoke at 2 has seen it
    tracking.record_tombstone("app_settings", ["a", "z", ""], tracking.commit_rev("app_settings"))
    assert len(tracking.tombstones("app_settings", committed_after_rev=0)) == 2
    assert tracking.release_committed("app_settings", 2) == 1 and len(tracking.tombstones("app_settings")) == 1
    assert tracking.drop_tombstone(tracking.tombstones("app_settings")[0]["id"]) and tracking.tombstones("app_settings") == []
    tracking.configure(is_master=lambda: False)
    with pytest.raises(tracking.NotMasterError):
        tracking.commit_tombstones("app_settings")
    with pytest.raises(tracking.NotMasterError):
        tracking.record_tombstone("app_settings", ["x"], 1)
