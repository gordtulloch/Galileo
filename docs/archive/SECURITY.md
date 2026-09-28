# Galileo — Network Security Notes (NFR-SEC-020)

This document covers the security implications of exposing an INDI server or
ASCOM Alpaca device over a network, and states what Galileo does and does not
do about it. It satisfies `NFR-SEC-020` (see [SRS §5.7](SRS.md)); the
credential/location-consent requirement `NFR-SEC-010` is a separate item in
the same section.

## Exposing INDI or Alpaca over a LAN vs. a WAN

Galileo's recommended deployment (SDD §7, Topology A) runs `indiserver` (or
an Alpaca device bridge) on an SBC at the telescope and the Galileo GUI on a
separate machine, connecting over the local network. This is safe on a
trusted home/observatory LAN, where every device on the network is one you
control.

**Neither INDI nor ASCOM Alpaca were designed with WAN exposure in mind:**

- **INDI** has no authentication or transport encryption in its base
  protocol. Any host that can reach `indiserver`'s TCP port can issue device
  commands — including mount slews and camera exposures — with no login
  step.
- **ASCOM Alpaca** is a plain HTTP/JSON REST API. The Alpaca specification
  defines an optional bearer-token authentication scheme, but it is
  frequently left disabled by device drivers, and the transport itself is
  unencrypted HTTP unless a reverse proxy in front of it terminates TLS.

Forwarding either service's port directly to the public internet (e.g. a
router port-forward, or a cloud relay with no auth layer) exposes an
unauthenticated telescope-control interface to anyone who finds the port.
This applies regardless of Galileo — the same risk exists for KStars/EKOS,
NINA, or any other INDI/Alpaca client.

## What Galileo does

- Galileo makes no changes to either protocol and introduces no bypass of
  whatever authentication a given INDI driver or Alpaca device does support
  (`NFR-SEC-020`'s "shall not itself weaken ... authentication" clause) — it
  is a protocol client, not a protocol implementation.
- Advisory internet data (weather forecast, aurora/Kp-index, smoke; see
  `galileo.safety`) is fetched directly by Galileo over HTTPS and is never
  used as a channel for device control.
- Equipment-profile credentials and observing-location data are never
  transmitted to an external service without explicit user configuration and
  consent (`NFR-SEC-010`).

## What Galileo does not do

Galileo does not implement its own authentication, VPN, or TLS-termination
layer for INDI/Alpaca traffic, and does not recommend exposing either
protocol directly to the public internet. If remote access from outside the
local network is needed, use one of the standard, protocol-agnostic
approaches instead:

- A VPN (WireGuard, Tailscale, or similar) so the remote client joins the
  observatory's LAN rather than the observatory exposing a port publicly.
- An SSH tunnel forwarding the INDI/Alpaca port over an already-authenticated
  SSH session.
- A reverse proxy with its own authentication and TLS in front of an Alpaca
  HTTP endpoint, if a proxy-based setup is preferred over a VPN.

None of these are Galileo-specific; they are the same mitigations the
INDI/ASCOM communities already recommend for any INDI- or Alpaca-based
imaging setup.
