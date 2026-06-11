# Architecture Review — 2026-06-10

Scope: high-level design review of the full monorepo at v0.2.0
(`HEAD` ≈ `14bd4ce`). Focus is architecture and cross-surface seams, not
line-level bugs.

Overall verdict: the core model is sound — the pipeline shape
(manifest → validate → render → flash → inject → first boot), the
host/device split, the safety layering around flashing, and the
local-first shared workspace are all right and worth protecting. The
structural debt is concentrated in seams between surfaces, listed below
in priority order.

---

## Issue 1 — Desktop bridge screen-scrapes the CLI instead of calling a structured core API

**Severity:** High (largest structural issue)

**Location:**
- `apps/desktop/src/easymanet_desktop/bridge.py:24` (`PRIVILEGE_ERROR_MARKER`)
- `apps/desktop/src/easymanet_desktop/bridge.py:172` (`_capture_flash`)
- `apps/desktop/src/easymanet_desktop/bridge.py:220` (`_error_summary`)
- `apps/desktop/src/easymanet_desktop/bridge.py:228` (`_warning_lines`)
- `apps/cli/src/easymanet_cli/flash.py:304` (`run_flash`)

**Problem:** The bridge runs the CLI's `run_flash` under
`redirect_stdout`/`redirect_stderr` and reverse-engineers the result
from terminal text:

- success is derived from the exit code,
- the error message is "the last non-empty line of output",
- warnings are lines starting with `"Warning:"` or containing
  `"Flash safety:"`,
- privilege failure is detected by searching for the exact sentence
  `"Write access to the target block device is required."` from
  `privileges.py`.

The CLI's presentation layer has become the desktop app's integration
API. Rewording any message, changing colors, or reordering output can
silently break desktop error reporting. Buffered capture also means a
multi-minute destructive `dd` write shows the desktop user nothing
until the bridge process exits (see the 30-minute
`flashBridgeTimeoutMs` in `apps/desktop/electron/main.js:10`).

**Root cause:** Flash orchestration lives in the CLI surface and is
welded to Typer (`typer.Exit`, `typer.secho`), so the desktop must
emulate a terminal to reuse it. This also creates an
`apps/desktop → apps/cli` import — an app depending on another app —
which contradicts the layering described in `docs/monorepo.md`.
`planning.md` lists "subprocess vs shared core library" as an open
question; the implementation answered it by default, with the weaker
option.

**Direction:** Move the flash workflow into `packages/core` as a
function that returns structured results (steps, warnings, errors as
data) and accepts a progress/event callback. CLI and bridge become thin
presenters. This removes the string coupling, fixes the dependency
direction, and unlocks real progress display in the desktop app.

**Related (same theme):** Core modules embed presentation directly —
`print()` progress in `packages/core/src/easymanet/image.py:151` and
`packages/core/src/easymanet/download.py:410`.

---

## Issue 2 — Public product surfaces are defined twice in parallel

**Severity:** High (guaranteed drift)

**Location:**
- `tools/publish/src/easymanet_publish/export.py` (`SURFACES` tuples,
  generated per-surface pyprojects; installed as `easymanet-publish`)
- `tools/packaging/publish_product_repos.py` (`RepoSpec`,
  `PRODUCT_DOC_PATHS`/`PRODUCT_TEST_PATHS`, `product_repos/templates/`,
  its own `cli_surface_pyproject()` / `desktop_surface_pyproject()`
  generators; this is what `.github/workflows/publish-product-repos.yml`
  actually runs)

**Problem:** Two independent mechanisms encode "which files belong to
which public repo," in different formats, in different places. A path
added to one and not the other yields inconsistent public surfaces.
This recreates, inside the monorepo, exactly the drift risk that
`planning.md` warns about for public repos.

**Doc rot:** `docs/monorepo.md` still says public subrepositories are
"intentionally not configured," but the `Publish Product Repos`
workflow can create repos, push, and dispatch releases, and the README
links three live public repos.

**Direction:** Make the surface definitions a single data structure
consumed by both the local exporter and the publisher. Update
`docs/monorepo.md` to describe the actual publish state.

---

## Issue 3 — Untyped dict-merging config model with rules duplicated across layers

**Severity:** Medium (works today; first thing to rot as fields grow)

**Location:**
- `packages/core/src/easymanet/validate.py:186-200` and
  `validate.py:250-264` (local_ap password rules duplicated within one
  module)
- `packages/core/src/easymanet/validate.py:294` (`resolve_node` shallow
  merges; password fallback at `validate.py:333` patches the dict after
  it was built)
- `packages/core/src/easymanet/render.py` (re-implements pieces of the
  merge again)

**Problem:** The manifest stays raw nested dicts end-to-end.
`resolve_node` does `{**defaults, **node}` merges; `validate()`
re-implements the same merge to check resolved values; the
provision.json schema exists implicitly in four places at once
(`render.py`, `validate.py`, `provision.sh`, `docs/manifest.md`).
`gateway.wifi` already shows the per-field special-casing pattern that
this model produces.

