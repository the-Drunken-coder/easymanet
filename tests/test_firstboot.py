from pathlib import Path


def test_firstboot_provisioner_uses_openwrt_jsonfilter_not_python():
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
        assert "jsonfilter" in text
        assert "python3" not in text


def test_firstboot_splits_mesh_and_local_ap_radios():
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
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
        assert "Keeping eth0 on br-lan for management; removing WAN from eth0." in text
        assert "easymanet_repair_management_lan firstboot" in text
        assert "network.@device[0].ports=\"$UPLINK\"" not in text


def test_firstboot_uses_batman_mesh_topology():
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
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
        assert 'firewall.mesh_zone.network="meship"' in text
        assert 'network.mesh.proto="static"' not in text
        assert 'network.mesh.ipaddr="$NODE_IP"' not in text
        assert 'network.mesh.netmask="255.255.255.0"' not in text


def test_firstboot_configures_mesh11sd_from_known_good_openmanet_state():
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
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
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
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


def test_management_lan_repair_hook_is_packaged_and_enabled():
    root = Path(__file__).resolve().parents[1]
    overlay = root / "provisioning" / "openwrt-overlay"
    helper = overlay / "usr" / "lib" / "easymanet" / "network.sh"
    init = overlay / "etc" / "init.d" / "easymanet-management-lan"
    defaults = overlay / "etc" / "uci-defaults" / "97-easymanet-management-lan"

    assert helper.exists()
    assert init.exists()
    assert defaults.exists()
    helper_text = helper.read_text()
    assert "easymanet_repair_management_lan" in helper_text
    assert "uci -q delete network.wan" in helper_text
    assert "uci -q delete network.wan6" in helper_text
    assert 'uci add_list network."$bridge".ports="$port"' in helper_text
    assert "brctl addif br-lan" in helper_text
    init_text = init.read_text()
    assert "sleep 25" in init_text
    assert "USE_PROCD" not in init_text
    assert "write_easymanet_boot_report post-management-lan" in init_text
    assert "/etc/init.d/easymanet-management-lan enable" in defaults.read_text()


def test_boot_report_hook_is_packaged_and_enabled():
    root = Path(__file__).resolve().parents[1]
    overlay = root / "provisioning" / "openwrt-overlay"
    report = overlay / "usr" / "lib" / "easymanet" / "boot-report.sh"
    init = overlay / "etc" / "init.d" / "easymanet-boot-report"
    defaults = overlay / "etc" / "uci-defaults" / "98-easymanet-boot-report"
    provision = overlay / "usr" / "lib" / "easymanet" / "provision.sh"

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
    assert "wpa_supplicant-wlan0.conf" in report_text
    assert "/etc/init.d/easymanet-boot-report enable" in defaults.read_text()
    assert "write_easymanet_boot_report provisioned" in provision.read_text()
    assert "easymanet-network.log" in report_text
