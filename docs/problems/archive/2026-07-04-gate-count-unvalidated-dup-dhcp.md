1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Fleet validation accepts zero or multiple `gate` nodes; multi-gate fleets get duplicate DHCP pools
3. **Issue:** `validate` never checks gate count. A fleet with no gate provisions a mesh with no DHCP, no internet, and no topology API. A fleet with two gates provisions two DHCP servers on the same flat `br-ahwlan` bridge with the identical pool (`start=351, limit=16`) and separate lease databases.
4. **Severity:** S3 (Moderate)
5. **Location:** `packages/core/src/easymanet/validate.py` (no gate-count rule anywhere in `validate()`); runtime consequence in `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:387-397` (every gate configures the same DHCP pool)
6. **Expected:** `easymanet validate` errors (or at least warns) when a fleet defines zero gates or more than one gate, since the runtime model assumes exactly one DHCP server and internet exit.
7. **Actual:** Both configurations validate cleanly and flash. Zero gates: clients get no leases, points show `EM-INET-DOWN`, desktop Mesh tab reports `gateway_api_not_found` with no hint the fleet file is the cause. Two gates: both serve leases from the same 16-address window without coordination, so double-assignment of client IPs is possible (BATMAN gateway steering reduces but does not eliminate the race, and clients attached directly to a gate's own bridge bypass it entirely).
8. **Reproduction:**
   1. Copy `examples/three-node-field-mesh.yml`; set `role: point` on every node (or `role: gate` on two).
   2. Run `easymanet validate <fleet.yml>` — exits clean with no gate-related error or warning.
9. **Notes:** Fix belongs in `validate.py` next to the role checks. If multi-gate is ever intended (BATMAN itself supports multiple `gw_mode=server` nodes), each gate needs a non-overlapping DHCP `start`/`limit`; until then, "exactly one gate" is the honest rule. Related: [2026-07-04-node-ip-subnet-validation-gap.md](2026-07-04-node-ip-subnet-validation-gap.md) — same file, could land as one change.
