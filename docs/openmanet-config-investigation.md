# OpenMANET Config Investigation

This document records what the OpenMANET web wizard modifies, based on
inspection of OpenMANET images and documentation.

> **Note**: This is based on OpenMANET's public documentation and
> source tree analysis. Exact UCI paths may vary by OpenMANET version.
> Update this document when testing against a specific OpenMANET build.

---

## Files Modified by OpenMANET Setup Wizard

### `/etc/config/wireless`

The wizard configures the mesh radio and optional local AP:

```
config wifi-device 'radio0'
    option type 'mac80211'
    option channel '42'
    option htmode 'HT20'
    option country 'US'
    option disabled '0'

config wifi-iface 'mesh0'
    option device 'radio0'
    option network 'mesh'
    option mode 'mesh'
    option mesh_id '<mesh-id>'
    option encryption 'sae'
    option key '<mesh-password>'
    option mesh_fwding '1'

config wifi-iface 'ap0'          # Only if local AP enabled
    option device 'radio0'
    option network 'lan'
    option mode 'ap'
    option ssid '<ap-ssid>'
    option encryption 'sae'
    option key '<ap-password>'
```

### `/etc/config/network`

Mesh interface (static IP) and gateway WAN:

```
config interface 'mesh'
    option proto 'static'
    option ipaddr '<node-ip>'
    option netmask '255.255.255.0'

config interface 'wan'           # Only on gate nodes
    option proto 'dhcp'
    option ifname 'eth0'
```

### `/etc/config/system`

Hostname and timezone:

```
config system
    option hostname '<hostname>'
    option timezone 'UTC'
```

### `/etc/config/dhcp`

Mesh interface is excluded from DHCP serving:

```
config dhcp 'mesh'
    option interface 'mesh'
    option ignore '1'
```

### `/etc/config/firewall`

Mesh zone (open between mesh nodes):

```
config zone
    option name 'mesh'
    option network 'mesh'
    option input 'ACCEPT'
    option output 'ACCEPT'
    option forward 'ACCEPT'
```

### `/etc/dropbear/authorized_keys`

SSH public keys for root login (Dropbear format).

### `/etc/shadow`

Root password hash is updated.

### `/etc/openmanetd/config.yml`

OpenMANET daemon configuration (if the daemon is present):

```yaml
mesh:
  id: "<mesh-id>"
  password: "<mesh-password>"
  channel: <channel>
  bandwidth_mhz: <bandwidth>
  country: "<country>"
node:
  name: "<node-name>"
  hostname: "<hostname>"
  role: "<gate|point>"
  ip: "<node-ip>"
```

---

## Setup-Complete Flags

OpenMANET may use one or more of these flags:

- `/etc/openmanet/setup-complete`
- `/etc/config/openmanet` with a `setup_complete` option
- A marker in the OpenMANET database (typically SQLite at
  `/var/lib/openmanet/openmanet.db`)

EasyMANET uses its own marker at `/etc/easymanet/provisioned` to
avoid conflicts and ensure idempotent provisioning.

---

## Service Control

After configuration changes, the following services need restart:

```
/etc/init.d/network restart
/etc/init.d/openmanetd restart    # If daemon model
```

Or enable for subsequent boots:

```
/etc/init.d/network enable
/etc/init.d/openmanetd enable
```

---

## Reboot Requirement

OpenMANET typically requires one reboot after initial configuration
before the mesh fully forms. This is handled by EasyMANET's
`provision.sh` which calls `reboot` at the end.

---

## Mesh Role Representation

| Role | UCI Changes | Network Behavior |
|------|------------|------------------|
| **gate** | WAN interface configured, IP forwarding enabled, mesh firewall open | Routes mesh traffic to uplink (internet/other network) |
| **point** | Mesh interface only, no WAN | Participates in mesh, no external routing |

---

## Known Gaps

The following sections need validation against a running OpenMANET
node to confirm exact UCI paths and service names:

1. Exact `/etc/config/wireless` radio0 type string for MM6108 SPI
2. Whether OpenMANET uses `mesh_id` or `ssid` for mesh identification
3. Exact encryption type (sae, psk2, none) per OpenMANET version
4. OpenMANET daemon path (`/etc/init.d/openmanetd` — may differ)
5. Any additional UCI config files (e.g., `olsrd`, `batman-adv`)

**These should be verified by inspecting a node configured via the
OpenMANET web wizard.**
