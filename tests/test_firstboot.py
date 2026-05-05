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
        assert "delete_ifaces_for_radio" in text
        assert "while uci -q delete wireless.@wifi-iface[0]" not in text
        assert "while uci -q delete wireless.@wifi-device[0]" not in text
        assert 'wireless.mesh0.device="$MESH_RADIO"' in text
        assert 'wireless.ap0.device="$AP_RADIO"' in text
        assert "s1g_chanbw" in text
        assert 'uci -q delete wireless."$MESH_RADIO".htmode 2>/dev/null || true' in text
        assert "Keeping eth0 on br-lan for management" in text
        assert "network.@device[0].ports=\"$UPLINK\"" not in text


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
    assert "write_easymanet_boot_report" in report.read_text()
    assert "boot-report-latest" in report.read_text()
    assert "/etc/init.d/easymanet-boot-report enable" in defaults.read_text()
    assert "write_easymanet_boot_report provisioned" in provision.read_text()
