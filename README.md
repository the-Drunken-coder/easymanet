# EasyMANET

Zero-touch provisioning and imaging for OpenMANET mesh nodes.

Public product repositories:

- [EasyMANET Images](https://github.com/the-Drunken-coder/easymanet-images)
- [EasyMANET CLI](https://github.com/the-Drunken-coder/easymanet-cli)
- [EasyMANET Desktop](https://github.com/the-Drunken-coder/easymanet-desktop)

## What EasyMANET Is

EasyMANET is a local CLI and Electron desktop app that lets you define an
entire OpenMANET mesh fleet in a single YAML config file, flash SD cards from
that file, and boot Raspberry Pi nodes directly into a working mesh without
touching the node-local web UI.

## What EasyMANET Is NOT

- A replacement for OpenMANET or OpenWrt
- A new MANET protocol
- A cloud dashboard
- A cloud management service
- A Meshtastic integration
- A drone UI

EasyMANET is a **provisioning, imaging, and configuration layer** on
top of OpenMANET. Use OpenMANET as the base firmware.

## Why It Exists

OpenMANET requires booting each node, connecting to the node, opening
the web UI, and running a setup wizard. For a multi-node field
deployment, this is tedious and error-prone. EasyMANET removes that
workflow entirely.

## Supported Hardware

- **Host**: macOS and Linux (the laptop you flash from)
- **Node**: Raspberry Pi 4
- **Radio**: MM6108 SPI (OpenMANET rpi4 + mm6108-spi target)

## Current Release Scope

- Single target: `rpi4-mm6108-spi` only
- Local CLI and Electron desktop workflows only
- No remote management
- No monitoring dashboard
- No incremental config updates (flash to reconfigure)

## Quick Start

### 1. Initialize the local workspace

The installed CLI creates a shared workspace under
`~/Documents/EasyMANET/`. Fleet files live in
`~/Documents/EasyMANET/Fleets/`, and the Electron app reads the same folder.

```bash
easymanet init
easymanet fleets
```

Set `EASYMANET_WORKSPACE=/path/to/EasyMANET` if you need a different local
workspace.

### 2. Write a fleet config

Create `~/Documents/EasyMANET/Fleets/fleet.yml`:

```yaml
version: 1

mesh:
  id: my-mesh
  password: "strong-mesh-password"
  channel: 42
  bandwidth_mhz: 2
  country: US

defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: "ap-password"
  management:
    root_password_hash: ""
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3..."
  gateway:
    wifi:
      enabled: false
      ssid: "operator-wifi"
      password: "operator-wifi-password"
      encryption: psk2

nodes:
  gate01:
    role: gate
    hostname: gate01
    ip: 10.41.1.1
    local_ap:
      ssid: gate01-local
    gateway:
      enabled: true
      uplink_interface: wifi
      wifi:
        enabled: true

  point01:
    role: point
    hostname: point01
    ip: 10.41.2.1
    local_ap:
      ssid: point01-local
```

The checked-in starter fleet is
[`examples/three-node-field-mesh.yml`](examples/three-node-field-mesh.yml).
See [docs/sample-fleet.md](docs/sample-fleet.md) for the copy command and a
smaller two-node example. EasyMANET does not create a fleet file automatically.

For a gate, `uplink_interface: wifi` joins the configured operator LAN. With SSH
enabled, the node opens SSH on that WAN zone so the desktop Mesh tab can find
it locally. `uplink_interface: eth0` keeps wired management on `br-lan`;
EasyMANET does not run WAN DHCP on that management bridge.

### 3. List available disks

```bash
easymanet disks
```

### 4. Validate config

```bash
easymanet validate --config fleet
easymanet validate --config fleet --node point01
```

### 5. Preview flash (dry run)

```bash
easymanet flash \
  --config fleet \
  --node point01 \
  --device /dev/disk4 \
  --base-image ./openmanet-rpi4-mm6108-spi.img.gz \
  --dry-run
```

### 6. Build an EasyMANET-flavored base image

```bash
easymanet image build
```

By default this uses Docker, builds OpenMANET `1.6.5` for
`rpi4-mm6108-spi`, and copies the resulting image into `./dist/`.
Local builds use a persistent Docker volume for the OpenMANET build cache.
CI can pass `--cache-dir .openmanet-cache` so GitHub Actions can cache the
same expensive OpenWrt download, host, and toolchain directories.

### 7. Flash a node

```bash
easymanet flash \
  --config fleet \
  --node point01 \
  --device /dev/disk4 \
  --base-image ./dist/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz \
  --image-sha256 <sha256> \
  --yes
```

### 8. Boot the node

Insert the SD card into the Raspberry Pi and power it on. The node
applies EasyMANET provisioning on first boot, restarts networking, and
stays up. Give it at least 90–120 seconds for networking and mesh services to
settle.

## Disk Flashing Safety

- **Never auto-selects a disk.** You must always provide `--device`.
- **`--yes` is required** to flash. Use `--dry-run` to preview first.
- **`easymanet disks`** lists removable, USB, and MMC/SD-like devices on
  Linux; macOS shows external drives. Use `easymanet disks --all` to list
  every block device.
- **Blocking checks** refuse to flash system disks, large internal drives,
  suspiciously large devices, and devices not in the default list unless
  you pass **`--force`**.
- **Partial failure recovery:** if boot payload staging fails after the
  image write, re-run the full `easymanet flash` command.
- **Unmounts partitions** before writing.
- **Downloaded images require HTTPS and SHA-256 verification.** Local
  `--base-image` files are allowed; pass `--image-sha256` to verify them
  before flashing.
- **Syncs writes** and **ejects** after completion.
- **SSH at flash time:** use `--enable-ssh` or `--disable-ssh` on `easymanet flash`
  (gate nodes default to SSH on; point nodes default to off). See
  [docs/flashing.md](docs/flashing.md).
- **Boot-partition secrets:** `provision.json` on the FAT boot volume contains
  fleet secrets in cleartext until successful first boot, when `provision.sh`
  removes the boot copy. The overlay copy at `/etc/easymanet/provision.json`
  (mode `0600`) remains. Treat flashed media as sensitive until the node has
  provisioned. See [docs/flashing.md](docs/flashing.md#security).

Set `EASYMANET_SKIP_UPDATE_CHECK=1` to skip the optional GitHub release check
on `flash` and `image build`.

## How to Test a Two-Node Mesh

1. Flash `gate01` to one SD card.
2. Flash `point01` to another SD card.
3. Boot both Raspberry Pis.
4. Wait at least 90–120 seconds after first-boot provisioning.
5. SSH into either node and verify mesh connectivity:
   ```bash
   ssh root@10.41.1.1
   ip addr show bat0
   batctl n
   ping 10.41.2.1
   ```

## CLI Commands

| Command | Description |
|---------|-------------|
| `easymanet init` | Create/show the shared `~/Documents/EasyMANET` workspace |
| `easymanet fleets` | List fleet YAML files in the shared workspace |
| `easymanet disks` | List flashable disks (`--all` for every block device) |
| `easymanet validate --config FILE` | Validate fleet config |
| `easymanet validate --config FILE --node NAME` | Validate specific node |
| `easymanet render --config FILE --node NAME` | Print resolved provision.json |
| `easymanet image build` | Build an EasyMANET-flavored OpenMANET image with Docker |
| `easymanet image manifest --image IMG` | Write image release metadata with checksum and provenance |
| `easymanet flash --config FILE --node NAME --device DEV --base-image IMG --yes` | Flash and provision |
| `easymanet flash ... --dry-run` | Preview flash without writing |
| `npm --prefix apps/desktop/electron start` | Run the local Electron operator console |
| `easymanet-desktop serve` | Run the browser-served fallback console |
| `easymanet-publish export` | Generate local public product surfaces without setting up subrepos |

## Architecture

```text
Documents/EasyMANET/Fleets/fleet.yml → validate → render → boot-partition provision.json → first boot → mesh
```

See [docs/architecture.md](docs/architecture.md) for the full data flow.

## Docs

- [Documentation Index](docs/README.md)
- [Architecture](docs/architecture.md)
- [Monorepo Layout](docs/monorepo.md)
- [Release Checklist](docs/release.md)
- [Sample Fleet](docs/sample-fleet.md)
- [Manifest Reference](docs/manifest.md) — every config field documented
- [Flashing Guide](docs/flashing.md)
- [Public Product Repositories](docs/public-repos.md)
- [OpenMANET Config Investigation](docs/openmanet-config-investigation.md)
- [Design Decisions](docs/design-decisions/) — durable choices and trade-offs ([template](docs/design-decisions/_EXAMPLE_DESIGN_DECISION_.md))
- [Problems](docs/problems/) — short-lived agent notes on active blockers ([template](docs/problems/_EXAMPLE_PROBLEM_.md))

## Development

```bash
pip install -e ".[dev]"
pytest
```

The repo is split into shared core, CLI, image, Electron desktop, and
publish/export source roots. See [docs/monorepo.md](docs/monorepo.md) for the
ownership map.

Before cutting a release, run the installed-wheel smoke and the checklist in
[docs/release.md](docs/release.md).

Pull requests run the `CI` workflow (unit tests, overlay shell syntax, and
packaging checks). Full OpenMANET firmware images are built via the
`Build OpenMANET Image` workflow (manual) or the weekly `Prove Overlay Weekly`
workflow on `main`. Docker-based `easymanet image build` on Apple Silicon uses
`linux/amd64` emulation and is slower than on native x86_64 hosts.

Generated public product repositories are produced with
`tools/packaging/publish_product_repos.py`; see [docs/public-repos.md](docs/public-repos.md).

## Security Notes

- An empty `root_password_hash` leaves the root password unchanged on the node.
- `gateway.uplink_interface: eth0` is reserved for wired management on
  `br-lan`; use a separate uplink or Wi-Fi uplink for WAN routing.
- Wi-Fi uplink (`gateway.wifi.enabled`) can expose SSH on WAN when SSH is enabled.
- When `/etc/openmanetd/config.yml` exists, first-boot writes mesh credentials
  into that file in plaintext (OpenMANET daemon requirement; verify on hardware).

## OpenMANET Provisioning Status

The first-boot scripts target standard OpenMANET UCI paths. Some UCI
paths and service names may need adjustment based on the specific
OpenMANET build. See [docs/openmanet-config-investigation.md](docs/openmanet-config-investigation.md)
for a record of known paths and gaps.

The following need verification against a configured OpenMANET node:
- Exact wireless radio type string for MM6108 SPI
- Mesh identification field name (`mesh_id` vs `ssid`)
- Encryption type (`sae` vs `psk2`)
- OpenMANET daemon service name (`openmanetd`)
- Any additional UCI config files
