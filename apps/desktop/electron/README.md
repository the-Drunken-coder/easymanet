# EasyMANET Electron Desktop

This is the local Electron shell for the EasyMANET operator console. It
loads the UI from local files and talks to EasyMANET through a narrow
preload API plus a Python JSON bridge. It does not depend on a hosted
website or a localhost web server.

The native shell can preview and execute the shared EasyMANET flash workflow.
If the OS blocks direct block-device writes, the app returns a copyable sudo
fallback command that reuses the bundled bridge.

## Run

From the repository root:

```bash
npm --prefix apps/desktop/electron install
npm --prefix apps/desktop/electron start
```

If EasyMANET is not installed into the active Python environment, point
Electron at the repo venv:

```bash
EASYMANET_PYTHON=.codex-venv/bin/python npm --prefix apps/desktop/electron start
```

## Check

```bash
npm --prefix apps/desktop/electron run check
```

## Package

Build the bundled bridge and native desktop artifacts from the repository root:

```bash
python -m pip install -e ".[dev]" pyinstaller
npm --prefix apps/desktop/electron ci
npm --prefix apps/desktop/electron run dist -- --mac dmg zip
```

On Windows, swap the final command for:

```bash
npm --prefix apps/desktop/electron run dist -- --win nsis zip
```

The packaged app bundles the Python bridge with PyInstaller and copies the
static UI into Electron resources so the release artifacts stay local-first.
