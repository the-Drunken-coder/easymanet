# Electron Local Desktop

## Status

Accepted

## Context

EasyMANET needs a local-first operator console that can inspect the shared
workspace, list removable disks, validate fleet files, preview flash plans, and
call a native bridge for privileged-adjacent host operations.

## Decision

Use Electron for the desktop shell. Keep `contextIsolation` enabled, keep
`nodeIntegration` disabled, and expose only a narrow preload API. The renderer
loads local static assets and calls the Python bridge through IPC for filesystem
and device operations.

## Consequences

The desktop app can ship as a familiar packaged operator tool while continuing
to share the Python core with the CLI. The security boundary stays in the
Electron main/preload bridge, and host behavior remains testable without a
separate desktop database or service.
