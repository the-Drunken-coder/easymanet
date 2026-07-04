# Dynamic Gateway Roles

Status: future idea, not current implementation.

Today, EasyMANET requires exactly one `gate` node in each fleet. That keeps the
runtime honest because one node owns DHCP, internet exit, and gate-only topology.

Future EasyMANET could manage more of the infrastructure itself. In a larger
fleet, such as ten nodes, a node with a working Wi-Fi or other uplink could
promote itself to gateway/backhaul service. A node without an uplink would stay
or fall back to point behavior.

That future needs a real design before implementation:

- gateway eligibility and health checks for Wi-Fi or wired uplinks
- a clear election or priority rule when more than one node has backhaul
- one coordinated DHCP owner, or non-overlapping DHCP pools per gateway
- topology and desktop behavior that can show active, standby, and failed gates
- hardware-in-the-loop tests proving promotion, demotion, and client lease safety

A simple first step, when this becomes active work, is detection-only reporting:
show which nodes appear to have usable uplinks, but keep the configured single
gate rule until the DHCP and failover model is designed.
