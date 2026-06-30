# EasyMANET Verification System Plan

## Summary

Build a layered verification system that makes bench testing the exception, not
the default. The system should prove most EasyMANET changes through repeatable
local and CI checks, simulated OpenWrt provisioning, image and artifact
inspection, and a scheduled or release-only hardware-in-the-loop path.

The goal is not to eliminate hardware validation entirely. The goal is to make
each change land with the strongest non-hardware evidence available, then
reserve real node testing for firmware, flash, provisioning, radio, and release
risk.

## Key Changes

- Add one standard verification entrypoint: `python tools/verify.py <profile>`.
- Supported profiles:
  - `fast`: Python tests, overlay shell syntax, Electron check, overlay
    packaging check, and whitespace check.
  - `package`: installed-wheel smoke in a clean temporary venv, including
    removed-import checks and optional Electron smoke.
  - `openwrt-sim`: shell-harnessed provisioning, API, and status tests using
    fake `uci`, fake `jsonfilter`, and fixed OpenMANET command-output fixtures.
  - `artifact`: verify built image and release artifacts without booting
    hardware.
  - `hil`: run hardware-in-the-loop checks against already-flashed or
    freshly-flashed real nodes.
- Keep each profile boring: call existing tools and tests rather than inventing
  a framework.
- Document the profiles in the README and release checklist so every change has
  an obvious verification level.

## Verification Layers

### Fast Gate

- Runs on every PR and local pre-merge check.
- Uses Python 3.11 or a clean project venv, not host Homebrew Python 3.14 for
  packaging-sensitive checks.
- Must fail with clear messages; fix the current Electron `undefined` failure
  path before treating it as a trusted gate.

### OpenWrt Simulation Gate

- Expand the existing shell harness to cover first-boot behavior that previously
  required bench testing.
- Required scenarios: gate provisioning, point provisioning, stale config rerun,
  gate-only DHCP, `br-ahwlan`/`bat0` layout, `openmanetd` mesh interface,
  topology API exposure, status output, boot-report generation, and
  management-LAN repair.
- Fixtures should live in one predictable test fixture directory and represent
  real captured `batctl`, `ip`, `uci`, and status outputs.
- Until `tools/verify.py openwrt-sim` lands, run the gate directly with:
  `python -m pytest -q tests/test_firstboot.py tests/test_provision_behavior.py tests/test_led_status.py`.

### Artifact Gate

- Verify firmware and release outputs without flashing them.
- Checks: overlay files are packaged, executable modes are preserved, required
  init, defaults, and API files exist, release manifest matches artifact name,
  size, and SHA, boot payload injection can be staged into a mounted test image
  or synthetic FAT fixture, and image cache metadata is read-only during state
  checks.
- This gate should run after image builds and before publishing releases.

### Desktop And CLI Workflow Gate

- Prove the operator workflow without hardware: workspace creation, fleet
  selection, validation, disk payload serialization, flash dry-run and plan,
  diagnostics bundle export, and Electron renderer state transitions.
- Desktop checks should include runtime `require()` and bridge smoke checks, not
  just `node --check`.

### Hardware-In-The-Loop Gate

- Runs manually, nightly, or before release, not on every PR.
- Inputs: fleet config, gate node name, point node name, optional disk devices,
  and optional existing node IPs.
- Checks: flash or reuse nodes, wait 90-120 seconds, probe `/v1/identity`,
  `/v1/status`, `/v1/topology`, SSH when enabled, mesh neighbor visibility,
  support code, boot-report availability, and optional throughput smoke.
- Output: a timestamped JSON result plus a redacted support bundle under the
  EasyMANET diagnostics workspace.

## Test Scenarios

- Normal CLI changes must pass `fast`.
- Packaging, release, or public-surface changes must pass `fast` and `package`.
- Provisioning, overlay, API, status, diagnostics, or network behavior changes
  must pass `fast` and `openwrt-sim`.
- Image builder, manifest, cache, download, or release workflow changes must
  pass `fast`, `package`, and `artifact`.
- Desktop shell, bridge, renderer, or flash UI changes must pass `fast` plus the
  desktop smoke path.
- Changes touching destructive flash writes, macOS elevated flash, OpenMANET
  image contents, radio or mesh assumptions, or release artifacts must also get
  `hil` evidence before shipping.

## Assumptions And Defaults

- Keep the current single supported target as the default:
  `rpi4-mm6108-spi`.
- Keep CI fast; full image builds stay manual or scheduled.
- Do not require hardware-in-the-loop for ordinary application, test, docs, or
  non-flash UI changes.
- Treat hardware results as evidence tied to exact image version, source commit,
  fleet file, node names, and captured diagnostics.
- Prefer adding coverage to the existing pytest, shell harness, release smoke,
  and workflow structure over introducing a new test framework.
