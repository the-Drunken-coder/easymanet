import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from easymanet.disks import core


FIXTURE = r'''
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import easymanet.flash as flash
import easymanet.image as image
from easymanet.disks import DiskInfo, core

assert Path(core.__file__).resolve().is_relative_to(Path(os.environ["EASYMANET_TEST_CORE"]))

resource, mode, root = sys.argv[1:]
root = Path(root)
core.flash_resource_key = lambda _device: resource
device = root / "inert-device"
firmware = root / "firmware.img"
firmware.write_bytes(b"image")
device.touch(exist_ok=True)
disk = DiskInfo(str(device), size_bytes=8192, model="Inert media", removable=True)

if mode.startswith("child-"):
    writer = root / "inert-dd"
    writer.write_text("#!" + sys.executable + "\n" + "\n".join([
        "import os, time",
        "from pathlib import Path",
        "root = Path(" + repr(str(root)) + ")",
        "(root / 'child-ready').write_text(str(os.getpid()))",
        "while not (root / 'release-child').exists(): time.sleep(0.01)",
    ]) + "\n")
    writer.chmod(0o700)
    image._tool_path = lambda name: str(writer) if name == "dd" else shutil.which(name)
    image.is_macos = lambda: False
    image._reread_partition_table = lambda _device, **_kwargs: None
    image._unmount_or_raise = lambda _device, **_kwargs: None
    image.get_partition2_wipe_range = lambda _device: (512, 2048)
    image.open_device_for_write = lambda identity, **_kwargs: os.open(identity.path, os.O_WRONLY)
    identity = core.capture_device_identity(str(device))
    if mode == "child-eject":
        (root / "eject").symlink_to(writer)
        os.environ["PATH"] = str(root) + os.pathsep + os.environ["PATH"]
        core.is_macos = lambda: False
        core.is_linux = lambda: True
        image.os.sync = lambda: None
        flash.check_platform = lambda: None
        flash.lookup_device = lambda _device: disk
        flash.assert_flash_allowed = lambda *_args, **_kwargs: disk
        flash.check_privileges = lambda _device: None
        flash.flash_image = lambda **_kwargs: identity
        flash.inject = lambda **_kwargs: [("/inert/provision.json", True)]
        result = flash.run_flash_workflow(flash.FlashOptions(
            config="examples/three-node-field-mesh.yml", node="point01", device=str(device),
            base_image=str(firmware), yes=True,
        ))
        print(json.dumps(result.to_dict()), flush=True)
        sys.exit(0)
    with core.flash_device_guard(str(device)) as admission_fd:
        image_fd = os.open(firmware, os.O_RDONLY)
        output_fd = os.open(device, os.O_WRONLY)
        try:
            if mode == "child-raw":
                image._write_raw_via_dd(image_fd, output_fd, admission_fd=admission_fd)
            elif mode == "child-gzip":
                compressed = root / "firmware.img.gz"
                compressed.write_bytes(gzip.compress(b"image"))
                os.close(image_fd)
                image_fd = os.open(compressed, os.O_RDONLY)
                image._write_gz_via_dd(image_fd, output_fd, admission_fd=admission_fd)
            else:
                image._clear_stale_overlay(
                    str(device), 0, device_identity=identity, output_identity=identity,
                    admission_fd=admission_fd,
                )
        finally:
            os.close(image_fd)
            os.close(output_fd)
    sys.exit(0)

flash.check_platform = lambda: None
flash.lookup_device = lambda _device: disk
flash.assert_flash_allowed = lambda *_args, **_kwargs: disk
flash.check_privileges = lambda _device: None

def step(label):
    print(label, flush=True)
    if mode == "hold":
        if sys.stdin.readline().strip() != "advance":
            raise RuntimeError("Inert workflow was not released")

def write(**kwargs):
    step("writer")
    return core.capture_device_identity(str(device))

def inject(**kwargs):
    step("inject")
    return [("/inert/provision.json", True)]

def finish(*args, **kwargs):
    step("finish")

flash.flash_image = write
flash.inject = inject
flash.finish_flash = finish
result = flash.run_flash_workflow(flash.FlashOptions(
    config="examples/three-node-field-mesh.yml", node="point01", device=str(device),
    base_image=str(firmware), yes=True,
))
print(json.dumps(result.to_dict()), flush=True)
'''


