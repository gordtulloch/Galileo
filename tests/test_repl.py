# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""REPL — replication support (TC-REPL-*), plus the loopback check it shares with PROF-130 / GUIDE-100
(TC-PROF-130, TC-GUIDE-100). Real SQLite database, migrated by ``settings_db``."""

import json

import pytest

from galileo import settings_store as store
from galileo.bus import EventBus
from galileo.library.models.base import db
from galileo.net import is_loopback, loopback_message
from galileo.replication import (
    NotMasterError,
    RegistryError,
    ReplicableRegistry,
    ReplicableSpec,
    RevisionIssuer,
    SessionBusy,
    SettingsChanged,
    SyncStore,
    apply_mode,
    publish_settings_changed,
    register_defaults,
)
from galileo.replication import registry as global_registry
from galileo.replication import tracking
from galileo.replication.registry import NOT_CONFIGURATION, PENDING_REGISTRATION


def _row(namespace="ns", key="k"):
    cur = db.execute_sql("SELECT namespace, key, scope, value, modified, rev, dirty, base_rev FROM app_settings "
                         "WHERE namespace = ? AND key = ?", (namespace, key))
    r = cur.fetchone()
    return None if r is None else dict(zip(("namespace", "key", "scope", "value", "modified", "rev", "dirty",
                                            "base_rev"), r, strict=True))


# ---- REPL-010 / 020 -------------------------------------------------------------------------
@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_every_ordinary_write_is_tracked(settings_db):
    """REPL-010: a write sets dirty, stamps modified and keeps the base_rev the edit started from — for the
    settings store's upserts, which bypass the ORM's save; an identical rewrite is not an edit."""
    assert store.set_setting("ns", "k", 1)
    r = _row()
    assert r["dirty"] == 1 and r["modified"] > 1e9 and r["rev"] == 0 and r["base_rev"] == 0
    tracking.mark_clean("app_settings", "namespace = ? AND key = ?", ("ns", "k"), rev=7)
    r = _row()
    assert (r["dirty"], r["rev"], r["base_rev"]) == (0, 7, 7)
    store.set_setting("ns", "k", 1)                                  # same value: not a local edit
    assert _row()["dirty"] == 0
    store.set_setting("ns", "k", 2)
    r = _row()
    assert r["dirty"] == 1 and r["base_rev"] == 7 and json.loads(r["value"]) == 2
    store.set_setting("ns", "k", 3)                                  # a second edit keeps the original base
    assert _row()["base_rev"] == 7
    store.set_namespace("ns2", {"a": 1, "b": 2})
    assert {_row("ns2", k)["dirty"] for k in "ab"} == {1}


@pytest.mark.requirement("TC-REPL-010")
@pytest.mark.priority("MVP")
def test_tc_repl_010_applying_replicated_rows_is_not_a_local_edit_and_failure_rolls_back(settings_db):
    """REPL-010: while the sync engine applies rows, tracking is suspended; if the apply fails the whole
    bulk and the suspension are rolled back."""
    with apply_mode():
        store.set_setting("ns", "from_master", "x")
    assert _row("ns", "from_master")["dirty"] == 0
    store.set_setting("ns", "local", "y")
    assert _row("ns", "local")["dirty"] == 1
    with pytest.raises(RuntimeError), apply_mode():
        store.set_setting("ns", "half", "z")
        raise RuntimeError("apply failed")
    assert _row("ns", "half") is None
    store.set_setting("ns", "after", "w")
    assert _row("ns", "after")["dirty"] == 1                         # tracking is back on
    db.execute_sql("UPDATE repl_state SET apply_mode = 1")           # as if the process died mid-apply
    tracking.reset_apply_mode()
    store.set_setting("ns", "after2", "w")
    assert _row("ns", "after2")["dirty"] == 1


@pytest.mark.requirement("TC-REPL-020")
@pytest.mark.priority("MVP")
def test_tc_repl_020_a_delete_leaves_a_tombstone_until_released(settings_db):
    """REPL-020: deleting a row leaves a tombstone (table, natural key, revision, time) until the sync owner
    releases it; a delete applied from a peer leaves none."""
    store.set_setting("ns", "gone", 1, scope="pier1")
    tracking.mark_clean("app_settings", "key = ?", ("gone",), rev=4)
    store.delete_setting("ns", "gone", scope="pier1")
    (t,) = tracking.tombstones()
    assert (t["table"], t["key"], t["rev"]) == ("app_settings", ["ns", "gone", "pier1"], 4) and t["deleted_at"] > 1e9
    with apply_mode():
        store.set_setting("ns", "remote", 1)
        store.delete_setting("ns", "remote")
    assert len(tracking.tombstones()) == 1
    assert tracking.tombstones("other") == [] and tracking.tombstones(since_id=t["id"]) == []
    assert SyncStore().release_tombstones("app_settings", t["id"]) == 1 and tracking.tombstones() == []


# ---- REPL-030 / 040 -------------------------------------------------------------------------
@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_registry_orders_by_dependency_and_applies_declared_filters():
    """REPL-030: specs() returns tables after the ones they depend on; node-local and secret fields are
    withheld from the wire form; a later (plugin) table is picked up with no change to the consumer."""
    reg = ReplicableRegistry()
    reg.register(ReplicableSpec("piers", ("name",), depends_on=("observatories",)))
    reg.register(ReplicableSpec("observatories", ("name",)))
    reg.register(ReplicableSpec("device_x", ("pier", "slot"), depends_on=("piers",),
                                node_local_fields=frozenset({"serial_port"}), secret_fields=frozenset({"password"}),
                                to_wire=lambda r: {**r, "converted": True}))
    assert [s.table for s in reg.specs()] == ["observatories", "piers", "device_x"]
    spec = reg.get("device_x")
    row = {"id": 5, "pier": "p1", "slot": 2, "serial_port": "COM3", "password": "hunter2", "dirty": 1,
           "base_rev": 0, "rev": 3}
    assert spec.wire(row) == {"pier": "p1", "slot": 2, "rev": 3, "converted": True}
    assert "password" in spec.wire(row, include_secrets=True) and spec.key_of(row) == '["p1", 2]'
    reg.register(ReplicableSpec("plugin_table", ("k",)))
    assert "plugin_table" in [s.table for s in reg.specs()]
    for bad in (ReplicableSpec("x", ()), ReplicableSpec("fitsfile", ("id",)), ReplicableSpec("piers", ("n",))):
        with pytest.raises(RegistryError):
            reg.register(bad)
    reg.register(ReplicableSpec("orphan", ("k",), depends_on=("missing",)))
    with pytest.raises(RegistryError):
        reg.specs()


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_dependency_cycles_are_refused():
    """REPL-030: a dependency cycle is an error, not a hang."""
    reg = ReplicableRegistry()
    reg.register(ReplicableSpec("a", ("k",), depends_on=("b",)))
    reg.register(ReplicableSpec("b", ("k",), depends_on=("a",)))
    with pytest.raises(RegistryError):
        reg.specs()


@pytest.mark.requirement("TC-REPL-030")
@pytest.mark.priority("MVP")
def test_tc_repl_030_app_settings_is_registered_and_node_local_namespaces_stay_home():
    """REPL-030: core registers app_settings with its natural key; a node's own namespaces never replicate."""
    reg = ReplicableRegistry()
    register_defaults(reg)
    spec = reg.get("app_settings")
    assert spec.natural_key == ("namespace", "key", "scope")
    assert spec.replicates({"namespace": "autofocus"}) and spec.replicates({"namespace": "plugin.kasa"})
    assert not spec.replicates({"namespace": "connect_link"})
    assert not spec.replicates({"namespace": "plugin.NodeConnect"})


