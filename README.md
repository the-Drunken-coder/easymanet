# EasyMANET

Zero-touch provisioning and imaging for OpenMANET mesh nodes.

## What EasyMANET Is

EasyMANET is a CLI tool that lets you define an entire OpenMANET mesh
fleet in a single YAML config file, flash SD cards from that file, and
boot Raspberry Pi nodes directly into a working mesh — without ever
touching the node-local web UI.

## What EasyMANET Is NOT

- A replacement for OpenMANET or OpenWrt
- A new MANET protocol
- A web dashboard or GUI
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

## MVP Limitations

- Single target: `rpi4-mm6108-spi` only
- CLI only
- No remote management
- No monitoring dashboard
- No incremental config updates (flash to reconfigure)

## Quick Start

### 1. Write a fleet config

Create `fleet.yml`:

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

nodes:
  gate01:
    role: gate
    hostname: gate01
    ip: 10.41.1.1
    local_ap:
      ssid: gate01-local
    gateway:
      enabled: true
      uplink_interface: eth0

  point01:
    role: point
    hostname: point01
    ip: 10.41.2.1
    local_ap:
      ssid: point01-local
```

### 2. List available disks

```bash
easymanet disks
```

### 3. Validate config

```bash
easymanet validate --config fleet.yml
easymanet validate --config fleet.yml --node point01
```

### 4. Preview flash (dry run)

```bash
easymanet flash \
  --config fleet.yml \
  --node point01 \
  --device /dev/disk4 \
  --base-image ./openmanet-rpi4-mm6108-spi.img.gz \
  --dry-run
```

### 5. Build an EasyMANET-flavored base image

```bash
easymanet image build
```

By default this uses Docker, builds OpenMANET `1.6.5` for
`rpi4-mm6108-spi`, and copies the resulting image into `./dist/`.

### 6. Flash a node

```bash
easymanet flash \
  --config fleet.yml \
  --node point01 \
  --device /dev/disk4 \
  --base-image ./dist/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz \
  --yes
```

### 7. Boot the node

Insert the SD card into the Raspberry Pi and power it on. The node
will configure itself and reboot once. After reboot, it joins the mesh.

## Disk Flashing Safety

- **Never auto-selects a disk.** You must always provide `--device`.
- **`--yes` is required** to flash. Use `--dry-run` to preview first.
- **System disk detection** warns or refuses to flash likely system
  disks (internal drives with `/`, `/boot`, etc.).
- **`--force` overrides** system disk detection (use with extreme care).
- **Unmounts partitions** before writing.
- **Syncs writes** and **ejects** after completion.

## How to Test a Two-Node Mesh

1. Flash `gate01` to one SD card.
2. Flash `point01` to another SD card.
3. Boot both Raspberry Pis.
4. Wait ~60 seconds after reboot.
5. SSH into either node and verify mesh connectivity:
   ```bash
   ssh root@10.41.1.1
   ping 10.41.2.1
   ```

## CLI Commands

| Command | Description |
|---------|-------------|
| `easymanet disks` | List external/removable disks |
| `easymanet validate --config FILE` | Validate fleet config |
| `easymanet validate --config FILE --node NAME` | Validate specific node |
| `easymanet render --config FILE --node NAME` | Print resolved provision.json |
| `easymanet image build` | Build an EasyMANET-flavored OpenMANET image with Docker |
| `easymanet flash --config FILE --node NAME --device DEV --base-image IMG --yes` | Flash and provision |
| `easymanet flash ... --dry-run` | Preview flash without writing |

## Architecture

```
fleet.yml → validate → render → boot-partition provision.json → first boot → mesh
```

See [docs/architecture.md](docs/architecture.md) for the full data flow.

## Docs

- [Architecture](docs/architecture.md)
- [Manifest Reference](docs/manifest.md) — every config field documented
- [Flashing Guide](docs/flashing.md)
- [OpenMANET Config Investigation](docs/openmanet-config-investigation.md)

## Development

```bash
pip install -e ".[dev]"
pytest
```

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
