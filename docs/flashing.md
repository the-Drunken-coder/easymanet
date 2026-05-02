# Flash Workflow

## Overview

The `easymanet flash` command writes an OpenMANET base image to an SD
card or USB drive, then places node-specific `provision.json` on the
FAT boot partition at `/easymanet/provision.json`.

## Supported Image Formats

- `.img` — raw disk image
- `.img.gz` — gzip-compressed raw disk image

## Build the Base Image

```bash
easymanet image build
```

This command uses Docker to:

1. Build a reusable Ubuntu 24.04 builder image with the OpenWrt toolchain.
2. Clone or refresh the cached OpenMANET source tree in the Docker cache.
3. Copy `provisioning/openwrt-overlay/` into the firmware tree's `files/`.
4. Run `./scripts/openmanet_setup.sh -i -b ekh-bcm2711`.
5. Run `make download -jN` and `make -jN V=s`.
6. Copy the resulting `openmanet-*-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz`
   into `./dist/` by default.

By default the cache is a Docker volume. Use `--cache-dir PATH` when the host
needs to manage or persist OpenMANET cache files directly, such as in GitHub
Actions.

## macOS

### Detecting Disks

```bash
easymanet disks
```

Uses `diskutil list external` to find removable/external drives.

### Flashing

```bash
easymanet flash \
  --config fleet.yml \
  --node manet02 \
  --device /dev/disk4 \
  --base-image ./openmanet-rpi4-mm6108-spi.img.gz \
  --yes
```

Steps:
1. Validate config.
2. Render `provision.json` for the selected node.
3. Unmount all partitions of the target device.
4. Stream (decompress if `.gz`) the image to the raw device.
5. Mount the FAT boot partition.
6. Write `/easymanet/provision.json`.
7. Unmount and eject.

### Safety

- Mac internal drives (containing `/` or `/System/Volumes/Data`) are
  flagged as system disks and rejected.
- `--yes` is required. Use `--dry-run` to preview.
- `--force` overrides system disk detection.

### Post-flash

After successful flash and boot-payload staging, the drive is ejected. Remove it
and insert into the Raspberry Pi.

## Linux

### Detecting Disks

```bash
easymanet disks
```

Uses `lsblk -J` to list block devices. Filters to disk type devices.

### Flashing

Same command as macOS. Uses `dd`-style streaming write via Python
file I/O.

### Safety

- System disks are detected by mount points (`/`, `/boot`, `/home`,
  `/var`, `/usr`).
- `--yes` is required.
- `--force` overrides system disk detection.

### Permissions

Flashing requires write access to the target block device, typically
meaning the command must be run as root or with `sudo`.

## Dry Run

```bash
easymanet flash \
  --config fleet.yml \
  --node manet02 \
  --device /dev/disk4 \
  --base-image ./openmanet.img.gz \
  --dry-run
```

Outputs the complete flash plan without writing anything:

- Selected node and resolved config
- Target device details
- Resolved `provision.json`
- The boot-partition payload that would be written
- Disk safety warnings if any

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Permission denied | Run with `sudo` |
| Device not found | Use `easymanet disks` to verify device path |
| System disk warning | Verify you selected the correct device; use `--force` only if sure |
| Boot payload staging failed | Verify the first FAT partition mounted correctly and is writable from your host OS. |
| Image won't boot | Verify the base image matches your hardware (RPi4 + MM6108 SPI) by writing it directly first, without EasyMANET injection. |
| `gzip` reports `trailing garbage ignored` for an OpenWrt/OpenMANET sysupgrade image | This is expected. OpenWrt appends sysupgrade metadata after the gzip payload. EasyMANET validates the gzip payload but allows the metadata trailer. |
| EasyMANET payload is present on the boot partition but the node still launches the normal wizard | The base image does not yet include the EasyMANET first-boot hooks. Rebuild the firmware image with `provisioning/openwrt-overlay/` copied into OpenMANET's `files/` tree. |

EasyMANET validates `.img.gz` payloads before flashing. A corrupt cached
download is skipped during automatic image resolution and deleted before
re-download when `--download` is used. OpenWrt/OpenMANET sysupgrade
metadata appended after the gzip payload is not treated as corruption.

EasyMANET no longer attempts to edit the root filesystem offline. That
approach is invalid for standard OpenWrt/OpenMANET SquashFS images.

The current `flash` command assumes the base image already includes the
EasyMANET first-boot hooks. Those files live in this repo under:

`provisioning/openwrt-overlay/`
