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


def test_firstboot_targets_existing_halow_radio_without_deleting_devices():
    root = Path(__file__).resolve().parents[1]
    for script in [
        root / "firstboot" / "provision.sh",
        root / "provisioning" / "openwrt-overlay" / "usr" / "lib" / "easymanet" / "provision.sh",
    ]:
        text = script.read_text()
        assert "find_halow_radio" in text
        assert "hwmode='11ah'" in text
        assert "while uci -q delete wireless.@wifi-iface[0]" in text
        assert "while uci -q delete wireless.@wifi-device[0]" not in text
        assert 'wireless.mesh0.device="$MESH_RADIO"' in text
        assert 'wireless.ap0.device="$MESH_RADIO"' in text
