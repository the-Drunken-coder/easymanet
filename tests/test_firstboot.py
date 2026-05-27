from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "provisioning" / "openwrt-overlay"
PROVISION_SCRIPT = OVERLAY / "usr" / "lib" / "easymanet" / "provision.sh"


def test_firstboot_provisioner_uses_openwrt_jsonfilter_not_python():
    text = PROVISION_SCRIPT.read_text()
    assert "jsonfilter" in text
    assert "python3" not in text


def test_firstboot_splits_mesh_and_local_ap_radios():
    text = PROVISION_SCRIPT.read_text()
    assert "find_morse_radio" in text
    assert "type='morse'" in text
    assert "hwmode='11ah'" in text
    assert "find_local_ap_radio" in text
    assert "type='mac80211'" in text
    assert "mmc_host" in text
    assert "delete_ifaces_for_radio" in text
    assert "while uci -q delete wireless.@wifi-iface[0]" not in text
    assert "while uci -q delete wireless.@wifi-device[0]" not in text
    assert 'wireless.mesh0.device="$MESH_RADIO"' in text
    assert 'wireless.mesh0.ifname="wlan0"' in text
    assert 'wireless.ap0.device="$AP_RADIO"' in text
    assert "s1g_chanbw" in text
    assert 'bcf="bcf_fgh100mhaamd.bin"' in text
    assert 'uci -q delete wireless."$MESH_RADIO".htmode 2>/dev/null || true' in text
    assert "Ensuring eth0 stays on br-lan for management" in text
    assert "easymanet_repair_management_lan firstboot" in text
    assert "Keeping eth0 on br-lan for management; removing WAN from eth0." not in text
    assert "network.@device[0].ports=\"$UPLINK\"" not in text


def test_firstboot_uses_batman_mesh_topology():
    text = PROVISION_SCRIPT.read_text()
    assert 'wireless.mesh0.mesh_fwding="0"' in text
    assert 'network.bat0.proto="batadv"' in text
    assert 'network.bat0.routing_algo="BATMAN_V"' in text
    assert 'network.bat0.gw_mode="$BATMAN_GW_MODE"' in text
    assert 'network.mesh.proto="batadv_hardif"' in text
    assert 'network.mesh.master="bat0"' in text
    assert 'uci -q delete network.mesh.ipaddr 2>/dev/null || true' in text
    assert 'uci -q delete network.mesh.netmask 2>/dev/null || true' in text
    assert 'network.meship.device="bat0"' in text
    assert 'network.meship.ipaddr="$NODE_IP"' in text
    assert 'network.meship.netmask="255.255.0.0"' in text
    assert "uci -q delete dhcp.mesh" in text
    assert 'dhcp.lan.interface="lan"' in text
    assert 'dhcp.lan.start="100"' in text
    assert 'firewall.mesh_zone.network="meship"' in text
    assert 'network.mesh.proto="static"' not in text
    assert 'network.mesh.ipaddr="$NODE_IP"' not in text
    assert 'network.mesh.netmask="255.255.255.0"' not in text


def test_firstboot_creates_lan_interface_before_setting_lan_fields():
    text = PROVISION_SCRIPT.read_text()

    create_idx = text.index("uci_set network.lan=interface")
    netmask_idx = text.index('uci_set network.lan.netmask="255.255.255.0"')
    repair_idx = text.index("easymanet_repair_management_lan firstboot")

    assert create_idx < netmask_idx < repair_idx


def test_firstboot_configures_mesh11sd_from_known_good_openmanet_state():
    text = PROVISION_SCRIPT.read_text()
    assert 'MESH_GATE_ANNOUNCEMENTS="1"' in text
    assert 'mesh11sd.setup.enabled="1"' in text
    assert 'mesh11sd.mesh_params.mesh_fwding="0"' in text
    assert 'mesh11sd.mesh_params.mesh_max_peer_links="10"' in text
    assert 'mesh11sd.mesh_params.mesh_rssi_threshold="0"' in text
    assert 'mesh11sd.mesh_params.mesh_hwmp_rootmode="0"' in text
    assert 'mesh11sd.mesh_params.mesh_gate_announcements="$MESH_GATE_ANNOUNCEMENTS"' in text
    assert 'mesh11sd.mesh_dynamic_peering.enabled="1"' in text
    assert 'mesh11sd.mesh_beaconless.mesh_beacon_less_mode="0"' in text
    assert 'mesh11sd.mbca.mbca_config="1"' in text
    assert "/etc/init.d/mesh11sd enable" in text
    assert "dot11MeshHWMPRootMode" not in text
    assert 'mesh_hwmp_rootmode="1"' not in text


def test_firstboot_can_configure_wifi_uplink():
    text = PROVISION_SCRIPT.read_text()
    assert "json_bool node gateway wifi enabled" in text
    assert "gateway.wifi.enabled requires gateway.wifi.ssid" in text
    assert 'wireless.wan0=wifi-iface' in text
    assert 'wireless.wan0.network="wan"' in text
    assert 'wireless.wan0.mode="sta"' in text
    assert 'wireless.wan0.ssid="$WIFI_UPLINK_SSID"' in text
    assert 'wireless.wan0.encryption="$WIFI_UPLINK_ENCRYPTION"' in text
    assert 'wireless.wan0.key="$WIFI_UPLINK_PASSWORD"' in text
    assert 'delete_ifaces_for_radio "$AP_RADIO"' in text
    assert 'network.wan.proto="dhcp"' in text
    assert 'uci -q delete network.wan.ifname' in text
    assert "firewall.allow_ssh_wan=rule" in text
    assert 'firewall.allow_ssh_wan.src="wan"' in text
    assert 'firewall.allow_ssh_wan.dest_port="22"' in text
    assert 'firewall.allow_ssh_wan.target="ACCEPT"' in text


