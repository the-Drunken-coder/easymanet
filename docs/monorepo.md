# Monorepo Layout

EasyMANET is authored as a private monorepo with separate product
surfaces for the shared core, CLI, image builder, Electron desktop app, and
publish/export tooling.

## Source Roots

| Path | Role |
| --- | --- |
| `packages/core/src/easymanet/` | Shared fleet parsing, validation, rendering, disk safety, flashing, injection, image cache, and diagnostics primitives. |
| `apps/cli/src/easymanet_cli/` | Installable CLI surface. The `easymanet` command points here. |
| `packages/image/src/easymanet_image/` | OpenMANET image build commands and release metadata generation. |
| `images/openmanet/provisioning/` | OpenWrt overlay files and extra package list used by firmware builds. |
| `apps/desktop/electron/` | Local Electron shell that loads UI files from disk and uses preload IPC for filesystem-backed operations. |
| `apps/desktop/src/easymanet_desktop/` | Shared desktop UI assets, JSON bridge, and browser-served fallback console. |
| `tools/publish/src/easymanet_publish/` | Local export tooling for generated public product surfaces. |

The monorepo does not keep legacy module aliases. Import from the explicit
surface that owns the behavior: `easymanet_cli`, `easymanet_image`,
`easymanet_desktop`, `easymanet_publish`, or shared core modules under
`easymanet`.

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

The current implementation intentionally does not configure public
subrepositories, credentials, protected branches, remotes, or dispatch
targets. Instead, `easymanet-publish export` writes local generated
surfaces under `dist/public-surfaces/` and records a provenance file
named `easymanet-public-surfaces.json`.

Exported surfaces also receive small bootstrap workflow templates under
`.github/workflows/`. Those templates are inert until a later setup step
publishes them into actual public repositories and configures dispatch
credentials.

Those local exports are the handoff point for later public repository
setup.