@pytest.fixture
def admission_fixture(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "packages/core/src"
    monkeypatch.setenv("PYTHONPATH", str(source))
    monkeypatch.setenv("EASYMANET_TEST_CORE", str(source))
    resource = f"inert-{uuid4()}"
    fixture = tmp_path / "inert_workflow.py"
    fixture.write_text(FIXTURE)
    monkeypatch.setattr(core, "flash_resource_key", lambda _device: resource)
    lock = Path(f"/tmp/easymanet-media-{hashlib.sha256(resource.encode()).hexdigest()}.lock")
    yield resource, fixture, tmp_path, lock
    lock.unlink(missing_ok=True)


def _run(fixture, resource, root, *, workspace):
    result = subprocess.run(
        [sys.executable, str(fixture), resource, "try", str(root)],
        env={**os.environ, "EASYMANET_WORKSPACE": str(workspace)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    import json

    return json.loads(result.stdout.splitlines()[-1])


def test_core_admission_covers_write_inject_and_finish_across_workspaces(admission_fixture):
    resource, fixture, root, lock = admission_fixture
    process = subprocess.Popen(
        [sys.executable, str(fixture), resource, "hold", str(root)],
        env={**os.environ, "EASYMANET_WORKSPACE": str(root / "workspace-a")},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdin is not None
        for phase in ("writer", "inject", "finish"):
            assert process.stdout.readline().strip() == phase
            inode = lock.stat().st_ino
            assert stat.S_IMODE(lock.stat().st_mode) == 0o666
            contender = _run(fixture, resource, root, workspace=root / "workspace-b")
            assert contender["ok"] is False
            assert contender["code"] == "disk_safety"
            assert "Another EasyMANET process" in contender["errors"][0]
            assert lock.stat().st_ino == inode
            process.stdin.write("advance\n")
            process.stdin.flush()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert '"ok": true' in stdout
        assert _run(fixture, resource, root, workspace=root / "workspace-b")["ok"] is True
        assert lock.stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("phase", ["raw", "gzip", "overlay", "eject"])
def test_inherited_admission_survives_parent_termination(admission_fixture, phase):
    resource, fixture, root, _lock = admission_fixture
    process = subprocess.Popen(
        [sys.executable, str(fixture), resource, f"child-{phase}", str(root)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    ready = root / "child-ready"
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None, process.stderr.read()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        process.kill()
        process.wait(timeout=10)
        contender = _run(fixture, resource, root, workspace=root / "other-workspace")
        assert contender["ok"] is False
        assert contender["code"] == "disk_safety"
        (root / "release-child").touch()
        deadline = time.monotonic() + 10
        while True:
            try:
                with core.flash_device_guard("/inert"):
                    break
            except ValueError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        assert _run(fixture, resource, root, workspace=root / "other-workspace")["ok"] is True
    finally:
        (root / "release-child").touch()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_existing_lock_is_shared_without_creating_or_truncating(admission_fixture, monkeypatch):
    _resource, _fixture, _root, lock = admission_fixture
    lock.write_text("preserved contents")
    lock.chmod(0o666)
    inode = lock.stat().st_ino
    original_open = os.open

    def protected_open(path, flags, *args, **kwargs):
        if str(path) == str(lock) and flags & os.O_CREAT and not flags & os.O_EXCL:
            raise PermissionError("Linux protected_regular")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", protected_open)
    with core.flash_device_guard("/inert"):
        assert lock.stat().st_ino == inode
    assert lock.read_text() == "preserved contents"


@pytest.mark.parametrize("kind", ["symlink", "directory", "hardlink"])
def test_admission_rejects_nonregular_or_aliased_lock_files(admission_fixture, kind):
    _resource, _fixture, root, lock = admission_fixture
    if kind == "symlink":
        target = root / "target"
        target.touch()
        lock.symlink_to(target)
    elif kind == "directory":
        lock.mkdir()
    else:
        target = root / "target"
        target.touch()
        os.link(target, lock)
    try:
        with pytest.raises(ValueError):
            with core.flash_device_guard("/inert"):
                pytest.fail("Invalid lockfile admitted a writer")
    finally:
        if kind == "directory":
            lock.rmdir()


def test_mac_raw_and_block_aliases_share_the_same_resource(monkeypatch):
    monkeypatch.setattr(core, "is_macos", lambda: True)
    assert core.flash_resource_key("/dev/rdisk7") == core.flash_resource_key("/dev/disk7")
    with pytest.raises(ValueError):
        core.flash_resource_key("/dev/disk7s1")


def test_linux_device_aliases_share_the_device_number(monkeypatch):
    monkeypatch.setattr(core, "is_macos", lambda: False)
    monkeypatch.setattr(core, "is_linux", lambda: True)
    monkeypatch.setattr(os, "stat", lambda _path: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 32)))
    assert core.flash_resource_key("/dev/sdc") == core.flash_resource_key("/dev/disk/by-id/inert-alias")
