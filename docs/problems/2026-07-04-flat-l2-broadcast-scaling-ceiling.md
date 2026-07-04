1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Flat L2 /16 mesh design - known broadcast scaling ceiling and 16-lease DHCP pool
3. **Status:** Known limitation, not a current defect. This is documented so future work does not rediscover it or over-engineer around it before the product needs it.
4. **Severity:** S5 (Note)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:319-341` (bridge + /16), `provision.sh:33-34,387-391` (`EM_AHWLAN_DHCP_START=351`, `LIMIT=16`)

## Current Design

Every node bridges BATMAN (`bat0`), mesh-side Ethernet (`eth0`, except when a gate uses it as WAN), and the local AP into one OpenMANET LAN bridge named `br-ahwlan`.
Each node gets a static address on the shared `10.41.0.0/16` network.
Only the gate serves DHCP on that shared bridge, with the default pool set to 16 leases.

This is intentional. BATMAN makes the multi-hop mesh look like one Ethernet cable, point nodes stay near-stateless, and OpenMANETd can manage gateway routing and client access using its normal model.

## Why This Is Acceptable Now

EasyMANET is aimed at small, local, operator-managed fleets.
The expected number of client devices attached to the mesh is low, and needing more than 16 DHCP clients is currently considered extremely unlikely.

The flat bridge is the simplest design that matches the current product shape.
It avoids per-node routing, per-node DHCP pools, route distribution, subnet planning, and extra operator choices.
Those tradeoffs are worth keeping until a real deployment proves otherwise.

## Known Ceiling

The shared bridge is one broadcast domain.
ARP, DHCP, and other broadcast or multicast client traffic can cross the mesh instead of staying local to one node.
BATMAN's distributed ARP table and multicast mode reduce some of this traffic, but they do not change the basic shape: a larger flat L2 mesh eventually spends more radio airtime carrying background chatter.

The 16-lease DHCP pool is a separate, simpler ceiling.
It limits the total number of DHCP client devices on the mesh, not the number of EasyMANET nodes.
Static node IPs are not part of this pool.

## What Would Make This Worth Fixing

Revisit this only if one of these becomes true:

- Operators routinely attach more than 16 DHCP client devices to one mesh.
- Hardware-in-the-loop testing shows slow or failed DHCP at the mesh edge.
- Idle client devices create measurable HaLow airtime load on larger fleets.
- The target product changes from small field fleets to larger always-on networks.

Until then, do not replace the flat bridge just because routed designs are theoretically more scalable.

## Future Options

1. Raise `EM_AHWLAN_DHCP_LIMIT`.
   This is the smallest fix if the only real problem is more than 16 client devices.
   It does not reduce broadcast traffic.

2. Expose DHCP pool size in `fleet.yml`.
   This gives operators a documented knob, but adds config, validation, docs, and support surface.
   It still does not reduce broadcast traffic.

3. Segment client LANs per node and route between them.
   This is the real scaling architecture if large fleets matter.
   It is much more complex and loses the elegant "one Ethernet cable" behavior, so it should wait for a proven need.

## Verification Notes

Local repo verification confirms the configured bridge, `/16` netmask, BATMAN settings, gate-only DHCP behavior, and 16-lease default.
The exact node count where broadcast traffic becomes painful cannot be proven from static code; it needs larger hardware-in-the-loop testing with airtime and DHCP timing measurements.
