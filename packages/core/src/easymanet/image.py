"""Low-level OpenMANET image writer for SD cards and USB drives.

This module owns destructive media writes: image file validation, .img/.img.gz
streaming, disk unmounts, stale overlay wipe, sync, and eject. It does not
resolve fleet configs, download images, or stage EasyMANET boot payloads.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from ._image_dd import (
    ceil_div as _ceil_div_value,
    command_error_message as _command_error_message,
    dd_device_path as _platform_dd_device_path,
    dd_progress_bytes,
    stream_dd_block_args as _platform_stream_dd_block_args,
    stream_dd_device_path as _platform_stream_dd_device_path,
    write_block_size_arg as _platform_write_block_size_arg,
)
from ._download_integrity import normalize_sha256
from .disks import (
    DeviceIdentity,
    DiskInfo,
    assert_device_identity,
    assert_flash_allowed,
    capture_device_identity,
    get_partition2_wipe_range,
    open_device_for_write,
    unmount_disk,
    eject_disk,
)
from .platform import is_linux, is_macos


class FlashError(Exception):
    pass


FlashEventCallback = Callable[[dict[str, Any]], None]
_MACOS_GZIP_WRITE_CHUNK_BYTES = 1024 * 1024
_IMAGE_READ_BYTES = 1024 * 1024


def _gzip_env() -> dict[str, str]:
    return {**os.environ, "LANG": "C", "LC_ALL": "C"}


def _emit_event(
    emit: FlashEventCallback | None,
    event_type: str,
    message: str,
    **data: Any,
) -> None:
    if emit:
        emit({"type": event_type, "message": message, **data})


def _tool_path(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FlashError(f"Required tool not found on PATH: {name}")
    return path


def _check_device_safety(
    device: str,
    force: bool = False,
) -> tuple[DiskInfo, DeviceIdentity]:
    identity = _capture_device_identity(device)
    try:
        disk = assert_flash_allowed(device, force=force)
    except ValueError as e:
        raise FlashError(str(e)) from e
    if disk.device != device:
        raise FlashError(
            f"Safety check resolved {device} as {disk.device}; use the canonical device path."
        )
    _assert_device_identity(identity)
    return disk, identity


def _capture_device_identity(path: str) -> DeviceIdentity:
    try:
        return capture_device_identity(path)
    except (OSError, ValueError) as exc:
        raise FlashError(f"Could not capture device identity for {path}: {exc}") from exc


def _assert_device_identity(expected: DeviceIdentity) -> None:
    try:
        assert_device_identity(expected)
    except ValueError as exc:
        raise FlashError(str(exc)) from exc


def _open_device_for_write(
    expected: DeviceIdentity,
    *,
    companions: tuple[DeviceIdentity, ...] = (),
) -> int:
    try:
        return open_device_for_write(expected, companions=companions)
    except (OSError, ValueError) as exc:
        raise FlashError(str(exc)) from exc


def _unmount_or_raise(device: str) -> None:
    try:
        unmount_disk(device)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        raise FlashError(f"Failed to unmount {device}: {e}") from e


def _open_image(image_path: str) -> tuple[Path, int]:
    image = Path(image_path)
    suffix = image.suffix.lower()
    if suffix == ".gz" and not image.stem.lower().endswith(".img"):
        raise FlashError(f"Expected .img.gz file, got: {image_path}")
    if suffix not in {".img", ".gz"}:
        raise FlashError(
            f"Unsupported image format: {image_path}. Expected .img or .img.gz"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        return image, os.open(image, flags)
    except OSError as exc:
        raise FlashError(f"Base image not found or unreadable: {image_path}: {exc}") from exc


def _check_image(
    image_path: str,
    expected_sha256: str | None = None,
) -> Tuple[Path, Optional[int]]:
    """Validate one image object and return its decompressed size when gzipped."""
    image, image_fd = _open_image(image_path)
    try:
        return image, _check_open_image(image, image_fd, expected_sha256)
    finally:
        os.close(image_fd)


def _check_open_image(
    image: Path,
    image_fd: int,
    expected_sha256: str | None,
) -> int | None:
    size = os.fstat(image_fd).st_size
    if size <= 0:
        raise FlashError(f"Base image is empty: {image}")
    if expected_sha256:
        try:
            expected = normalize_sha256(expected_sha256)
        except ValueError as exc:
            raise FlashError(f"Invalid image SHA-256: {exc}") from exc
        actual = _sha256_fd(image_fd)
        if actual != expected:
            raise FlashError(
                f"SHA-256 mismatch for {image.name}: expected {expected}, got {actual}"
            )
    if image.suffix.lower() != ".gz":
        return None
    try:
        written_bytes = _gzip_decompressed_bytes(image_fd)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FlashError(f"Invalid gzip-compressed image {image}: {exc}") from exc
    if written_bytes <= 0:
        raise FlashError(
            f"Invalid gzip-compressed image {image}: compressed image did not contain a disk image payload"
        )
    return written_bytes


def _sha256_fd(image_fd: int) -> str:
    hasher = hashlib.sha256()
    offset = 0
    while True:
        chunk = os.pread(image_fd, _IMAGE_READ_BYTES, offset)
        if not chunk:
            return hasher.hexdigest()
        hasher.update(chunk)
        offset += len(chunk)


def _gzip_decompressed_bytes(image_fd: int) -> int:
    os.lseek(image_fd, 0, os.SEEK_SET)
    gzip_cmd = [_tool_path("gzip"), "-dc"]
    with tempfile.TemporaryFile() as gzip_stderr_file:
        gzip_proc = subprocess.Popen(
            gzip_cmd,
            env=_gzip_env(),
            stdin=image_fd,
            stdout=subprocess.PIPE,
            stderr=gzip_stderr_file,
        )
        assert gzip_proc.stdout is not None
        total = 0
        try:
            for chunk in iter(
                lambda: gzip_proc.stdout.read(_IMAGE_READ_BYTES),
                b"",
            ):
                total += len(chunk)
        except BaseException:
            gzip_proc.kill()
            gzip_proc.wait()
            raise
        finally:
            gzip_proc.stdout.close()
        gzip_return = gzip_proc.wait()
        gzip_stderr_file.seek(0)
        gzip_stderr = _decode_subprocess_output(gzip_stderr_file.read())
    _check_gzip_result(gzip_return, gzip_cmd, gzip_stderr)
    return total


def _check_gzip_result(return_code: int, command: list[str], stderr: str) -> None:
    if return_code == 0:
        return
    if return_code == 2 and "trailing garbage ignored" in stderr.lower():
        return
    raise subprocess.CalledProcessError(return_code, command, stderr=stderr)


def _reread_partition_table(device: str) -> None:
    if is_linux():
        try:
            _run_reread_partition_command([_tool_path("blockdev"), "--rereadpt", device], device)
        except FlashError:
            _run_reread_partition_command([_tool_path("partprobe"), device], device)
    elif is_macos():
        _run_reread_partition_command([_tool_path("diskutil"), "list", device], device)


def _run_reread_partition_command(cmd: list[str], device: str) -> None:
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise FlashError(
            f"Failed to re-read partition table for {device} with {cmd[0]}{suffix}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise FlashError(
            f"Timed out re-reading partition table for {device} with {cmd[0]}"
        ) from e
    except OSError as e:
        raise FlashError(
            f"Failed to re-read partition table for {device} with {cmd[0]}: {e}"
        ) from e


def flash_image(
    device: str,
    image_path: str,
    dry_run: bool = False,
    force: bool = False,
    skip_overlay_wipe: bool = False,
    expected_sha256: str | None = None,
    emit: FlashEventCallback | None = None,
) -> DeviceIdentity:
    image, image_fd = _open_image(image_path)
    try:
        gzip_written_bytes = _check_open_image(
            image,
            image_fd,
            expected_sha256,
        )
        disk, device_identity = _check_device_safety(device, force=force)

        _emit_event(
            emit,
            "disk_details",
            f"Device: {disk.device}",
            device=disk.device,
            model=disk.model,
            size_human=disk.size_human,
            mounted=disk.mounted,
            removable=disk.removable,
        )

        if dry_run:
            return device_identity

        device = disk.device
        write_path = (
            _stream_dd_device_path(device)
            if image.suffix == ".gz"
            else _dd_device_path(device)
        )
        write_identity = (
            device_identity
            if write_path == device
            else _capture_device_identity(write_path)
        )
        overlay_path = _dd_device_path(device)
        overlay_identity = (
            device_identity
            if overlay_path == device
            else _capture_device_identity(overlay_path)
        )

        try:
            _assert_device_identity(device_identity)
            _unmount_or_raise(device)
            _emit_event(
                emit,
                "write_started",
                f"Writing {image.name} to {device}...",
                image=image.name,
                device=device,
            )
            companions = () if write_identity == device_identity else (device_identity,)
            device_fd = _open_device_for_write(write_identity, companions=companions)
            try:
                if image.suffix == ".gz":
                    _write_gz_via_dd(image_fd, device_fd, emit=emit)
                else:
                    _write_raw_via_dd(image_fd, device_fd, emit=emit)
            finally:
                os.close(device_fd)

            _emit_event(emit, "sync_started", "Syncing...")
            os.sync()
            _emit_event(emit, "write_completed", "Done writing.")

            if not skip_overlay_wipe:
                written_bytes = (
                    gzip_written_bytes
                    if gzip_written_bytes is not None
                    else os.fstat(image_fd).st_size
                )
                _clear_stale_overlay(
                    device,
                    written_bytes,
                    device_identity=device_identity,
                    output_identity=overlay_identity,
                    emit=emit,
                )
            return device_identity

        except subprocess.CalledProcessError as e:
            raise FlashError(f"Flash failed: {_command_error_message(e)}") from e
        except FlashError:
            raise
        except (OSError, subprocess.SubprocessError) as e:
            raise FlashError(f"Flash failed: {e}") from e
    finally:
        os.close(image_fd)


def _write_gz_via_dd(
    image_fd: int,
    output_fd: int,
    *,
    emit: FlashEventCallback | None = None,
) -> None:
    if is_macos():
        _write_gz_via_macos_stream(image_fd, output_fd, emit=emit)
        return

    os.lseek(image_fd, 0, os.SEEK_SET)
    gzip_cmd = [_tool_path("gzip"), "-dc"]
    dd_cmd = [
        _tool_path("dd"),
        *_stream_dd_block_args(),
        "status=progress",
    ]
    with tempfile.TemporaryFile() as gzip_stderr_file:
        gzip_proc = subprocess.Popen(
            gzip_cmd,
            env=_gzip_env(),
            stdin=image_fd,
            stdout=subprocess.PIPE,
            stderr=gzip_stderr_file,
        )
        assert gzip_proc.stdout is not None
        dd_kwargs: dict[str, Any] = {
            "stdin": gzip_proc.stdout,
            "stdout": output_fd,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        dd_proc = subprocess.Popen(dd_cmd, **dd_kwargs)
        gzip_proc.stdout.close()

        if emit is None:
            _dd_stdout, dd_stderr = dd_proc.communicate()
        else:
            dd_stderr = _drain_dd_progress(dd_proc, emit)
        dd_return = dd_proc.wait()
        gzip_return = gzip_proc.wait()
        gzip_stderr_file.seek(0)
        gzip_stderr = _decode_subprocess_output(gzip_stderr_file.read())

    if dd_return != 0:
        raise subprocess.CalledProcessError(dd_return, dd_cmd, stderr=dd_stderr)
    _check_gzip_result(gzip_return, gzip_cmd, gzip_stderr)


def _write_gz_via_macos_stream(
    image_fd: int,
    output_fd: int,
    *,
    emit: FlashEventCallback | None = None,
) -> None:
    os.lseek(image_fd, 0, os.SEEK_SET)
    gzip_cmd = [_tool_path("gzip"), "-dc"]
    with tempfile.TemporaryFile() as gzip_stderr_file:
        gzip_proc = subprocess.Popen(
            gzip_cmd,
            env=_gzip_env(),
            stdin=image_fd,
            stdout=subprocess.PIPE,
            stderr=gzip_stderr_file,
        )
        assert gzip_proc.stdout is not None
        write_error: OSError | None = None
        try:
            _write_stream_to_fd(gzip_proc.stdout, output_fd, emit=emit)
        except OSError as exc:
            write_error = exc
            gzip_proc.kill()

        gzip_proc.communicate()
        gzip_stderr_file.seek(0)
        gzip_stderr = _decode_subprocess_output(gzip_stderr_file.read())
    if write_error is not None:
        raise write_error
    _check_gzip_result(gzip_proc.returncode, gzip_cmd, gzip_stderr)


def _write_stream_to_fd(
    stream: Any,
    fd: int,
    *,
    emit: FlashEventCallback | None = None,
) -> None:
    total_written = 0
    while True:
        chunk = stream.read(_MACOS_GZIP_WRITE_CHUNK_BYTES)
        if not chunk:
            break
        _write_all(fd, chunk)
        total_written += len(chunk)
        _emit_dd_progress(f"{total_written} bytes transferred", emit)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written == 0:
            raise OSError("write returned 0 bytes")
        view = view[written:]


def _decode_subprocess_output(output: Any) -> str:
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return str(output or "")


_OVERLAY_WIPE_SECTOR_BYTES = 512
_OVERLAY_WIPE_BULK_BYTES = 16 * 1024 * 1024


def _dd_device_path(device: str) -> str:
    return _platform_dd_device_path(device, macos=is_macos())


def _stream_dd_device_path(device: str) -> str:
    return _platform_stream_dd_device_path(device, macos=is_macos())


def _stream_dd_block_args() -> list[str]:
    return _platform_stream_dd_block_args(macos=is_macos())


def _write_block_size_arg() -> str:
    return _platform_write_block_size_arg(macos=is_macos())


def _ceil_div(numerator: int, denominator: int) -> int:
    return _ceil_div_value(numerator, denominator)


def _run_zero_dd(
    output_fd: int,
    block_bytes: int,
    seek_blocks: int,
    count_blocks: int,
    *,
    emit: FlashEventCallback | None = None,
) -> None:
    if count_blocks <= 0:
        return

    # Every dd phase inherits the same open file description. Reset it because
    # dd's seek is relative to the descriptor's current output position.
    os.lseek(output_fd, 0, os.SEEK_SET)
    _run_dd_with_progress(
        [
            _tool_path("dd"),
            "if=/dev/zero",
            f"bs={block_bytes}",
            f"seek={seek_blocks}",
            f"count={count_blocks}",
            "status=progress",
        ],
        output_fd=output_fd,
        emit=emit,
    )


def _clear_stale_overlay(
    device: str,
    written_bytes: int,
    *,
    device_identity: DeviceIdentity,
    output_identity: DeviceIdentity,
    emit: FlashEventCallback | None = None,
) -> None:
    _assert_device_identity(device_identity)
    _reread_partition_table(device)
    _assert_device_identity(device_identity)
    wipe_range = get_partition2_wipe_range(device)
    _assert_device_identity(device_identity)
    if not wipe_range:
        raise FlashError(
            f"Image was written to {device}, but the stale OpenWrt overlay area "
            f"could not be wiped (partition layout unknown).\n"
            f"Re-flash with a known-good image, manually zero partition 2, or re-run with "
            f"--skip-overlay-wipe only if you accept stale config on the drive."
        )

    tail_start, wipe_bytes = wipe_range
    start_bytes = max(tail_start, written_bytes)
    wipe_bytes = wipe_bytes - (start_bytes - tail_start)
    if wipe_bytes <= 0:
        _emit_event(
            emit,
            "overlay_wipe_skipped",
            "Skipping stale overlay wipe; image covers the wipe region.",
        )
        return

    sector_bytes = _OVERLAY_WIPE_SECTOR_BYTES
    bulk_bytes = _OVERLAY_WIPE_BULK_BYTES
    seek_sectors = _ceil_div(start_bytes, sector_bytes)
    aligned_start = seek_sectors * sector_bytes
    span_bytes = wipe_bytes + (aligned_start - start_bytes)
    count_sectors = max(1, _ceil_div(span_bytes, sector_bytes))
    total_mib = count_sectors * sector_bytes / (1024 * 1024)
    _emit_event(
        emit,
        "overlay_wipe_started",
        f"Clearing stale OpenWrt overlay area ({total_mib:.1f} MiB at offset {start_bytes} bytes)...",
        total_mib=total_mib,
        start_bytes=start_bytes,
    )

    companions = () if output_identity == device_identity else (device_identity,)
    # Partition-table probing may auto-mount volumes, so unmount immediately
    # before opening the already-identified raw device node.
    _assert_device_identity(device_identity)
    _unmount_or_raise(device)
    output_fd = _open_device_for_write(output_identity, companions=companions)
    try:
        total_bytes = count_sectors * sector_bytes
        cursor = aligned_start
        if cursor % bulk_bytes:
            prefix_bytes = min(total_bytes, bulk_bytes - (cursor % bulk_bytes))
            prefix_sectors = _ceil_div(prefix_bytes, sector_bytes)
            _run_zero_dd(
                output_fd,
                sector_bytes,
                cursor // sector_bytes,
                prefix_sectors,
                emit=emit,
            )
            prefix_written = prefix_sectors * sector_bytes
            cursor += prefix_written
            total_bytes -= prefix_written

        bulk_blocks = total_bytes // bulk_bytes
        _run_zero_dd(
            output_fd,
            bulk_bytes,
            cursor // bulk_bytes,
            bulk_blocks,
            emit=emit,
        )
        bulk_written = bulk_blocks * bulk_bytes
        cursor += bulk_written
        total_bytes -= bulk_written

        tail_sectors = total_bytes // sector_bytes
        _run_zero_dd(
            output_fd,
            sector_bytes,
            cursor // sector_bytes,
            tail_sectors,
            emit=emit,
        )
    finally:
        os.close(output_fd)


def _write_raw_via_dd(
    image_fd: int,
    output_fd: int,
    *,
    emit: FlashEventCallback | None = None,
) -> None:
    os.lseek(image_fd, 0, os.SEEK_SET)
    _run_dd_with_progress(
        [
            _tool_path("dd"),
            _write_block_size_arg(),
            "status=progress",
        ],
        input_fd=image_fd,
        output_fd=output_fd,
        emit=emit,
    )


def _run_dd_with_progress(
    cmd: list[str],
    *,
    input_fd: int | None = None,
    output_fd: int | None = None,
    emit: FlashEventCallback | None = None,
) -> None:
    input_kwargs = {"stdin": input_fd} if input_fd is not None else {}
    output_kwargs = {"stdout": output_fd} if output_fd is not None else {}
    if emit is None:
        subprocess.run(cmd, check=True, **input_kwargs, **output_kwargs)
        return

    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
        **input_kwargs,
        **output_kwargs,
    )
    stderr = _drain_dd_progress(proc, emit)
    return_code = proc.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd, stderr=stderr)


def _drain_dd_progress(
    proc: subprocess.Popen,
    emit: FlashEventCallback | None,
) -> str:
    stderr_stream = getattr(proc, "stderr", None)
    if stderr_stream is None:
        return ""
    captured = []
    buffer = []
    while True:
        char = stderr_stream.read(1)
        if not char:
            break
        captured.append(char)
        if char in "\r\n":
            _emit_dd_progress("".join(buffer).strip(), emit)
            buffer = []
        else:
            buffer.append(char)
    if buffer:
        _emit_dd_progress("".join(buffer).strip(), emit)
    return "".join(captured)


def _emit_dd_progress(text: str, emit: FlashEventCallback | None) -> None:
    if not text:
        return
    data: dict[str, Any] = {"raw": text}
    bytes_written = dd_progress_bytes(text)
    if bytes_written is not None:
        data["bytes"] = bytes_written
    if emit:
        emit({"type": "dd_progress", "message": text, **data})


def finish_flash(
    device: str,
    *,
    device_identity: DeviceIdentity,
    eject: bool = True,
    emit: FlashEventCallback | None = None,
) -> None:
    os.sync()
    _assert_device_identity(device_identity)
    if eject:
        _emit_event(emit, "eject_started", f"Ejecting {device}...", device=device)
        try:
            eject_disk(device)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            _emit_event(
                emit,
                "eject_failed",
                f"Image written and payload staged, but eject failed. "
                f"Run sync and eject {device} manually before removing it.",
                level="warning",
            )
            raise FlashError(f"Failed to eject {device}: {e}") from e
    else:
        _emit_event(
            emit,
            "unmount_started",
            f"Unmounting {device}...",
            device=device,
        )
        try:
            _unmount_or_raise(device)
        except FlashError as exc:
            _emit_event(
                emit,
                "unmount_failed",
                f"Image written and payload staged, but unmount failed. "
                f"Unmount {device} manually before removing it.",
                level="warning",
            )
            raise
    _emit_event(emit, "safe_to_remove", "Safe to remove.", device=device)
