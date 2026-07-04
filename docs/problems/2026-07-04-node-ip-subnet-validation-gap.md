1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Node IPs validated only as "valid IPv4" — off-subnet and DHCP-window addresses pass
3. **Issue:** `validate_ip()` accepts any IPv4 address. It does not check membership in the mesh subnet (`10.41.0.0/16`, netmask hardcoded as `EM_MESH_NETMASK=255.255.0.0`) nor collision with the gate's DHCP hand-out window (offset 351–366 ≈ `10.41.1.95–10.41.1.110`).
4. **Severity:** S3 (Moderate)
5. **Location:** `packages/core/src/easymanet/validate.py:47` (`validate_ip`); subnet applied at `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:27,336-341`; DHCP window at `provision.sh:387-391`
6. **Expected:** Validation rejects (or warns on) node IPs outside `10.41.0.0/16` and IPs falling inside the gate DHCP lease window.
7. **Actual:** Confirmed empirically: a gate at `192.168.50.10` and a point at `172.20.2.1` validate cleanly, render, and flash. On boot, each node gets its off-subnet IP with a /16 netmask on the shared L2 bridge — nodes see each other's ARP but cannot route, the node is unreachable from the rest of the mesh, and desktop fleet-based discovery probes the configured IP and fails. A node IP inside the DHCP window can silently collide with a client lease.
8. **Reproduction:**
   1. In any fleet yml, set a node's `ip` to `192.168.50.10`.
   2. Run `easymanet validate <fleet.yml>` — passes with no error or warning.
9. **Notes:** Cheapest high-value fix from the 2026-07-04 mesh review — prevents the most confusing field failure (flash succeeds, node vanishes). Needs two checks in `validate.py`: `ipaddress.ip_address(ip) in ip_network("10.41.0.0/16")` and exclusion of the DHCP range. If the subnet is meant to be configurable someday, derive it from one shared constant instead of hardcoding twice.
