1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Topology probe cap (8) falsely marks extra nodes "offline" in fleets larger than 9
3. **Issue:** The gate's topology builder stops probing peers after `MAX_TOPOLOGY_PEER_PROBES=8`. Every fleet peer beyond the cap is recorded as `offline` regardless of its real state, which also inflates `EM-NODE-MISSING` counts in `/v1/status`.
4. **Severity:** S3 (Moderate)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/api.sh:13` (default cap); `api-lib.sh:416-419` (skip + `status="offline"` + warning); downstream: `status-lib.sh:124-131` (offline → `MISSING`)
6. **Expected:** Nodes that are up are reported up. If probing must be bounded, unprobed nodes should get a distinct status (`unknown`/`skipped`), not `offline`, and the desktop should surface the "probe limit" warning prominently.
7. **Actual:** In a fleet with more than 8 non-gate nodes, healthy nodes past the cap show as `offline` in `/v1/topology`, count as `MISSING` on the HDMI fleet list, and trigger the `EM-NODE-MISSING` support code — false alarms arriving exactly at the fleet size where the monitoring matters most. The only signal is a warning string buried in `warnings[]`.
8. **Reproduction:**
   1. Provision a gate with a fleet.yml listing 10 point nodes (all online).
   2. `curl http://<gate-ip>:10411/v1/topology` — at least one node has `"status":"offline"` with warning `"<name> skipped after topology probe limit (8)"`.
9. **Notes:** From the 2026-07-04 mesh review. The cap exists to protect the uhttpd `script_timeout=10` budget (see [2026-07-04-gate-status-topology-sweep-timeout.md](2026-07-04-gate-status-topology-sweep-timeout.md)); fixing that with parallel probes/caching removes the need for a cap this low. Interim cheap fix: report skipped peers as `UNKNOWN` instead of `offline` so they don't count as missing.
