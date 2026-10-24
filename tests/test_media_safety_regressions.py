import gzip
import json
import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from easymanet import disks
from easymanet.disks import core as disk_core
from easymanet.disks import linux, macos
from easymanet.image import FlashError, flash_image
from easymanet.inject import InjectError, inject
from easymanet.manifest import load_manifest


ROOT = os.path.dirname(os.path.dirname(__file__))


def _disk(name, children=(), **fields):
    return {
        "name": name,
        "type": "disk",
        "size": 32 * 1024**3,
        "rm": True,
        "children": list(children),
        **fields,
    }


def _linux_os(monkeypatch, devices, sources=None, *, fstypes=None, btrfs_output=None):
    sources = sources or {"/": "/dev/md0"}
    fstypes = fstypes or {}

    def check_output(cmd, **_kwargs):
        if cmd[0] == "lsblk" and "-J" in cmd:
            return json.dumps({"blockdevices": devices}).encode()
        if cmd[0] == "lsblk" and "PKNAME" in cmd:
            return b"sda1\nsdb1\n"
        if cmd[0] == "findmnt":
            if "-J" in cmd:
                return json.dumps(
                    {
                        "filesystems": [
                            {"source": source, "target": target, "fstype": fstypes.get(target, "ext4")}
                            for target, source in sources.items()
                        ]
                    }
                ).encode()
            return sources.get(cmd[-1], "").encode()
        if cmd[:3] == ["btrfs", "filesystem", "show"]:
            if btrfs_output is None:
                raise FileNotFoundError("btrfs")
            return btrfs_output.encode()
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(disk_core, "_is_block_device", lambda _path: True)


@pytest.mark.parametrize("source", ["/dev/md0", "/dev/mapper/root"])
def test_every_nested_raid_and_mapper_backing_disk_is_protected(monkeypatch, source):
    root = {"name": "dm-0", "type": "lvm", "mountpoint": "/"}
    raid = {"name": "md0", "type": "raid1", "children": [root]}
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "children": [raid]}], rm="1"),
        _disk("sdb", [{"name": "sdb1", "type": "part", "children": [raid]}], rm="1"),
        _disk("sdc", rm="1"),
    ]
    _linux_os(monkeypatch, devices, {"/": source})
    realpath = os.path.realpath
    monkeypatch.setattr(
        os.path,
        "realpath",
        lambda path: "/dev/dm-0" if path == "/dev/mapper/root" else realpath(path),
    )

    found = {disk.device: disk for disk in linux.list_disks_linux()}

    assert set(found) == {"/dev/sda", "/dev/sdb", "/dev/sdc"}
    assert found["/dev/sda"].is_system
    assert found["/dev/sdb"].is_system
    assert "/" in found["/dev/sdb"].mounted
    assert not found["/dev/sdc"].is_system


@pytest.mark.parametrize(
    "unknown_source", ["/dev/md99", "/dev/mapper/missing", "overlay"]
)
def test_unresolved_system_backing_graph_fails_closed(monkeypatch, unknown_source):
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}], rm=False),
        _disk("sdc", rm="1"),
    ]
    _linux_os(monkeypatch, devices, {"/": "/dev/sda1", "/home": unknown_source})

    found = linux.list_disks_linux()

    assert found[0].safety_error
    assert not found[0].is_system
    with pytest.raises(ValueError, match="resolve"):
        disks.assert_flash_allowed("/dev/sdc", force=True)


def test_native_removable_boolean_is_usable_without_force(monkeypatch):
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}], rm=False),
        _disk("sdc", tran=None),
    ]
    _linux_os(monkeypatch, devices, {"/": "/dev/sda1"})

    found = linux.list_disks_linux()

    assert [disk.device for disk in found] == ["/dev/sdc"]
    assert found[0].removable
    assert not found[0].blocking_warnings


@pytest.mark.parametrize(
    ("target", "source", "fstype"),
    [
        ("/home", "fileserver:/export/home", "nfs"),
        ("/home", "fileserver:/export/home", "nfs4"),
        ("/home", "//fileserver/home", "cifs"),
        ("/boot", "systemd-1", "autofs"),
        ("/var", "tmpfs", "tmpfs"),
    ],
)
def test_nonlocal_system_mounts_do_not_block_unrelated_media(monkeypatch, target, source, fstype):
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}], rm=False),
        _disk("sdc"),
    ]
    _linux_os(
        monkeypatch, devices, {"/": "/dev/sda1", target: source}, fstypes={target: fstype}
    )

    disk = disks.assert_flash_allowed("/dev/sdc")

    assert not disk.is_system
    assert not disk.safety_error
    with pytest.raises(ValueError, match="system disk"):
        disks.assert_flash_allowed("/dev/sda", force=True)


