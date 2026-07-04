1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Gate status path re-sweeps the whole mesh every 5s and can exceed its own uhttpd timeout
3. **Issue:** On a gate, every status render triggers a full serial HTTP sweep of all fleet peers. The HDMI display loop does this every 5 seconds, and `/v1/status` can take longer than uhttpd's 10-second `script_timeout` exactly when peers are offline.
4. **Severity:** S3 (Moderate)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/display-status.sh:78-81` (5s loop) → `status-lib.sh:111` (`status_fleet_json` calls `topology_json_body`) → `api-lib.sh:375-464` (serial peer probes, `FETCH_TIMEOUT=1`, up to 8 peers × 2 fetches); timeout set at `provision-runtime.sh:128` (`script_timeout=10`)
6. **Expected:** Status rendering reads a cached snapshot; the mesh-wide sweep happens at a bounded, slower cadence; `/v1/status` always answers within the uhttpd timeout.
7. **Actual:** A gate with a monitor attached probes every peer (identity + neighbors) over the low-bandwidth HaLow radio roughly every 5 seconds, forever. When several peers are down, the serial probes (~1s timeout each) plus internet pings (up to 4s if the first target fails) push `/v1/status` past 10s, so uhttpd kills the CGI — the endpoint meant to report failures dies precisely during failures. The `api.sh:56-61` fallback then emits `EM-DIAG-PARTIAL`.
8. **Reproduction:**
   1. Provision a gate with an HDMI display and a fleet of ≥4 nodes; power off 3 points.
   2. `time curl http://<gate-ip>:10411/v1/status` — observe duration approaching/exceeding 10s and the `EM-DIAG-PARTIAL` fallback body.
   3. Watch `/var/log/easymanet-display-status.log` / point uhttpd access patterns for the 5s probe cadence.
9. **Notes:** Fix direction from the 2026-07-04 mesh review: write the status/topology snapshot to a tmp file with a short TTL and have display, LED, and API read that one snapshot; probe peers in parallel (background jobs + wait) instead of serially. Timing figures are code-derived, not HIL-measured — worth confirming on hardware via `tools/hil_verify.py`.
