"""Disk detection and listing for macOS and Linux."""

from ._common import (
    DISK_PARSE_ERRORS,
    DISK_SUSPICIOUS_SIZE_GB,
    DISK_WARN_THRESHOLD_GB,
    OVERLAY_WIPE_BLOCK_MIB,
    OVERLAY_WIPE_BLOCKS,
    SYS_MOUNT_POINTS,
    DiskInfo,
    debug_note,
)
from .core import (
    DeviceIdentity,
    assert_flash_allowed,
    assert_device_identity,
    capture_device_identity,
    eject_disk,
    get_partition2_wipe_range,
    list_disks,
    lookup_device,
    open_device_for_write,
    unmount_disk,
)

__all__ = [
    "DISK_PARSE_ERRORS",
    "DISK_SUSPICIOUS_SIZE_GB",
    "DISK_WARN_THRESHOLD_GB",
    "DeviceIdentity",
    "DiskInfo",
    "OVERLAY_WIPE_BLOCK_MIB",
    "OVERLAY_WIPE_BLOCKS",
    "SYS_MOUNT_POINTS",
    "assert_flash_allowed",
    "assert_device_identity",
    "capture_device_identity",
    "debug_note",
    "eject_disk",
    "get_partition2_wipe_range",
    "list_disks",
    "lookup_device",
    "open_device_for_write",
    "unmount_disk",
]
