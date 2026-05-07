# EasyMANET Lessons Learned

This file captures practical lessons from getting an EasyMANET-flavored OpenMANET
image built, flashed, booted, and reachable on a Raspberry Pi 4 with a Seeed /
Morse MM6108 SPI HaLow HAT. Future agent sessions should read this before
changing the firmware build, first-boot provisioning, flashing flow, or network
debugging path.

## Build Workflow

- Full OpenMANET image builds are slow on GitHub-hosted runners. A successful
  full overlay build can take around 2-5 hours depending on cache state.
- The slow part is the OpenWrt/OpenMANET firmware build, not the EasyMANET
  Python code or overlay scripts.
- Stock OpenMANET, empty EasyMANET overlay, and full EasyMANET overlay builds
  were all in the same broad runtime range. The overlay itself was not the main
  source of build time.
- Use fast checks for normal development:

  ```sh
  pytest -q
  sh -n provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh
  sh -n provisioning/openwrt-overlay/usr/lib/easymanet/network.sh
  sh -n provisioning/openwrt-overlay/usr/lib/easymanet/boot-report.sh
  ```

- Only run the full firmware workflow when a flashable image is needed.
- The useful full-image workflow is:

  ```sh
  gh workflow run prove-openmanet-overlay.yml \
    --ref add-project-files \
    -f openmanet_version=1.6.5 \
    -f board=ekh-bcm2711 \
    -f openwrt_target=bcm27xx \
    -f subtarget=bcm2711 \
    -f jobs=0
  ```

- `jobs=0` means use `nproc` in the proof workflows. Do not assume every
  workflow handles `0` this way; check the workflow before dispatching.

## Artifact Selection

- The `ekh-bcm2711` build produces multiple Raspberry Pi 4 images. For the
  Seeed/Morse SPI HAT tested here, use:

  ```text
  openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz
  ```

- Do not accidentally flash the SDIO or USB variant unless the hardware really
  matches it.
- Artifacts are downloaded from GitHub Actions with:

  ```sh
  gh run download <run-id> --dir /tmp/easymanet-artifact-<run-id>
  ```

## Flashing

- The current flashing command shape is:

  ```sh
  sudo python3 -m easymanet.cli flash \
    --config examples/fleet.yml \
    --node manet01 \
    --device /dev/disk4 \
    --base-image /tmp/easymanet-artifact-<run-id>/openmanet-full-easymanet-overlay-1.6.5-ekh-bcm2711/openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz \
    --yes
  ```

- On macOS, verify the target USB drive before flashing:

  ```sh
  diskutil list external physical
  ```

- The USB stick used during testing appeared as:

  ```text
  /dev/disk4
  Model: USB DISK 3.0
  Removable: yes
  ```

- If macOS shows the USB device in `system_profiler SPUSBDataType` but not in
  `diskutil list`, unplug and replug it. Do not flash until a real
  `/dev/diskN` appears.
- The flash tool patches `/boot/cmdline.txt` to use `root=PARTUUID=...-02`.
  This mattered for USB boot on the Pi.
- `gzip: ... trailing garbage ignored` appeared during successful flashes. It
  was noisy but not fatal in the tested path.
- Avoid shell wrapping mistakes:
  - There must be a space between `flash` and `--config`.
  - Do not split the `--base-image` path across lines unless the shell line
    continuation is exact.
  - Do not paste conversational words like `lets` into the command.

## First Boot Diagnostics

- Offline boot reports are essential when SSH is not available.
- The EasyMANET image writes reports to the FAT boot partition under:

  ```text
  /easymanet/boot-report-latest/
  /easymanet/boot-report-<timestamp>/
  ```

- Useful report files:
  - `summary.txt`
  - `brctl-show.txt`
  - `ip-addr.txt`
  - `ip-link.txt`
  - `ip-route.txt`
  - `uci-network.txt`
  - `uci-wireless.txt`
  - `config-network`
  - `config-wireless`
  - `logread.txt`
  - `easymanet-network.log`

- If a report is captured too early, it may show pre-repair network state. The
  management LAN repair waits before running; wait at least 90-120 seconds
  before pulling the drive for diagnostics.

## RPi4 Ethernet Management

