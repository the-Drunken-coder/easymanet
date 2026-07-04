1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Point nodes get no default route from EasyMANET — internet status depends on OpenMANETd behavior
3. **Issue:** Provisioning gives points a static IP and DNS servers on `ahwlan` but never a default route; reaching the internet from the point itself relies on OpenMANETd (via BATMAN `gw_mode=client`) installing one. If it doesn't, every point permanently reports `EM-INET-DOWN` as structural noise.
4. **Severity:** S4 (Minor — pending HIL verification; upgrade if confirmed)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh:336-341` (static `ahwlan`, DNS set, no `gateway` option); `status-lib.sh:33-41` (`status_public_internet` pings 1.1.1.1/8.8.8.8); OpenMANETd handoff at `provision.sh:499-529` (`meshNetInterface: br-ahwlan`)
6. **Expected:** Either EasyMANET explicitly configures point routing (e.g. `option gateway <gate-ip>` on `ahwlan`, or documented reliance on OpenMANETd with the dependency stated), and the `EM-INET-DOWN` support code on points reflects reality.
7. **Actual:** Unverifiable from the repo alone — OpenMANETd's gateway-route management is the inferred, uncontracted coupling flagged in the 2026-06 review. If OpenMANETd does install routes, this is a docs gap; if not, point HDMI displays show a permanent red `INTERNET DOWN` that operators will learn to ignore, masking real outages.
8. **Reproduction:**
   1. On provisioned hardware (HIL): `ssh root@<point-ip> 'ip route show default; ping -c1 -w2 1.1.1.1'`.
   2. Compare against the point's `/v1/status` `internet.ok` and support code.
9. **Notes:** From the 2026-07-04 mesh review. Good candidate for the next `tools/hil_verify.py` run. Client devices are unaffected either way (they DHCP from the gate, which hands out router/DNS); this is only about the point node's own connectivity and the honesty of its status display.