def test_network_root_still_protects_local_boot_media(monkeypatch):
    _linux_os(
        monkeypatch,
        [_disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/boot"}]), _disk("sdc")],
        {"/": "fileserver:/export/root", "/boot": "/dev/sda1"}, fstypes={"/": "nfs4"},
    )

    assert not disks.assert_flash_allowed("/dev/sdc").safety_error
    with pytest.raises(ValueError, match="system disk"):
        disks.assert_flash_allowed("/dev/sda", force=True)


@pytest.mark.parametrize("fstype", ["overlay", "zfs", "", None])
def test_unresolved_local_or_unknown_filesystem_stays_blocked(monkeypatch, fstype):
    _linux_os(
        monkeypatch,
        [_disk("sda", [{"name": "sda1", "type": "part"}]), _disk("sdc")],
        {"/": "/dev/sda1", "/home": "unresolved"},
        fstypes={"/home": fstype},
    )

    with pytest.raises(ValueError, match="resolve"):
        disks.assert_flash_allowed("/dev/sdc", force=True)


def test_all_btrfs_system_members_are_hard_blocked(monkeypatch):
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}]),
        _disk("sdb", [{"name": "sdb1", "type": "part"}]),
        _disk("sdc"),
    ]
    _linux_os(
        monkeypatch, devices, {"/": "/dev/sda1[/@]"}, fstypes={"/": "btrfs"},
        btrfs_output=(
            "Label: none  uuid: 8a9d72cd-ead3-469d-b371-9c7203276265\n"
            "\tTotal devices 2 FS bytes used 32768\n"
            "\tdevid    1 size 34359738368 used 1048576 path /dev/sda1\n"
            "\tdevid    2 size 34359738368 used 1048576 path /dev/sdb1\n"
        ),
    )

    found = {disk.device: disk for disk in linux.list_disks_linux()}

    assert found["/dev/sda"].is_system
    assert found["/dev/sdb"].is_system
    for device in ("/dev/sda", "/dev/sdb"):
        with pytest.raises(ValueError, match="system disk"):
            disks.assert_flash_allowed(device, force=True)
    assert disks.assert_flash_allowed("/dev/sdc").device == "/dev/sdc"


@pytest.mark.parametrize(
    "btrfs_output",
    [
        None,
        "Total devices 2 FS bytes used 32768\n\tdevid 1 size 34359738368 used 1048576 path /dev/sda1\n",
        "Total devices 1 FS bytes used 32768\n\tdevid 1 size 0 used 0 path /dev/sda1 MISSING\n",
        "Total devices 1 FS bytes used 32768\n\tdevid 1 size 34359738368 used 1048576 path /dev/unknown\n",
    ],
    ids=["tool-unavailable", "missing-member", "missing-device", "unknown-backing"],
)
def test_incomplete_btrfs_membership_fails_closed(monkeypatch, btrfs_output):
    _linux_os(
        monkeypatch,
        [_disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}]), _disk("sdc")],
        {"/": "/dev/sda1[/@]"}, fstypes={"/": "btrfs"}, btrfs_output=btrfs_output,
    )

    with pytest.raises(ValueError, match="resolve"):
        disks.assert_flash_allowed("/dev/sdc", force=True)


