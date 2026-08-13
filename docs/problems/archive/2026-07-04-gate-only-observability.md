1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Gate is the single pane of glass — gate down means operator is blind (design note)
3. **Issue:** Topology is only served by gates (`/v1/topology` returns `not_gateway` on points) and the desktop Mesh tab only accepts gates as entry points. If the gate is down, the operator sees nothing, even when all points are meshing fine.
4. **Severity:** S5 (Note)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/api-lib.sh:375-379` (`topology_json_body` gate check); `apps/desktop/src/easymanet_desktop/mesh.py:74` (`_is_connected_gateway` filters to `role == "gate"`)
6. **Expected:** n/a as designed — centralizing aggregation on the gate is a reasonable simplicity choice. Ideal behavior would be a degraded desktop mode: when no gate answers, probe points' `/v1/identity` + `/v1/neighbors` directly and render a partial map labeled "gateway unreachable".
7. **Actual:** Gate offline (or just its uhttpd wedged) → desktop reports `gateway_api_not_found` and shows zero nodes; points continue answering `/v1/identity` and `/v1/neighbors` on their mesh IPs but nothing consumes them. The failure message steers the operator toward reflashing ("Reflash the gateway with a topology API image") when the actual fault may be a dead gate Pi.
8. **Reproduction:**
   1. Provision a gate + 2 points; power off the gate.
   2. Desktop Mesh tab rescan → `gateway_api_not_found`, no nodes shown, while `curl http://<point-ip>:10411/v1/neighbors` from a mesh-attached laptop still works.
9. **Notes:** From the 2026-07-04 mesh review. The building blocks for the degraded mode already exist — points run the same API, and `mesh.py` already probes all candidates; it just discards non-gate responders. Also worth softening the misleading "reflash" error text (`mesh.py:90`) independently of any bigger change.