- The initial failure mode was:
  - SSH to `10.41.254.1` timed out.
  - `br-lan` had `10.41.254.1/16`.
  - `br-lan` had no interfaces attached.
  - `eth0` was configured as `wan`.

- The working state is:

  ```text
  network.@device[0].name='br-lan'
  network.@device[0].type='bridge'
  network.@device[0].ports='eth0'
  network.lan.device='br-lan'
  network.lan.ipaddr='10.41.254.1'
  ```

  and:

  ```text
  br-lan ... interfaces: eth0
  eth0 ... master br-lan
  br-lan inet 10.41.254.1/16
  ```

- The current fix is intentionally defensive:
  - first-boot provisioning tries to keep `eth0` on `br-lan`
  - a late boot repair service runs after startup and enforces the same state
  - the repair removes `wan` / `wan6`, commits network config, brings `lan` up,
    and calls `brctl addif br-lan eth0`

- This was necessary because OpenMANET startup can leave `eth0` as `wan`, which
  makes direct Ethernet management unreachable even though Dropbear is running.

## SSH and Login

- Use the `root` user:

  ```sh
  ssh root@10.41.254.1
  ```

- A previous failed login was caused by trying to SSH as the local macOS user
  instead of `root`.
- The test image currently has no root password set, so OpenMANET prints a
  warning. This is acceptable for bring-up, but should be fixed before any
  real deployment.

## Radio Detection and Wireless

- Do not assume the HaLow radio is always `radio0`, `radio1`, or `radio2`.
- The provisioner should detect the Morse/802.11ah radio dynamically:
  - prefer `wireless.<radio>.type='morse'`
  - fall back to `wireless.<radio>.hwmode='11ah'`

- The local AP should not be put on the Morse radio unless that is intentional.
  The provisioner should choose a `mac80211` radio for local AP when available.
- On the tested Pi/HAT, reports showed the mesh interface as:

  ```text
  wlan0 inet 10.41.1.1/24
  mesh_id easymanet-field
  channel 42
  bandwidth 2
  country US
  ```

- The local AP path may be unreliable on this Pi/HAT combo; do not use AP
  visibility as the only boot success signal.

## Two-Node Mesh Test

- `examples/fleet.yml` already defines multiple nodes on the same mesh:
  - `manet01`: `10.41.1.1`, role `gate`
  - `manet02`: `10.41.2.1`, role `point`

- To test two radios:
  1. Flash one USB stick with `--node manet01`.
  2. Flash another USB stick with `--node manet02`.
  3. Boot both devices.
  4. SSH into `manet01` over Ethernet:

     ```sh
     ssh root@10.41.254.1
     ```

  5. From `manet01`, test mesh reachability:

     ```sh
     ping 10.41.2.1
     ssh root@10.41.2.1
     ```

- `manet02` is a point node and may not expose the same Ethernet management
  path unless the manifest explicitly configures it that way.

## Troubleshooting Order

When a flashed device does not respond:

1. Confirm the correct image target was flashed (`rpi4-mm6108-spi` for this
   hardware).
2. Confirm the drive was flashed with the intended node name.
3. Wait at least 90-120 seconds after boot.
4. Try `ssh root@10.41.254.1` for `manet01`.
5. If SSH fails, pull the drive and inspect:

   ```sh
   ls -R /Volumes/boot/easymanet
   cat /Volumes/boot/easymanet/boot-report-latest/summary.txt
   cat /Volumes/boot/easymanet/boot-report-latest/brctl-show.txt
   cat /Volumes/boot/easymanet/boot-report-latest/ip-addr.txt
   cat /Volumes/boot/easymanet/boot-report-latest/uci-network.txt
   cat /Volumes/boot/easymanet/boot-report-latest/easymanet-network.log
   ```

6. If `br-lan` has no `eth0`, the management LAN repair did not run or ran too
   late for the report. Check `ps.txt`, `logread.txt`, and
   `easymanet-network.log`.

## Known Follow-Ups

- Set a real root password or valid authorized keys before non-lab use.
- Consider making Ethernet management available on point nodes during bring-up.
- Consider a faster non-image CI smoke test for provisioner/network scripts.
- Consider a self-hosted runner for full OpenMANET image builds.