@pytest.mark.parametrize("compressed", [False, True])
def test_oversized_payload_is_rejected_before_unmount_or_open(
    monkeypatch, tmp_path, compressed
):
    device = tmp_path / "disk"
    device.write_bytes(b"untouched")
    image = tmp_path / ("firmware.img.gz" if compressed else "firmware.img")
    payload = b"x" * 4096
    image.write_bytes(gzip.compress(payload) if compressed else payload)
    _linux_os(
        monkeypatch,
        [
            _disk(
                "sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}], rm=False
            ),
            _disk("sdc", size=1024),
        ],
        {"/": "/dev/sda1"},
    )
    real_stat = os.stat
    monkeypatch.setattr(
        os,
        "stat",
        lambda path, *args, **kwargs: (
            real_stat(device)
            if os.fspath(path) == "/dev/sdc"
            else real_stat(path, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(
        "easymanet.image.unmount_disk",
        lambda *_args: pytest.fail("oversized image reached unmount"),
    )
    monkeypatch.setattr(
        "easymanet.image.open_device_for_write",
        lambda *_args, **_kwargs: pytest.fail("oversized image reached device open"),
    )

    with pytest.raises(FlashError, match="4096.*1024"):
        flash_image("/dev/sdc", str(image), force=True, skip_overlay_wipe=True)

    assert device.read_bytes() == b"untouched"


def _macos_boot_os(
    monkeypatch, tmp_path, *, mounted=True, wrong_parent=False, wrong_filesystem=False
):
    boot = tmp_path / "Boot Volume"
    boot.mkdir()
    disk_file = tmp_path / "disk-node"
    part_file = tmp_path / "partition-node"
    disk_file.touch()
    part_file.touch()
    real_stat = os.stat
    filesystem_device = boot.stat().st_dev

    def stat_device(path, *args, **kwargs):
        if os.fspath(path) in {"/dev/disk4", "/dev/disk4s1"}:
            backing = disk_file if os.fspath(path) == "/dev/disk4" else part_file
            result = real_stat(backing)
            fields = {
                name: getattr(result, name)
                for name in dir(result)
                if name.startswith("st_")
            }
            fields["st_rdev"] = filesystem_device + int(wrong_filesystem)
            return SimpleNamespace(**fields)
        return real_stat(path, *args, **kwargs)

    def check_output(cmd, **_kwargs):
        if cmd[:3] == ["diskutil", "list", "-plist"]:
            return plistlib.dumps(
                {
                    "AllDisksAndPartitions": [
                        {
                            "DeviceIdentifier": "disk4",
                            "Partitions": [
                                {
                                    "DeviceIdentifier": "disk4s1",
                                    "Content": "Windows_FAT_32",
                                }
                            ],
                        }
                    ]
                }
            )
        if cmd[:3] == ["diskutil", "info", "-plist"]:
            return plistlib.dumps(
                {
                    "DeviceIdentifier": "disk4s1",
                    "DeviceNode": "/dev/disk4s1",
                    "ParentWholeDisk": "disk9" if wrong_parent else "disk4",
                    "FilesystemType": "msdos",
                    "MountPoint": str(boot) if mounted else "",
                }
            )
        if cmd == ["mount"]:
            return f"/dev/disk4s1 on {boot} (msdos, local)\n".encode()
        raise AssertionError(cmd)

    monkeypatch.setattr(os, "stat", stat_device)
    monkeypatch.setattr("easymanet.inject.is_macos", lambda: True)
    monkeypatch.setattr("easymanet.inject.is_linux", lambda: False)
    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    return boot, disks.capture_device_identity("/dev/disk4")


def test_boot_volume_with_spaces_receives_real_payload(monkeypatch, tmp_path):
    boot, identity = _macos_boot_os(monkeypatch, tmp_path)
    manifest = load_manifest(os.path.join(ROOT, "examples/three-node-field-mesh.yml"))
    node_name = next(iter(manifest.nodes))

    inject("/dev/disk4", manifest, node_name, device_identity=identity)

    assert (boot / "easymanet/provision.json").is_file()
    assert not (tmp_path / "Boot/easymanet/provision.json").exists()


@pytest.mark.parametrize(
    "failure", ["missing_mount", "wrong_parent", "wrong_filesystem"]
)
def test_unproven_boot_volume_leaves_no_host_credentials(
    monkeypatch, tmp_path, failure
):
    _boot, identity = _macos_boot_os(
        monkeypatch,
        tmp_path,
        mounted=failure != "missing_mount",
        wrong_parent=failure == "wrong_parent",
        wrong_filesystem=failure == "wrong_filesystem",
    )
    manifest = load_manifest(os.path.join(ROOT, "examples/three-node-field-mesh.yml"))

    with pytest.raises(InjectError):
        inject(
            "/dev/disk4", manifest, next(iter(manifest.nodes)), device_identity=identity
        )

    assert not list(tmp_path.rglob("provision.json"))


def test_recursive_descendant_mounts_are_unmounted_deepest_first(monkeypatch):
    mapper = {"name": "dm-1", "type": "crypt", "mountpoint": "/media/Card Data/nested"}
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "mountpoint": "/"}], rm=False),
        _disk(
            "sdb",
            [
                {
                    "name": "sdb1",
                    "type": "part",
                    "mountpoint": "/media/Card Data",
                    "children": [mapper],
                }
            ],
        ),
    ]
    _linux_os(monkeypatch, devices, {"/": "/dev/sda1"})
    calls = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    linux.unmount_disk_linux("/dev/sdb")

    assert calls == [
        ["umount", "/media/Card Data/nested"],
        ["umount", "/media/Card Data"],
    ]


