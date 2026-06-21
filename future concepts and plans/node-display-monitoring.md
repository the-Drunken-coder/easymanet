# Node And Operator Observability

This plan supersedes the earlier HDMI-only display-monitoring concept. Node
status display, desktop diagnostics, CLI diagnostics, offline boot-report import,
and support bundles all use the same node facts and support codes.

## V1 Product Shape

- Audience: EasyMANET field operator.
- HDMI/console display: simple colored text, no browser or desktop stack.
- Gateway display: local node status plus expected fleet nodes as `OK`,
  `MISSING`, or `UNKNOWN`.
- Point display: local node status only.
- Desktop Diagnostics tab: run diagnostics, copy a support summary, export a zip
  bundle, and import offline boot reports.
- CLI diagnostics: same run, bundle, and import workflows for scripts and agents.

## Shared Facts

The on-node `/v1/status` endpoint and boot-report `status.json` include:

- node name, role, target, and IP address,
- mesh connected state and neighbor count,
- public internet reachability using configurable public ping targets,
- manageability/API state,
- stable support code and warnings,
- gateway fleet status when running on a gate node.

Stable V1 support codes are:

- `EM-OK`
- `EM-BOOT-INCOMPLETE`
- `EM-MESH-DOWN`
- `EM-INET-DOWN`
- `EM-NODE-MISSING`
- `EM-API-DOWN`
- `EM-DIAG-PARTIAL`

## Support Bundle

Support bundles are written under the shared EasyMANET workspace
`Diagnostics/` folder. They are meant for copy/paste into an AI agent or for
keeping local field evidence. Bundles include raw logs where available and redact
obvious secrets by default.
