import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from easymanet import image
from easymanet.disks import DiskInfo
from easymanet.disks import core as disk_core


def sink(root: Path, source: Path) -> None:
    descriptor = os.fstat(sys.stdin.fileno())
    (root / "child.json").write_text(json.dumps({
        "pid": os.getpid(), "links": descriptor.st_nlink, "size": descriptor.st_size,
    }))
    deadline = time.monotonic() + 15
    while not (root / "release").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Inert sink was never released")
        time.sleep(0.01)
    if source.suffix == ".gz":
        with gzip.GzipFile(fileobj=sys.stdin.buffer) as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
    else:
        shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)
    sys.stdout.buffer.flush()
    (root / "complete").touch()


def writer(root: Path, source: Path) -> None:
    target = root / "target"
    resource = f"inert-snapshot:{root}"
    disk_core.flash_resource_key = lambda _device: resource
    image.assert_flash_allowed = lambda _device, force=False: DiskInfo(
        str(target), size_bytes=65536, removable=True,
    )
    image.unmount_disk = lambda *_args, **_kwargs: None
    image.os.sync = lambda: None

    def inherited_sink(source_fd: int, target_fd: int, **_kwargs) -> None:
        os.lseek(source_fd, 0, os.SEEK_SET)
        subprocess.run(
            [sys.executable, __file__, "sink", str(root), str(source)],
            stdin=source_fd, stdout=target_fd, check=True,
        )

    image._write_raw_via_dd = inherited_sink
    image._write_gz_via_dd = inherited_sink
    lock_digest = hashlib.sha256(resource.encode()).hexdigest()
    try:
        image.flash_image(
            str(target), str(source), skip_overlay_wipe=True,
            expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    finally:
        Path(f"/tmp/easymanet-media-{lock_digest}.lock").unlink(missing_ok=True)


if __name__ == "__main__":
    role, root_path, source_path = sys.argv[1:]
    operation = sink if role == "sink" else writer
    operation(Path(root_path), Path(source_path))
