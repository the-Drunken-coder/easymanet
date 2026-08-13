"""Tests for boot-partition staging."""

import json
import os
import plistlib
import stat

import pytest

from easymanet.disks import capture_device_identity
from easymanet.inject import (
    InjectError,
    _atomic_write_text,
    _cleanup_mount,
    _find_boot_mount,
    _find_boot_partition,
    _fix_usb_boot_root,
    inject,
    inject_dry_run_info,
)
from easymanet.manifest import load_manifest


VALID_CONFIG = """
version: 1

mesh:
  id: test-mesh
  password: "test-password"
  channel: 42
  bandwidth_mhz: 2
  country: US

defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: "ap-password"
  management:
    root_password_hash: ""
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKm8abcdefgh"

nodes:
  node01:
    role: gate
    hostname: node01
    ip: 10.41.1.1
    local_ap:
      ssid: node01-local
    gateway:
      enabled: true
      uplink_interface: eth0
"""


def _write_config(tmp_path, content: str) -> str:
    path = tmp_path / "easymanet_test.yml"
    path.write_text(content)
    return str(path)


def _flash_target(tmp_path):
    device = tmp_path / "disk"
    device.write_bytes(b"disk")
    return str(device), capture_device_identity(str(device))


def test_find_boot_partition_macos_uses_content_when_filesystem_type_missing(monkeypatch):
    list_plist = {
        "AllDisksAndPartitions": [
            {
                "DeviceIdentifier": "disk4",
                "Partitions": [
                    {
                        "DeviceIdentifier": "disk4s1",
                        "Content": "Windows_FAT_32",
                        "MountPoint": "/Volumes/boot",
                    },
                    {
                        "DeviceIdentifier": "disk4s2",
                        "Content": "Linux",
                    },
                ],
            }
        ]
    }

    monkeypatch.setattr("easymanet.inject.is_macos", lambda: True)
    monkeypatch.setattr("easymanet.inject.is_linux", lambda: False)

    def fake_check_output(cmd, timeout=15):
        assert cmd[:3] == ["diskutil", "list", "-plist"]
        return plistlib.dumps(list_plist)

    monkeypatch.setattr("easymanet.inject.subprocess.check_output", fake_check_output)

    assert _find_boot_partition("/dev/disk4") == "/dev/disk4s1"
    assert _find_boot_mount("/dev/disk4") == "/Volumes/boot"


def test_inject_dry_run_info_mentions_boot_partition(tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)

    info = inject_dry_run_info(manifest, "node01")

    assert "/easymanet/provision.json" in info
    assert "first-boot hooks" in info


def test_inject_writes_provision_json_to_boot_partition(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda _device, _mount_point, _mounted_here: None,
    )

    results = inject(device, manifest, "node01", device_identity=identity)

    written = boot_mount / "easymanet" / "provision.json"
    assert written.exists()
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    data = json.loads(written.read_text())
    assert data["node"]["name"] == "node01"
    assert results[0] == ("/boot/easymanet/provision.json", True)


def test_inject_patches_rpi_boot_root_to_partuuid(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()
    cmdline = boot_mount / "cmdline.txt"
    cmdline.write_text(
        "console=serial0 console=tty1 root=/dev/mmcblk0p2 rootfstype=squashfs,ext4 rootwait\n"
    )
    (boot_mount / "partuuid.txt").write_text("a7ad1f13\n")

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda _device, _mount_point, _mounted_here: None,
    )

    results = inject(device, manifest, "node01", device_identity=identity)

    assert "root=PARTUUID=a7ad1f13-02" in cmdline.read_text()
    assert "root=/dev/mmcblk0p2" not in cmdline.read_text()
    assert (boot_mount / "cmdline.txt.easymanet.bak").read_text().startswith("console=serial0")
    assert results[-1] == ("/boot/cmdline.txt root=PARTUUID=a7ad1f13-02", True)


def test_inject_patches_usb_sda_root_to_partuuid(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()
    cmdline = boot_mount / "cmdline.txt"
    cmdline.write_text(
        "console=ttyAMA0 root=/dev/sda2 rootfstype=squashfs rootwait\n"
    )
    (boot_mount / "partuuid.txt").write_text("b3c4d5e6\n")

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda _device, _mount_point, _mounted_here: None,
    )

    results = inject(device, manifest, "node01", device_identity=identity)

    assert "root=PARTUUID=b3c4d5e6-02" in cmdline.read_text()
    assert "root=/dev/sda2" not in cmdline.read_text()
    assert (boot_mount / "cmdline.txt.easymanet.bak").read_text().startswith("console=ttyAMA0")
    assert results[-1] == ("/boot/cmdline.txt root=PARTUUID=b3c4d5e6-02", True)


def test_inject_patches_nvme_root_to_partuuid(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()
    cmdline = boot_mount / "cmdline.txt"
    cmdline.write_text(
        "console=ttyAMA0 root=/dev/nvme0n1p2 rootfstype=squashfs rootwait\n"
    )
    (boot_mount / "partuuid.txt").write_text("c8d9e0f1\n")

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda _device, _mount_point, _mounted_here: None,
    )

    results = inject(device, manifest, "node01", device_identity=identity)

    assert "root=PARTUUID=c8d9e0f1-02" in cmdline.read_text()
    assert "root=/dev/nvme0n1p2" not in cmdline.read_text()
    assert (boot_mount / "cmdline.txt.easymanet.bak").read_text().startswith("console=ttyAMA0")
    assert results[-1] == ("/boot/cmdline.txt root=PARTUUID=c8d9e0f1-02", True)