@pytest.mark.requirement("TC-REPL-040")
@pytest.mark.priority("MVP")
def test_tc_repl_040_every_table_is_registered_not_configuration_or_visibly_pending(settings_db):
    """REPL-040: the database holds no table that is none of registered, not-configuration or pending
    registration, so "complete" stays true as Galileo grows; the pending list is the visible to-do."""
    register_defaults()
    tables = db.get_tables()
    assert global_registry.unclassified_tables(tables) == [], \
        "a new table must be registered for replication or added to NOT_CONFIGURATION in galileo/replication/registry.py"
    assert global_registry.unclassified_tables(["brand_new_settings"]) == ["brand_new_settings"]
    assert not (PENDING_REGISTRATION & NOT_CONFIGURATION)
    assert "app_settings" not in PENDING_REGISTRATION
    assert "app_settings" in {s.table for s in global_registry.specs()}
    assert set(global_registry.pending(tables)) == set(PENDING_REGISTRATION) & set(tables)


@pytest.mark.requirement("TC-REPL-040")
@pytest.mark.priority("MVP")
def test_tc_repl_040_tracking_columns_exist_for_every_registered_table(settings_db):
    """REPL-040 / REPL-010: every registered table carries the tracking columns and triggers."""
    register_defaults()
    for spec in global_registry.specs():
        cols = {c.name for c in db.get_columns(spec.table)}
        assert set(tracking.TRACKED_COLUMNS) <= cols, spec.table
        trig = {r[0] for r in db.execute_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()}
        assert {f"repl_{spec.table}_{s}" for s in ("ins", "upd", "del")} <= trig


