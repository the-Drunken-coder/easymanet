# Node Observability V1

## Status

Accepted

## Context

EasyMANET needed one small status model for node-local display, the read-only
node API, boot reports, desktop diagnostics, CLI diagnostics, and support
bundles. This started as a future concept, but the implemented overlay and
diagnostics code now make it a current design reference.

## Decision

Use a shared node status contract. Nodes expose `/v1/status` JSON, write the
same facts into boot-report `status.json`, and render the same facts on the
simple HDMI/console display.

Gate nodes include expected fleet nodes as `OK`, `MISSING`, or `UNKNOWN`. Point
nodes report only local status.

Stable V1 support codes are:

- `EM-OK`
- `EM-BOOT-INCOMPLETE`
- `EM-MESH-DOWN`
- `EM-INET-DOWN`
- `EM-NODE-MISSING`
- `EM-API-DOWN`
- `EM-DIAG-PARTIAL`

Support bundles are written under the shared EasyMANET workspace `Diagnostics/`
folder. They are local field evidence for humans or agents, include raw logs
where available, and redact obvious secrets by default.

## Consequences

The status contract stays local-first and file/API based. The desktop and CLI
should consume the same facts rather than inventing separate health models.

Current implementation and reference points:

- `docs/architecture.md`
- `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/status-lib.sh`
- `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/display-status.sh`
- `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/boot-report.sh`
- `packages/core/src/easymanet/diagnostics.py`
- `packages/core/src/easymanet/support_bundle.py`
