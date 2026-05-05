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
