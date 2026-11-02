# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""This node's identity (supports HIST-050, LINK-040): created once, kept in the settings database, never
replicated."""

import pytest

from galileo import node_identity
from galileo.replication import ReplicableRegistry, register_defaults


@pytest.mark.requirement("TC-HIST-050")
@pytest.mark.priority("MVP")
def test_node_id_is_created_once_stored_and_never_replicated(settings_db):
    """The id is stable across calls and restarts and lives in the node-local namespace, so two nodes can
    never share one by replication."""
    node_identity.reset_cache()
    first = node_identity.get_node_id()
    assert len(first) == 32 and node_identity.get_node_id() == first
    node_identity.reset_cache()
    assert node_identity.get_node_id() == first                          # read back from the database
    reg = ReplicableRegistry()
    register_defaults(reg)
    assert not reg.get("app_settings").replicates({"namespace": "node"})
    assert reg.get("app_settings").replicates({"namespace": "nodes_of_interest"})


def test_node_id_without_a_database_is_stable_for_the_process():
    node_identity.reset_cache()
    assert node_identity.get_node_id() == node_identity.get_node_id()
    node_identity.reset_cache()