def test_firstboot_installs_ssh_keys_via_jsonfilter_array():
    text = PROVISION_SCRIPT.read_text()
    assert "@.management.ssh_authorized_keys[*]" in text
    assert "jsonfilter -i \"$PROVISION_JSON\" -e '@.management.ssh_authorized_keys[*]'" in text
    assert "chmod 0600 /etc/dropbear/authorized_keys" in text
    assert "chown root /etc/dropbear/authorized_keys" in text


def test_firstboot_fails_if_root_password_hash_not_applied():
    text = PROVISION_SCRIPT.read_text()
    assert "failed to set root password hash in /etc/shadow" in text
    shadow_block = text.split("Setting root password hash")[1].split("Configuring mesh")[0]
    assert 'sed -i "s|^root:.*|root:${ROOT_PW_HASH}' in shadow_block
    assert "/etc/shadow; then" in shadow_block
    assert "|| true" not in shadow_block


def test_uci_defaults_propagates_provision_failure_rc():
    defaults = OVERLAY / "etc" / "uci-defaults" / "99-easymanet"
    text = defaults.read_text()
    assert "set -eu" in text
    assert "set +e" in text
    assert '/bin/sh "$PROVISION_SCRIPT"' in text
    assert "rc=$?" in text
    assert "set -e" in text.split("rc=$?")[1]
    assert 'if [ "$rc" -eq 0 ]; then' in text
    assert 'if /bin/sh "$PROVISION_SCRIPT"; then' not in text
    assert "provisioning failed with rc=" in text
    assert 'exit "$rc"' in text


def test_firstboot_honors_ssh_enabled_flag():
    text = PROVISION_SCRIPT.read_text()
    assert "SSH_ENABLED=0" in text
    assert 'if [ -n "$(json_val management ssh_enabled)" ]; then' in text
    assert 'json_bool management ssh_enabled && SSH_ENABLED=1' in text
    assert 'elif [ "$NODE_ROLE" = "gate" ]; then' in text
    assert 'if [ "$NODE_ROLE" = "gate" ] || json_bool management ssh_enabled' not in text
    assert "/etc/init.d/dropbear enable" in text
    assert "/etc/init.d/dropbear disable" in text
    assert "/etc/init.d/dropbear stop" in text
    assert 'if [ "$SSH_ENABLED" -eq 1 ]; then' in text


def test_firstboot_does_not_auto_reboot_after_provisioning():
    text = PROVISION_SCRIPT.read_text()
    assert "reboot" not in text
    assert "( sleep 5;" not in text


def test_management_lan_repair_hook_is_packaged_and_enabled():
    helper = OVERLAY / "usr" / "lib" / "easymanet" / "network.sh"
    init = OVERLAY / "etc" / "init.d" / "easymanet-management-lan"
    defaults = OVERLAY / "etc" / "uci-defaults" / "97-easymanet-management-lan"

    assert helper.exists()
    assert init.exists()
    assert defaults.exists()
    helper_text = helper.read_text()
    assert "easymanet_repair_management_lan" in helper_text
    assert "uci -q delete network.wan" in helper_text
    assert "uci -q delete network.wan6" in helper_text
    assert 'uci add_list network."$bridge".ports="$port"' in helper_text
    assert 'case " $ports "' in helper_text
    assert 'uci -q get network."$bridge".ports' in helper_text
    assert 'uci -q delete network."$bridge".ports' not in helper_text
    assert "brctl addif br-lan" in helper_text
    assert "uci set network.lan=interface" in helper_text
    assert 'uci set network.lan.device="br-lan"' in helper_text
    assert 'uci set network.lan.proto="static"' in helper_text
    assert 'uci set network.lan.ipaddr="10.41.254.1"' in helper_text
    init_text = init.read_text()
    assert "sleep 25" in init_text
    assert "USE_PROCD" not in init_text
    assert "write_easymanet_boot_report post-management-lan" in init_text
    assert "/etc/init.d/easymanet-management-lan enable" in defaults.read_text()


def test_boot_report_hook_is_packaged_and_enabled():
    report = OVERLAY / "usr" / "lib" / "easymanet" / "boot-report.sh"
    init = OVERLAY / "etc" / "init.d" / "easymanet-boot-report"
    defaults = OVERLAY / "etc" / "uci-defaults" / "98-easymanet-boot-report"

    assert report.exists()
    assert init.exists()
    assert defaults.exists()
    report_text = report.read_text()
    assert "write_easymanet_boot_report" in report_text
    assert "boot-report-latest" in report_text
    assert "iw-wlan0-station-dump.txt" in report_text
    assert "iw-wlan0-mpath-dump.txt" in report_text
    assert "batctl-neighbors.txt" in report_text
    assert "batctl-originators.txt" in report_text
    assert "mesh11sd-status.txt" in report_text
    assert "uci-mesh11sd.txt" in report_text
    assert "easymanet_redact_uci_wireless" in report_text
    assert "\\1'<redacted>'" in report_text
    assert "\\1='<redacted>'" not in report_text
    assert 'cp /etc/easymanet/provision.json' not in report_text
    assert 'cp /etc/config/wireless' not in report_text
    assert "wpa_supplicant-wlan0.conf" not in report_text
    assert "/etc/init.d/easymanet-boot-report enable" in defaults.read_text()
    assert "write_easymanet_boot_report provisioned" in PROVISION_SCRIPT.read_text()
    assert "easymanet-network.log" in report_text
