# EasyMANET Electron Desktop

This is the local Electron shell for the EasyMANET operator console. It
loads the UI from local files and talks to EasyMANET through a narrow
preload API plus a Python JSON bridge. It does not depend on a hosted
website or a localhost web server.

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