def test_system_array_is_rejected_before_any_unmount(monkeypatch):
    array = {"name": "md0", "type": "raid1", "mountpoint": "/"}
    _linux_os(
        monkeypatch,
        [_disk("sdb", [{"name": "sdb1", "type": "part", "children": [array]}])],
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("system array must not be unmounted"),
    )

    with pytest.raises(RuntimeError, match="system disk"):
        linux.unmount_disk_linux("/dev/sdb")


def test_symlinked_payload_directory_cannot_receive_credentials(monkeypatch, tmp_path):
    boot, identity = _macos_boot_os(monkeypatch, tmp_path)
    host = tmp_path / "host-directory"
    host.mkdir()
    (boot / "easymanet").symlink_to(host, target_is_directory=True)
    manifest = load_manifest(os.path.join(ROOT, "examples/three-node-field-mesh.yml"))

    with pytest.raises(InjectError):
        inject(
            "/dev/disk4", manifest, next(iter(manifest.nodes)), device_identity=identity
        )

    assert not list(host.iterdir())


def test_opened_boot_directory_stays_bound_when_mount_path_is_replaced(
    monkeypatch, tmp_path
):
    boot, identity = _macos_boot_os(monkeypatch, tmp_path)
    detached = tmp_path / "detached-boot"
    real_open = os.open
    replaced = False

    def replace_after_open(path, flags, *args, **kwargs):
        nonlocal replaced
        fd = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == str(boot) and not replaced:
            replaced = True
            boot.rename(detached)
            boot.mkdir()
        return fd

    monkeypatch.setattr(os, "open", replace_after_open)
    manifest = load_manifest(os.path.join(ROOT, "examples/three-node-field-mesh.yml"))

    inject("/dev/disk4", manifest, next(iter(manifest.nodes)), device_identity=identity)

    assert (detached / "easymanet/provision.json").is_file()
    assert not list(boot.iterdir())


@pytest.mark.parametrize("broken_graph", ["missing_parent", "cycle"])
def test_incomplete_or_cyclic_backing_graph_is_never_accepted(
    monkeypatch, broken_graph
):
    logical = {"name": "md0", "type": "raid1", "pkname": "missing-disk"}
    if broken_graph == "cycle":
        logical = {
            "name": "md0",
            "type": "raid1",
            "children": [
                {
                    "name": "dm-0",
                    "type": "crypt",
                    "children": [{"name": "md0", "type": "raid1"}],
                }
            ],
        }
    devices = [
        _disk("sda", [{"name": "sda1", "type": "part", "children": [logical]}]),
        _disk("sdc"),
    ]
    _linux_os(monkeypatch, devices)

    with pytest.raises(ValueError, match="resolve"):
        disks.assert_flash_allowed("/dev/sdc", force=True)


@pytest.mark.parametrize("capacity", [0, 4096])
def test_capacity_must_be_known_and_exact_fit_is_accepted(
    monkeypatch, tmp_path, capacity
):
    device = tmp_path / "disk"
    device.touch()
    image = tmp_path / "firmware.img"
    image.write_bytes(b"x" * 4096)
    monkeypatch.setattr(
        "easymanet.image.assert_flash_allowed",
        lambda *_args, **_kwargs: disks.DiskInfo(
            str(device), size_bytes=capacity, removable=True
        ),
    )

    if capacity == 0:
        with pytest.raises(FlashError, match="capacity"):
            flash_image(str(device), str(image), dry_run=True)
    else:
        identity = flash_image(str(device), str(image), dry_run=True)
        assert identity.path == str(device)
    assert device.read_bytes() == b""


