1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Fleet roster is frozen into provision.json at flash time; gates never learn about fleet changes
3. **Issue:** The full fleet node list is embedded in each node's `provision.json` when the card is flashed, and first boot is one-shot (`/etc/easymanet/provisioned` flag). There is no mechanism to update the roster on a running node.
4. **Severity:** S3 (Moderate)
5. **Location:** `packages/core/src/easymanet/provision.py:292-298` (`resolve_fleet_model` embeds roster); `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:69-72` (provisioned flag short-circuit); consumers: `api-lib.sh:400-442` (topology iterates frozen roster), `status-lib.sh:103-138` (`EM-NODE-MISSING` from frozen roster)
6. **Expected:** Either fleet changes propagate to gates (roster refresh mechanism), or the limitation is an explicitly stated rule — "changing fleet.yml means reflashing every gate" — with the desktop warning when the gate's reported roster differs from the local fleet.yml.
7. **Actual:** Add a node after the gate was flashed: the gate's topology shows its radio links only as `unresolved` MACs and never lists it as a node. Remove a node from fleet.yml: the gate raises `EM-NODE-MISSING` for it forever. Rename/re-IP a node: the gate probes the old address. The only sync path is reflashing the gate.
8. **Reproduction:**
   1. Flash a gate from a 3-node fleet.yml; boot it.
   2. Add a 4th node to fleet.yml, flash and boot only that node.
   3. `curl http://<gate-ip>:10411/v1/topology` — 4th node absent from `nodes[]`, appears only as an `unresolved` link; conversely delete a node from the yml and observe permanent `EM-NODE-MISSING` in `/v1/status`.
9. **Notes:** From the 2026-07-04 mesh review. May be an acceptable simplicity trade-off — but currently it is undocumented behavior, and the false `MISSING`/invisible-node states erode trust in the monitoring. Minimal fix: desktop Mesh tab compares gate roster vs local fleet.yml and warns "gate roster is stale — reflash gate". Fuller fix is a design decision (`docs/design-decisions/`) about roster distribution.