def test_inject_leaves_existing_boot_root_alone(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()
    cmdline = boot_mount / "cmdline.txt"
    original = "console=serial0 console=tty1 root=PARTUUID=a7ad1f13-02 rootwait\n"
    cmdline.write_text(original)
    (boot_mount / "partuuid.txt").write_text("a7ad1f13\n")

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda _device, _mount_point, _mounted_here: None,
    )

    results = inject(device, manifest, "node01", device_identity=identity)

    assert cmdline.read_text() == original
    assert not (boot_mount / "cmdline.txt.easymanet.bak").exists()
    assert all("cmdline.txt" not in path for path, _ok in results)


def test_cleanup_mount_propagates_failed_linux_unmount(monkeypatch, tmp_path):
    mount_point = tmp_path / "boot"
    mount_point.mkdir()

    class Result:
        returncode = 1
        stderr = "busy"

    monkeypatch.setattr("easymanet.inject.is_macos", lambda: False)
    monkeypatch.setattr("easymanet.inject.is_linux", lambda: True)
    monkeypatch.setattr("easymanet.inject.subprocess.run", lambda *_a, **_k: Result())

    with pytest.raises(InjectError, match="busy"):
        _cleanup_mount("/dev/disk4", str(mount_point), True)

    assert mount_point.exists()


def test_inject_propagates_owned_boot_volume_cleanup_failure(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    device, identity = _flash_target(tmp_path)
    boot_mount = tmp_path / "boot"
    boot_mount.mkdir()

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), True),
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda *_args: (_ for _ in ()).throw(InjectError("owned volume is busy")),
    )

    with pytest.raises(InjectError, match="owned volume is busy"):
        inject(device, manifest, "node01", device_identity=identity)


def test_inject_rejects_device_replacement_during_mount(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    original = tmp_path / "original-disk"
    replacement = tmp_path / "replacement-disk"
    selected = tmp_path / "selected-disk"
    boot_mount = tmp_path / "boot"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)
    boot_mount.mkdir()
    identity = capture_device_identity(str(selected))
    cleanup_calls = []

    def replace_while_mounting(_device):
        selected.unlink()
        selected.symlink_to(replacement)
        return str(boot_mount), True

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        replace_while_mounting,
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda *args: cleanup_calls.append(args),
    )

    with pytest.raises(InjectError, match="Device identity changed"):
        inject(str(selected), manifest, "node01", device_identity=identity)

    assert cleanup_calls == [(str(selected), str(boot_mount), True)]
    assert not (boot_mount / "easymanet" / "provision.json").exists()


def test_inject_rejects_device_replacement_during_staging(monkeypatch, tmp_path):
    path = _write_config(tmp_path, VALID_CONFIG)
    manifest = load_manifest(path)
    original = tmp_path / "original-disk"
    replacement = tmp_path / "replacement-disk"
    selected = tmp_path / "selected-disk"
    boot_mount = tmp_path / "boot"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)
    boot_mount.mkdir()
    identity = capture_device_identity(str(selected))
    cleanup_calls = []

    monkeypatch.setattr(
        "easymanet.inject._mount_boot_partition",
        lambda _device: (str(boot_mount), False),
    )

    def replace_while_staging(*_args, **_kwargs):
        selected.unlink()
        selected.symlink_to(replacement)
        return [("/boot/easymanet/provision.json", True)]

    monkeypatch.setattr(
        "easymanet.inject.stage_boot_payload",
        replace_while_staging,
    )
    monkeypatch.setattr(
        "easymanet.inject._cleanup_mount",
        lambda *args: cleanup_calls.append(args),
    )

    with pytest.raises(InjectError, match="Device identity changed"):
        inject(str(selected), manifest, "node01", device_identity=identity)

    assert cleanup_calls == [(str(selected), str(boot_mount), False)]


def test_atomic_write_fsyncs_same_directory_temp_before_replace(monkeypatch, tmp_path):
    target = tmp_path / "provision.json"
    events = []
    real_replace = os.replace

    monkeypatch.setattr(
        "easymanet.inject.os.fsync",
        lambda _fd: events.append("fsync"),
    )

    def record_replace(source, destination):
        source_path = os.fspath(source)
        assert os.path.dirname(source_path) == os.fspath(tmp_path)
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr("easymanet.inject.os.replace", record_replace)

    _atomic_write_text(target, "sensitive payload", mode=0o600)

    assert target.read_text() == "sensitive payload"
    assert events == ["fsync", "replace"]
    assert not list(tmp_path.glob(".provision.json.*.tmp"))


def test_atomic_write_replace_failure_preserves_destination_and_cleans_temp(
    monkeypatch, tmp_path
):
    target = tmp_path / "provision.json"
    target.write_text("previous payload")

    monkeypatch.setattr(
        "easymanet.inject.os.replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        _atomic_write_text(target, "new payload", mode=0o600)

    assert target.read_text() == "previous payload"
    assert not list(tmp_path.glob(".provision.json.*.tmp"))


def test_cmdline_atomic_failure_preserves_original_and_cleans_temp(monkeypatch, tmp_path):
    original = "console=tty1 root=/dev/sda2 rootwait\n"
    cmdline = tmp_path / "cmdline.txt"
    cmdline.write_text(original)
    (tmp_path / "partuuid.txt").write_text("a1b2c3d4\n")
    real_replace = os.replace

    def fail_cmdline_replace(source, destination):
        if os.fspath(destination) == os.fspath(cmdline):
            raise OSError("cmdline replace failed")
        real_replace(source, destination)

    monkeypatch.setattr("easymanet.inject.os.replace", fail_cmdline_replace)

    with pytest.raises(OSError, match="cmdline replace failed"):
        _fix_usb_boot_root(tmp_path)

    assert cmdline.read_text() == original
    assert (tmp_path / "cmdline.txt.easymanet.bak").read_text() == original
    assert not list(tmp_path.glob(".cmdline.txt.*.tmp"))