def _macos_apfs_os(monkeypatch, *, root_kind="snapshot", fusion=False, failure=""):
    stores = [{"DeviceIdentifier": "disk0s2"}]
    if fusion:
        stores.append({"DeviceIdentifier": "disk1s2"})
    volume = {"DeviceIdentifier": "disk3s1", "MountedSnapshots": []}
    if root_kind == "snapshot":
        volume["MountedSnapshots"] = [{"SnapshotBSD": "disk3s1s1", "SnapshotMountPoint": "/"}]
    elif root_kind == "volume":
        volume["MountPoint"] = "/"
    volumes = [volume]
    if root_kind == "snapshot-volume":
        volumes.append({"DeviceIdentifier": "disk3s1s1", "MountPoint": "/"})
    container = {
        "DeviceIdentifier": "disk3",
        "Content": "EF57347C-0000-11AA-AA11-00306543ECAC",
        "Partitions": [],
        "APFSPhysicalStores": stores,
        "APFSVolumes": volumes,
    }
    if failure == "missing-stores":
        container.pop("APFSPhysicalStores")
    elif failure == "unknown-store":
        stores.append({"DeviceIdentifier": "disk99s2"})
    elif failure == "missing-root":
        volume["MountedSnapshots"] = []
    entries = [
        {
            "DeviceIdentifier": identifier,
            "Size": 32 * 1024**3,
            "Partitions": [{"DeviceIdentifier": f"{identifier}s2", "MountPoint": ""}],
        }
        for identifier in ("disk0", "disk1", "disk4", "disk5")
    ]
    entries.extend([
        container,
        {
            "DeviceIdentifier": "disk6",
            "APFSPhysicalStores": [{"DeviceIdentifier": "disk5s2"}],
            "APFSVolumes": [{"DeviceIdentifier": "disk6s1", "MountPoint": "/Volumes/Archive"}],
        },
    ])
    listing = {"WholeDisks": [entry["DeviceIdentifier"] for entry in entries], "AllDisksAndPartitions": entries}

    def check_output(cmd, **_kwargs):
        if cmd == ["diskutil", "list", "-plist", "external"]:
            return plistlib.dumps({"AllDisksAndPartitions": [entries[2], entries[3]]})
        if cmd == ["diskutil", "list", "-plist"]:
            if failure == "inventory-error":
                raise subprocess.CalledProcessError(1, cmd)
            return plistlib.dumps(listing)
        if cmd[:3] == ["diskutil", "info", "-plist"]:
            return plistlib.dumps({"MountPoint": ""})
        if cmd[:2] == ["diskutil", "info"]:
            virtual = "Yes" if cmd[2] in {"/dev/disk3", "/dev/disk6"} else "No"
            return (
                "Device / Media Name: Fixture media\n"
                "Disk Size: 32.0 GB (34359738368 Bytes)\n"
                f"Virtual: {virtual}\nDevice Location: External\nRemovable Media: Removable\n"
            ).encode()
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(macos.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(disk_core, "is_macos", lambda: True)
    monkeypatch.setattr(disk_core, "is_linux", lambda: False)
    monkeypatch.setattr(disk_core, "_is_block_device", lambda _path: True)


@pytest.mark.parametrize("root_kind", ["volume", "snapshot", "snapshot-volume"])
@pytest.mark.parametrize("fusion", [False, True], ids=["single-store", "fusion"])
def test_apfs_root_media_is_hard_blocked_and_unrelated_media_is_usable(monkeypatch, root_kind, fusion):
    _macos_apfs_os(monkeypatch, root_kind=root_kind, fusion=fusion)

    found = {disk.device: disk for disk in disks.list_disks(include_all=True)}

    protected = {"/dev/disk0", "/dev/disk3"}
    if fusion:
        protected.add("/dev/disk1")
    assert {device for device, disk in found.items() if disk.is_system} == protected
    for device in protected:
        assert "/" in found[device].mounted
        with pytest.raises(ValueError, match="system disk"):
            disks.assert_flash_allowed(device, force=True)
    for device in ("/dev/disk4", "/dev/disk5"):
        assert not disks.assert_flash_allowed(device).is_system
    assert "/Volumes/Archive" in found["/dev/disk5"].mounted
    assert not disks.lookup_device("/dev/rdisk4").safety_error


@pytest.mark.parametrize("failure", ["missing-stores", "unknown-store", "missing-root", "inventory-error"])
def test_unresolved_macos_system_relationship_blocks_without_false_system_label(monkeypatch, failure):
    _macos_apfs_os(monkeypatch, failure=failure)

    disk = disks.lookup_device("/dev/disk4")

    assert disk is not None
    assert not disk.is_system
    assert disk.safety_error
    with pytest.raises(ValueError, match="resolve"):
        disks.assert_flash_allowed("/dev/disk4", force=True)
