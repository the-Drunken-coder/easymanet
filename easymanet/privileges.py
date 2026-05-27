"""Privilege detection for disk writes.

On macOS, raw disk access requires sudo from a real terminal session.
We detect when privileges are needed and provide a clear message.
"""

import os


class PrivilegeError(Exception):
    pass


def is_running_as_root() -> bool:
    return os.geteuid() == 0


def check_privileges(device: str) -> None:
    del device
    if is_running_as_root():
        return

    raise PrivilegeError(
        "Root privileges are required to write to the disk.\n"
        "Run with sudo, for example:\n"
        "  sudo easymanet flash --config fleet.yml --node manet01 "
        "--device /dev/sdX --yes"
    )
