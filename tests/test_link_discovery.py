# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""LINK — LAN discovery (TC-LINK-040). The mDNS layer is replaced by a fake backend, so these tests
do not depend on the host's network; a real-multicast check is marked ``integration``."""

import socket

import pytest
from zeroconf import ServiceInfo

from galileo.connect_link import AuditLog, PeerStore
from galileo.connect_link.certs import CertificateStore
from galileo.connect_link.discovery import (
    SERVICE_TYPE,
    Discovery,
    DiscoveryError,
    manual_address,
    parse_service,
)
from galileo.connect_link.pairing import PairingService
from galileo.connect_link.secrets_store import MemorySecretStore
from galileo.connect_link.server import PROTOCOL_VERSION, LinkServer


class FakeBackend:
    def __init__(self, visible=()):
        self.registered, self.visible, self.closed = [], list(visible), False

    async def register(self, info):
        self.registered.append(info)

    async def unregister(self, info):
        self.registered.remove(info)

    async def browse(self, listen_for):
        return self.visible

    async def close(self):
        self.closed = True


def _service(node, port=8765, host="192.168.1.20", **props):
    p = {"name": f"Obs {node}", "node": node, "proto": "1", "role": "spoke", **props}
    return ServiceInfo(SERVICE_TYPE, f"{node}.{SERVICE_TYPE}", port=port, properties=p,
                       addresses=[socket.inet_aton(host)])


def _server(settings_db, discovery):
    def clock():
        return 1_000_000.0
    store = PeerStore(clock)
    certs = CertificateStore(MemorySecretStore(), "test-node")
    return LinkServer(store, PairingService(store, clock), certs, AuditLog(clock), discovery=discovery)


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
async def test_tc_link_040_advertisement_carries_only_public_facts_and_follows_the_listener(settings_db):
    """LINK-040: while the listener runs the node advertises _galileo-link._tcp with its name, node id,
    port, protocol version and role hint and nothing secret; the advertisement stops with the listener."""
    backend = FakeBackend()
    discovery = Discovery("node-a", "Home Observatory", "master", backend)
    server = _server(settings_db, discovery)
    assert backend.registered == []
    await server.start("127.0.0.1", 0)
    (info,) = backend.registered
    assert info.type == SERVICE_TYPE and info.port == server.port and discovery.advertising
    props = {k.decode(): v.decode() for k, v in info.properties.items()}
    assert props == {"name": "Home Observatory", "node": "node-a", "proto": str(PROTOCOL_VERSION),
                     "role": "master"}
    await server.stop()
    assert backend.registered == [] and not discovery.advertising


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
async def test_tc_link_040_a_failed_advertisement_does_not_stop_the_listener(settings_db):
    """LINK-040: if mDNS is unavailable the listener still runs (peers can use a manual address)."""
    class Broken(FakeBackend):
        async def register(self, info):
            raise OSError("no multicast")

    server = _server(settings_db, Discovery("node-a", "Home", "", Broken()))
    await server.start("127.0.0.1", 0)
    assert server.running and not server.discovery.advertising
    await server.stop()


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
async def test_tc_link_040_browse_lists_other_nodes_and_ignores_malformed_ones():
    """LINK-040: browsing returns other nodes' advertisements (not this node's own, not malformed)."""
    own, other = _service("node-a"), _service("node-b", port=9000, host="192.168.1.30")
    no_node = ServiceInfo(SERVICE_TYPE, f"x.{SERVICE_TYPE}", port=1, properties={"name": "x"},
                          addresses=[socket.inet_aton("10.0.0.1")])
    discovery = Discovery("node-a", "Home", "", FakeBackend([own, other, no_node]))
    nodes = await discovery.browse(0)
    assert [(n.node_id, n.host, n.port, n.protocol, n.role) for n in nodes] == [
        ("node-b", "192.168.1.30", 9000, 1, "spoke")]
    assert parse_service(no_node) is None


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
def test_tc_link_040_manual_host_and_port_are_validated():
    """LINK-040: a host and port entered by hand are accepted when sensible and refused otherwise."""
    n = manual_address(" scope.local ", 8765)
    assert (n.host, n.port) == ("scope.local", 8765)
    assert manual_address("192.168.1.5", 1).port == 1
    for host, port in (("https://scope", 8765), ("a/b", 8765), ("", 8765), ("scope", 0), ("scope", 70000)):
        with pytest.raises(DiscoveryError):
            manual_address(host, port)


@pytest.mark.requirement("TC-LINK-040")
@pytest.mark.priority("MVP")
async def test_tc_link_040_close_withdraws_and_releases_the_backend():
    """LINK-040: closing discovery withdraws the advertisement and releases the mDNS socket."""
    backend = FakeBackend()
    discovery = Discovery("node-a", "Home", "", backend)
    await discovery.advertise("127.0.0.1", 8765, 1)
    await discovery.advertise("127.0.0.1", 8765, 1)           # idempotent
    assert len(backend.registered) == 1
    await discovery.close()
    assert backend.registered == [] and backend.closed
