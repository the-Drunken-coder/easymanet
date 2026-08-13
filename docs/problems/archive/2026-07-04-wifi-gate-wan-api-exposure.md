1. **Time & Date:** 2026-07-04T06:17:34Z
2. **Name:** Wi-Fi-uplink gates expose the unauthenticated mesh API (and optionally SSH) to the upstream network
3. **Issue:** When a gate uses a Wi-Fi uplink, the EasyMANET API binds to `0.0.0.0:10411` and a firewall rule opens that port on WAN. The API is unauthenticated and returns the full mesh roster (node names, IPs, MACs, roles, topology). With `ssh_enabled`, port 22 is also opened on WAN.
4. **Severity:** S2 (Major)
5. **Location:** `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision-runtime.sh:132-133` (0.0.0.0 bind for wifi gates); `provision.sh:466-483` (`allow_ssh_wan`, `allow_easymanet_api_wan` firewall rules)
6. **Expected:** WAN-side access to the mesh API is either off by default, gated behind a shared token, or at minimum an explicit opt-in flag in fleet.yml with a validation warning. Posture should be consistent across uplink types.
7. **Actual:** Anyone on the upstream Wi-Fi (shared house network, venue AP, hostile hotspot) can `curl http://<gate-wan-ip>:10411/v1/topology` and read the entire mesh inventory — ideal recon — and probe SSH if enabled. Ethernet-uplink gates bind the API to the mesh IP only (`provision-runtime.sh:135`), so the exposure is an accident of the Wi-Fi code path, not a consistent design choice. Mitigating factors: API is read-only CGI, SSH is credential-protected.
8. **Reproduction:**
   1. Provision a gate with `gateway.wifi.enabled: true` joined to any Wi-Fi network.
   2. From another device on that upstream network: `curl http://<gate-uplink-ip>:10411/v1/identity` — full node identity returned, no auth.
9. **Notes:** From both 2026-07-04 reviews (independently found). Needs a small design decision first: is desktop-over-uplink management a feature? If yes, add a static bearer token carried in `provision.json` and checked in `api.sh`; if no, bind wifi gates to `$NODE_IP` like ethernet gates and drop `allow_easymanet_api_wan`. Related known risk: plaintext secrets in fleet.yml/provision.json (2026-06 review, still open).