# ---- REPL-050 / 060 -------------------------------------------------------------------------
@pytest.mark.requirement("TC-REPL-050")
@pytest.mark.priority("MVP")
def test_tc_repl_050_settings_changed_names_the_tables():
    """REPL-050: a bulk apply publishes settings-changed naming the tables, once each."""
    bus, seen = EventBus(), []
    bus.subscribe(SettingsChanged, lambda e: seen.append(e.tables))
    publish_settings_changed(["piers", "app_settings", "piers"], bus)
    assert seen == [["app_settings", "piers"]]


@pytest.mark.requirement("TC-REPL-060")
@pytest.mark.priority("MVP")
def test_tc_repl_060_busy_signal_and_on_idle():
    """REPL-060: is_busy() is true while a session runs; on_idle runs once, when the last one ends — or at
    once if nothing is running; a failing callback does not break the session."""
    busy, calls = SessionBusy(), []
    assert not busy.is_busy()
    busy.on_idle(lambda: calls.append("now"))
    assert calls == ["now"]
    with busy.running():
        with busy.running():
            assert busy.is_busy()
            busy.on_idle(lambda: calls.append("later"))
            busy.on_idle(lambda: 1 / 0)
        assert calls == ["now"]
    assert not busy.is_busy() and calls == ["now", "later"]


@pytest.mark.requirement("TC-REPL-060")
@pytest.mark.priority("MVP")
async def test_tc_repl_060_a_running_session_sets_the_busy_signal(monkeypatch):
    """REPL-060: the session executor reports busy for exactly the time it runs."""
    from galileo.replication.busy import get_session_busy
    from galileo.session_exec import SessionExecutor

    seen = []

    async def fake_run(self, blocks):
        seen.append(get_session_busy().is_busy())
        return "result"

    monkeypatch.setattr(SessionExecutor, "_run", fake_run)
    ex = SessionExecutor.__new__(SessionExecutor)
    assert await ex.run([]) == "result" and seen == [True] and not get_session_busy().is_busy()


# ---- REPL-070 -------------------------------------------------------------------------------
@pytest.mark.requirement("TC-REPL-070")
@pytest.mark.priority("MVP")
def test_tc_repl_070_outbox_claims_are_redelivered_until_acknowledged(settings_db):
    """REPL-070: queued changes are claimed oldest first and offered again until acknowledged; inbox items
    are applied once."""
    s = SyncStore(clock=lambda: 100.0)
    a = s.outbox_add("peer1", "app_settings", '["ns","a",""]', {"value": 1}, rev=3)
    b = s.outbox_add("peer1", "app_settings", '["ns","b",""]', {"value": 2}, op="delete")
    s.outbox_add("peer2", "app_settings", '["ns","c",""]', {"value": 3})
    first = s.outbox_claim("peer1")
    assert [r["id"] for r in first] == [a, b] and first[0]["payload"] == {"value": 1} and first[1]["op"] == "delete"
    assert [r["id"] for r in s.outbox_claim("peer1")] == [a, b]            # not acked: offered again
    s.outbox_ack([a])
    assert [r["id"] for r in s.outbox_claim("peer1")] == [b]
    i = s.inbox_add("peer1", "app_settings", '["ns","x",""]', {"value": 9}, rev=5)
    assert [r["id"] for r in s.inbox_pending("peer1")] == [i]
    s.inbox_mark([i], "applied")
    assert s.inbox_pending("peer1") == []


