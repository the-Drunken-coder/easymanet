from easymanet import disks


def test_linux_unmount_disk_unmounts_discovered_partitions_without_shell(monkeypatch):
    calls = []

    monkeypatch.setattr(disks, "is_macos", lambda: False)
    monkeypatch.setattr(disks, "is_linux", lambda: True)
    monkeypatch.setattr(
        disks.glob,
        "glob",
        lambda pattern: {
            "/dev/sdb[0-9]*": ["/dev/sdb2", "/dev/sdb1"],
            "/dev/sdbp[0-9]*": [],
        }.get(pattern, []),
    )

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr(disks.subprocess, "run", fake_run)

    disks.unmount_disk("/dev/sdb")

    assert calls == [
        (["umount", "-l", "/dev/sdb1"], {"capture_output": True, "timeout": 60}),
        (["umount", "-l", "/dev/sdb2"], {"capture_output": True, "timeout": 60}),
    ]


def test_linux_unmount_disk_falls_back_to_device_when_no_partitions(monkeypatch):
    calls = []

    monkeypatch.setattr(disks, "is_macos", lambda: False)
    monkeypatch.setattr(disks, "is_linux", lambda: True)
    monkeypatch.setattr(disks.glob, "glob", lambda _pattern: [])
    monkeypatch.setattr(disks.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)))

    disks.unmount_disk("/dev/mmcblk0")

    assert calls == [
        (["umount", "-l", "/dev/mmcblk0"], {"capture_output": True, "timeout": 60}),
    ]


def test_blocking_warnings_system_disk():
    disk = disks.DiskInfo(
        device="/dev/sda",
        size_bytes=500 * 1024**3,
        removable=False,
        is_system=True,
    )
    assert len(disk.blocking_warnings) == 1
    assert "system disk" in disk.blocking_warnings[0]


def test_blocking_warnings_large_fixed_disk():
    disk = disks.DiskInfo(
        device="/dev/nvme0n1",
        size_bytes=200 * 1024**3,
        removable=False,
        is_system=False,
    )
    assert any("Large fixed disk" in w for w in disk.blocking_warnings)


def test_blocking_warnings_not_in_default_list():
    disk = disks.DiskInfo(
        device="/dev/mmcblk0",
        size_bytes=32 * 1024**3,
        removable=True,
        not_in_default_list=True,
    )
    assert any("not in default disk list" in w for w in disk.blocking_warnings)


def test_assert_flash_allowed_blocks_without_force(monkeypatch):
    import pytest

    disk = disks.DiskInfo(
        device="/dev/sda",
        size_bytes=500 * 1024**3,
        is_system=True,
    )

    monkeypatch.setattr(disks, "_is_block_device", lambda _d: True)
    monkeypatch.setattr(disks, "lookup_device", lambda _d: disk)

    with pytest.raises(ValueError, match="--force"):
        disks.assert_flash_allowed("/dev/sda", force=False)

    assert disks.assert_flash_allowed("/dev/sda", force=True) is disk


def test_linux_should_list_default_rm_or_tran():
    assert disks._linux_should_list_default({"type": "disk", "rm": "1"})
    assert disks._linux_should_list_default({"type": "disk", "rm": "0", "tran": "mmc"})
    assert disks._linux_should_list_default({"type": "disk", "rm": "0", "tran": "usb"})
    assert not disks._linux_should_list_default({"type": "disk", "rm": "0", "tran": "nvme"})


def test_linux_disk_from_lsblk_marks_mmc_removable():
    dev = {"name": "mmcblk0", "type": "disk", "rm": "0", "tran": "mmc", "size": "32G"}
    disk = disks._linux_disk_from_lsblk(dev)
    assert disk.removable is True


def test_get_partition2_wipe_range_linux(monkeypatch):
    lsblk_output = {
        "blockdevices": [
            {
                "name": "sdb",
                "type": "disk",
                "children": [
                    {"name": "sdb1", "type": "part", "start": 2048, "size": 268435456},
                    {"name": "sdb2", "type": "part", "start": 270336, "size": 4500000000},
                ],
            }
        ]
    }

    monkeypatch.setattr(disks, "is_linux", lambda: True)
    monkeypatch.setattr(disks, "is_macos", lambda: False)

    def fake_check_output(cmd, timeout=10):
        assert "-b" in cmd
        return __import__("json").dumps(lsblk_output).encode()

    monkeypatch.setattr(disks.subprocess, "check_output", fake_check_output)

    result = disks.get_partition2_wipe_range("/dev/sdb")
    assert result is not None
    start_bytes, wipe_bytes = result
    assert start_bytes == 270336 * 512
    assert wipe_bytes > 0
