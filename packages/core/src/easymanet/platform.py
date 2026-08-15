import sys


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def check_platform() -> None:
    if is_macos() or is_linux():
        return
    sys.exit(f"Error: Unsupported platform '{sys.platform}'. EasyMANET supports macOS and Linux only.")