**Direction:** One typed resolution step — resolve → typed
node/provision dataclass → validate the typed object → serialize —
collapses three parallel representations into one.

---

## Issue 4 — OpenMANET coupling concentrated in the least-testable layer

**Severity:** Medium (acknowledged, partially mitigated)

**Location:**
- `images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh`
  (532 lines of POSIX sh; exceeds the repo's own ~300-line guideline,
  see `docs/problems/2026-05-30-modules-exceed-line-limit.md`)

**Problem:** All knowledge of OpenMANET's UCI paths, service names, and
encryption types lives in the on-device script, where debugging is
hardest. The host↔device contract is "whatever provision.sh happens to
read" — no schema check on either side of the boundary — and the README
itself lists unverified UCI paths (radio type string, `mesh_id` vs
`ssid`, `sae` vs `psk2`, `openmanetd` service name).

**Mitigations already in place:** `EM_*` environment-variable defaults
(`provision.sh:21-42`) as an upstream-change escape hatch;
`provision-lib.sh` extraction; the `tests/shell_harness/` stubs and the
weekly overlay-proving workflow.

**Direction:** Acceptable debt at single-target scope. Keep the
quarantine visible: continue the env-override + lib-extraction
trajectory, and consider a minimal payload-shape check on the device
side (fail loudly on missing required fields rather than silently
configuring with empty values).

---

## Issue 5 — Bridge imports private functions from the HTTP server module

**Severity:** Low

**Location:** `apps/desktop/src/easymanet_desktop/bridge.py:21` imports
`_state_payload`, `_disks_payload`, `_validate_payload` from
`server.py`.

**Problem:** The shared payload builders live inside the browser-served
HTTP server and are consumed across module boundaries via
underscore-private names. The dependency direction (JSON bridge →
fallback web server) is accidental.

**Direction:** Move the payload builders to a neutral module (e.g.
`easymanet_desktop/payloads.py`) that both `server.py` and `bridge.py`
import publicly.

---

## Issue 6 — `download.py` freezes workspace paths at import time

**Severity:** Low (classic test/bridge gotcha)

**Location:** `packages/core/src/easymanet/download.py:37-39`
(`CACHE_DIR = images_dir()`, `IMAGES_MANIFEST`, `VERSION_FILE`).

**Problem:** Every other module resolves workspace paths lazily through
functions; `download.py` captures them at import. Setting
`EASYMANET_WORKSPACE` after import is silently ignored by the download
cache, while honored everywhere else.

**Direction:** Replace the module-level constants with functions (or
properties) resolved at call time, matching `workspace.py`.

---

## Issue 7 — Fleet-path resolution rules exist in three places

**Severity:** Low

**Location:**
- `packages/core/src/easymanet/workspace.py:89` (`resolve_fleet_config`)
- `apps/desktop/electron/main.js:287-327` (`resolveConfigPath`,
  `fleetPathCandidates`, `existingFleetFile`)

**Problem:** The Electron main process re-implements fleet path
resolution in JS with slightly different rules (JS requires a
`.yml`/`.yaml` extension; Python accepts any existing path). The
candidate/extension logic will skew over time. Defense-in-depth at the
IPC boundary is good; duplicating resolution semantics is not.

**Direction:** Keep only the security checks (traversal, containment)
in JS and delegate resolution to the Python bridge, which already owns
those rules.

---

## Issue 8 — Version duplicated and synced by hand

**Severity:** Low

**Location:** `pyproject.toml:7` (`version = "0.2.0"`) and
`packages/core/src/easymanet/__init__.py:3` (`__version__ = "0.2.0"`).

**Direction:** Single-source it (e.g. read the package version from
metadata, or generate one from the other at build time). Note the
generated public-surface pyprojects are also produced by two generators
(see Issue 2).

---

## Issue 9 — Design-decision scaffold exists but is unused

**Severity:** Low (documentation/culture)

**Location:** `docs/design-decisions/` contains only
`_EXAMPLE_DESIGN_DECISION_.md`.

**Problem:** The actual durable decisions — Electron over Tauri,
subprocess vs shared core library for the desktop app, the
copy-paste-`sudo` strategy for desktop flashing (bridge returns a
`sudo_command` string instead of escalating in-app) — live scattered in
`planning.md` and READMEs. The sudo decision in particular deserves a
written rationale: it is a defensible local-first choice (no privileged
helpers), but it is non-obvious and embeds `sys.executable` paths.

**Direction:** Record these decisions in the scaffolded folder.

---

## Suggested priority

1. Issue 1 — promote flash orchestration into core with structured
   results + progress events (also resolves the layering violation and
   the desktop progress UX).
2. Issue 2 — unify the surface definitions behind one data source; fix
   the stale `docs/monorepo.md` claim.
3. Issue 3 — typed resolved-node model, best done before the field
   count grows.
4. Issues 4–9 — as the surrounding areas are touched.
