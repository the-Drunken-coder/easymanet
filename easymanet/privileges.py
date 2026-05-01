"""Privilege detection for disk writes.

On macOS, raw disk access requires sudo from a real terminal session.
We detect when privileges are needed and provide a clear message.
"""

import os


def is_running_as_root() -> bool:
    return os.geteuid() == 0


def check_privileges(device: str) -> None:
    if is_running_as_root():
        return

    print()
    print("Root privileges are required to write to the disk.")
    print()
    print("Run with sudo:")
    print(f"  sudo easymanet flash --config fleet.yml --node manet01 --device {device} --yes")
    print()
    raise SystemExit(1)
