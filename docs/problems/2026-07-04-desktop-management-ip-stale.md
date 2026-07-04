1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Desktop post-flash hint points every node at legacy 10.41.254.1 instead of its fleet IP
3. **Issue:** `node_access()` hardcodes `management_ip: "10.41.254.1"` for every node, and the flash UI renders "Connect Ethernet, then SSH to root@10.41.254.1" — but provisioned nodes answer on their fleet-assigned mesh IP on `br-ahwlan`.
4. **Severity:** S4 (Minor)
5. **Location:** `apps/desktop/src/easymanet_desktop/payloads.py:27,486,494` (`MANAGEMENT_LAN_IP` constant, used in `node_access`); `apps/desktop/src/easymanet_desktop/static/flash-ui.js:17-23` (`flashAccessHint`); dead fossil: `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:28` (`EM_LAN_FALLBACK_IP=10.41.254.1` defined, never used)
6. **Expected:** The post-flash hint shows the node's configured mesh IP (`resolved.ip`), falling back to 10.41.254.1 only as the "provisioning failed / base image" troubleshooting address.
7. **Actual:** In the success path (node boots, provisions, joins mesh) the operator is told to SSH to an address that no longer exists — `network.sh`/`provision.sh` delete the old `br-lan` management LAN entirely. 10.41.254.1 is only correct when provisioning failed before network config (it is the OpenMANET base-image default, per `docs/lessons-learned.md`).
8. **Reproduction:**
   1. In the desktop app, validate any fleet and start a flash for a node with e.g. `ip: 10.41.0.11`.
   2. Post-flash access hint reads `root@10.41.254.1` instead of `root@10.41.0.11`.
9. **Notes:** From the handed 2026-07-04 review; verified. Essentially a one-line fix: `node_access()` already calls `resolve_node_model` and has `resolved.ip` in hand two lines above the hardcoded constant. Keep 10.41.254.1 as a *probe candidate* in `mesh.py:27` / `diagnostics.py:31` (correct for failed/base-image nodes); optionally delete the unused `EM_LAN_FALLBACK_IP` while in there.
