# Monorepo Layout

EasyMANET is authored as a private monorepo with separate product
surfaces for the shared core, CLI, image builder, Electron desktop app, and
publish/export tooling.

## Source Roots

| Path | Role |
| --- | --- |
| `packages/core/src/easymanet/` | Shared fleet parsing, validation, rendering, disk safety, flashing, injection, image cache, and diagnostics primitives. |
| `apps/cli/src/easymanet_cli/` | Installable CLI surface. The `easymanet` command and Typer command registration live here. |
| `packages/image/src/easymanet_image/` | OpenMANET image build and release metadata logic. |
| `images/openmanet/provisioning/` | OpenWrt overlay entry scripts, sourced `/usr/lib/easymanet/*.sh` helpers, and extra package list used by firmware builds. |
| `apps/desktop/electron/` | Local Electron shell modules for app/window bootstrap, preload IPC, bridge execution, elevated flash staging, stream parsing, and packaged path resolution. |
| `apps/desktop/src/easymanet_desktop/` | Shared desktop UI modules, JSON bridge, and browser-served fallback console. |
| `tools/publish/src/easymanet_publish/` | Local export tooling for generated public product surfaces. |

Import from the explicit surface that owns the behavior: `easymanet_cli`,
`easymanet_image`, `easymanet_desktop`, `easymanet_publish`, or shared core
modules under `easymanet`. Compatibility imports may remain when public tests
or downstream users already rely on them, but new ownership should follow the
surface boundaries above.

## Product Surfaces

- CLI: `easymanet`
- Desktop app: `npm --prefix apps/desktop/electron start`
- Desktop fallback console: `easymanet-desktop serve`
- Public-surface export: `easymanet-publish export`
- Image build: `easymanet image build`
- Image release metadata: `easymanet image manifest`

## Local Workspace

Installing and running the CLI creates a shared local workspace at
`~/Documents/EasyMANET/` by default:

| Folder | Owner |
| --- | --- |
| `Fleets/` | User-authored `.yml` and `.yaml` fleet files discovered by the CLI and desktop app. |
| `Images/` | Downloaded or configured firmware image cache and image URL manifest. |
| `Diagnostics/` | Local boot reports and troubleshooting artifacts. |
| `Builds/` | Local build outputs and generated artifacts. |

The `EASYMANET_WORKSPACE` environment variable can point the CLI and desktop
bridge at another workspace. Fleet commands accept either a normal path or a
workspace fleet name such as `--config field`, which resolves to
`~/Documents/EasyMANET/Fleets/field.yml` or `.yaml` when present.

The Electron desktop app loads `index.html` from the local checkout, exposes
only a narrow `window.easymanet` preload API, and calls the Python desktop
bridge for state, disk discovery, and fleet validation. The browser-served
console remains available for development and smoke testing. Neither mode
introduces a separate app database; both desktop modes read fleet and image
state from the shared workspace.

## Image Release Metadata

Image builds write `easymanet-image-release.json` next to the firmware
artifact. The manifest records:

- target hardware
- OpenMANET version
- EasyMANET version
- release channel
- artifact filename, size, and SHA-256
- monorepo source ref
- public workflow provenance when available

The download path checks for this manifest in GitHub release assets
before falling back to filename-based image discovery.

## Public Repositories

Public product repositories are generated from this authoring monorepo rather
than edited by hand. The authoritative surface definitions live in
`easymanet_publish.surfaces` and are consumed by both:

- `easymanet-publish export`, which writes local previews under
  `dist/public-surfaces/` and records `easymanet-public-surfaces.json`
- `.github/workflows/publish-product-repos.yml`, which runs
  `tools/packaging/publish_product_repos.py` to generate, optionally push, and
  optionally dispatch release workflows in the public repositories

The generated public repositories are:

| Product | Public repo | Purpose |
| --- | --- | --- |
| `images` | `easymanet-images` | Firmware image build and image release surface. |
| `cli` | `easymanet-cli` | CLI/PyPI release and automation surface. |
| `desktop` | `easymanet-desktop` | Electron desktop packaging and release surface. |

Normal development stays in this authoring repo. Public repos should be treated
as generated outputs with provenance in `REPO_GENERATION.md`.