@pytest.mark.requirement("TC-REPL-070")
@pytest.mark.priority("MVP")
def test_tc_repl_070_snapshots_reports_transfers_and_peer_state(settings_db):
    """REPL-070: snapshots come back newest first for undo; reports are kept; the transfer queue holds an
    object once and serves the highest priority first; peer state round-trips."""
    t = [0.0]

    def clock():
        t[0] += 1
        return t[0]

    s = SyncStore(clock)
    s.snapshot_save("run1", "app_settings", "k1", None)
    s.snapshot_save("run1", "app_settings", "k2", {"value": 5})
    s.snapshot_save("run2", "app_settings", "k3", {"value": 6})
    assert [(r["natural_key"], r["before"]) for r in s.snapshot_rows("run1")] == [("k2", {"value": 5}), ("k1", None)]
    s.report_append("run1", "peer1", "ok", {"applied": 2})
    s.report_append("run2", "peer1", "partial", {"applied": 1, "errors": ["x"]})
    assert [r["run_id"] for r in s.reports()] == ["run2", "run1"] and s.reports()[0]["summary"]["errors"] == ["x"]
    low = s.transfer_enqueue("peer1", "up", "a" * 64, 100, priority=9)
    high = s.transfer_enqueue("peer1", "up", "b" * 64, 50, priority=1)
    assert s.transfer_enqueue("peer1", "up", "a" * 64, 100) == low                 # queued once
    claimed = s.transfer_claim()
    assert claimed["id"] == high and claimed["state"] == "active" and claimed["attempts"] == 1
    s.transfer_update(high, "done")
    assert s.transfer_claim("peer1")["id"] == low and s.transfer_claim("peer1") is None
    s.transfer_update(low, "retry")
    assert s.transfer_claim()["attempts"] == 2
    assert s.peer_state_get("peer1", "cursor", 0) == 0
    s.peer_state_set("peer1", "cursor", {"app_settings": 12})
    s.peer_state_set("peer1", "cursor", {"app_settings": 13})
    assert s.peer_state_get("peer1", "cursor") == {"app_settings": 13}


@pytest.mark.requirement("TC-REPL-070")
@pytest.mark.priority("MVP")
def test_tc_repl_070_sync_tables_belong_to_core_and_survive_a_migration_replay(settings_db):
    """REPL-070: the sync tables come from numbered core migrations, so a plugin ships none, and replaying
    the migrations (a fake replay) does not fail."""
    from galileo.library.database import run_migrations
    tables = set(db.get_tables())
    assert {"sync_outbox", "sync_inbox", "sync_snapshots", "sync_run_reports", "sync_transfer_queue",
            "sync_peer_state", "repl_tombstones", "repl_revisions", "repl_state"} <= tables
    db.execute_sql("DELETE FROM migratehistory WHERE name IN ('034_add_replication_tracking', '035_add_sync_tables')")
    run_migrations()                                                   # re-applies over the existing objects
    store.set_setting("ns", "still", 1)
    assert _row("ns", "still")["dirty"] == 1


# ---- REPL-080 -------------------------------------------------------------------------------
@pytest.mark.requirement("TC-REPL-080")
@pytest.mark.priority("MVP")
def test_tc_repl_080_only_the_master_issues_revisions_serially_per_table(settings_db):
    """REPL-080: a revision is a total order within a table; each table has its own sequence; a spoke
    never issues one."""
    master = RevisionIssuer(lambda: True)
    assert [master.commit_rev("app_settings") for _ in range(3)] == [1, 2, 3]
    assert master.commit_rev("piers") == 1 and master.current("app_settings") == 3 and master.current("none") == 0
    with pytest.raises(NotMasterError):
        RevisionIssuer(lambda: False).commit_rev("app_settings")
    assert master.current("app_settings") == 3


# ---- loopback guard -------------------------------------------------------------------------
@pytest.mark.requirement("TC-PROF-130")
@pytest.mark.priority("MVP")
def test_tc_prof_130_guide_100_one_loopback_check_serves_every_caller():
    """PROF-130 / GUIDE-100: localhost, 127.0.0.0/8, ::1 and 0.0.0.0 are refused in every form an address is
    typed (with a port, in brackets, as a URL); real host names and LAN addresses are fine; the message asks
    for the real name."""
    for bad in ("localhost", "LocalHost:7624", "127.0.0.1", "127.9.9.9:11111", "::1", "[::1]:80",
                "0.0.0.0",  # noqa: S104
                "http://localhost:8080/api", "::ffff:127.0.0.1", "observatory.localhost"):
        assert is_loopback(bad), bad
        assert "real host name" in loopback_message(bad)
    for good in ("scope.local", "192.168.1.5", "10.0.0.1:7624", "indi.example.org", "fe80::1", "", "::"):
        assert not is_loopback(good), good
        assert loopback_message(good) == ""
