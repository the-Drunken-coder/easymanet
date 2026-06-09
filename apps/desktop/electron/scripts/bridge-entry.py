"""PyInstaller entrypoint for the EasyMANET Electron bridge."""

from easymanet_desktop.bridge import main


if __name__ == "__main__":
    raise SystemExit(main())
