# Config Manifest Reference

Complete reference for every field in `fleet.yml`.

The manifest is a closed contract. Unknown fields, quoted booleans, numeric
strings, non-string text fields, non-mapping nested sections, and control
characters are rejected while loading the file. Write booleans as unquoted
YAML `true` or `false` and integers as unquoted YAML integers. Ordinary
single-line string content, including quotes, slashes, backslashes, and
leading or trailing spaces, is preserved exactly in `provision.json`.

## Top-level Fields

### `version` (required, integer)

Config schema version. Currently must be `1`.

```yaml
version: 1
```

---

## `mesh` (required, object)

Mesh-wide settings applied to every node.

### `mesh.id` (required, string)

Mesh network identifier. Used as the 802.11s mesh ID.

```yaml
mesh:
  id: my-mesh-network
```

### `mesh.password` (required, string)

Mesh network password/key. Used for SAE (WPA3) encryption.

```yaml
mesh:
  password: "strong-mesh-password"
```

### `mesh.channel` (required, integer)

WiFi channel for the mesh radio. Valid values depend on the country
regulatory domain. For the tested `rpi4-mm6108-spi` MM6108 target in the US,
use channel `42` with `mesh.bandwidth_mhz: 2`.

```yaml
mesh:
  channel: 42
```

### `mesh.bandwidth_mhz` (required, integer)

Channel bandwidth in MHz. Must be one of: 1, 2, 4, 8.
For the tested `rpi4-mm6108-spi` MM6108 target in the US, use `2`.

```yaml
mesh:
  bandwidth_mhz: 2
```

### `mesh.country` (required, string)

Two-letter ISO country code for WiFi regulatory compliance.

```yaml
mesh:
  country: US
```

---

## `defaults` (optional, object)

Default values inherited by all nodes unless overridden.

### `defaults.target` (optional, string)

Target hardware platform. Defaults to `rpi4-mm6108-spi`; currently that is the
only supported value.

```yaml
defaults:
  target: rpi4-mm6108-spi
```

### `defaults.local_ap` (object)

Default local access point settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Whether to create a local WiFi AP |
| `password` | string | — | AP password (min 8 chars when enabled) |
| `ssid` | string | `{nodename}-local` | AP SSID (override per node) |

```yaml
defaults:
  local_ap:
    enabled: true
    password: "ap-password-here"
```

### `defaults.management` (object)

Node management settings.

| Field | Type | Description |
|-------|------|-------------|
| `root_password_hash` | string | Hashed root password (from `openssl passwd -6`) |
| `ssh_authorized_keys` | list[string] | SSH public keys for root login (installed one per line via jsonfilter on the node) |

SSH enable/disable is **not** set in `fleet.yml`. Use `easymanet flash
--enable-ssh` or `--disable-ssh` (see [flashing.md](flashing.md)). The
flash command may write `management.ssh_enabled` into the boot-partition
(when `--enable-ssh` or `--disable-ssh` is used; otherwise first boot uses the role default)
`provision.json`.

```yaml
defaults:
  management:
    root_password_hash: "$6$salt$hash..."
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3..."
```

### `defaults.gateway` (object)

Default uplink settings shared by nodes.

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | bool | Optional consistency assertion. If present, it must be `true` for a `gate` and `false` for a `point`; rendered gateway mode is always derived from `role`. |
| `uplink_interface` | string | Uplink network interface name. `eth0` is WAN when selected on a gate; otherwise Ethernet remains mesh-side access on `br-ahwlan`. |
| `wifi` | object | Optional Wi-Fi uplink settings. `wifi.enabled` independently selects the Wi-Fi station for a gate uplink or point management access. |

#### `gateway.wifi` fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Whether to join the configured upstream Wi-Fi network. |
| `ssid` | string | — | Upstream network name. Required when enabled. |
| `password` | string | — | Upstream network password. Required when enabled. |
| `encryption` | string | `psk2` | `psk2`, `sae`, `none`, `psk`, or `psk-mixed`. |

### `defaults.role` (string)

Default node role. Must be `gate` or `point`.

---

## `nodes` (required, object)

Map of node names to their specific configurations. Each key is the
node name used with `--node` in CLI commands.

### Node Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `role` | string | no | from defaults, then `point` | `gate` or `point` |
| `hostname` | string | yes | — | System hostname |
| `ip` | string | yes | — | Static node IP on the OpenMANET mesh bridge (`br-ahwlan`) |
| `target` | string | no | from defaults, then `rpi4-mm6108-spi` | Hardware target |
| `local_ap` | object | no | from defaults | Local AP override |
| `gateway` | object | no | from defaults | Gateway settings override |

Node `ip` values must be strings inside the `10.41.0.0/16` mesh subnet,
must not use the subnet network or broadcast addresses (`10.41.0.0` or
`10.41.255.255`), and must stay outside the gate DHCP pool
`10.41.1.95`-`10.41.1.110`.

The current runtime model requires exactly one `gate` node per fleet. That gate
is the single DHCP server and internet exit for the flat `br-ahwlan` mesh LAN.

### Node `local_ap` Overrides

Any field in `defaults.local_ap` can be overridden per node:

```yaml
nodes:
  manet01:
    local_ap:
      ssid: manet01-local
      password: "different-ap-password"
```

### Node `gateway` Overrides

```yaml
nodes:
  manet01:
    role: gate
    gateway:
      uplink_interface: wifi
      wifi:
        enabled: true
```

With `uplink_interface: wifi`, EasyMANET joins the configured upstream Wi-Fi as
`wan`. The desktop Mesh and Diagnostics tabs discover nodes through the local
EasyMANET API (`/v1/identity`, `/v1/neighbors`, `/v1/status`, and gate-only
`/v1/topology`). Wi-Fi gateways keep that API mesh-side by default; use the
flash-time `--enable-wan-api` opt-in only on trusted upstream Wi-Fi LANs. With
`uplink_interface: eth0`, EasyMANET runs WAN DHCP on `eth0` and keeps that port
out of `br-ahwlan`.

`local_ap.enabled` and `gateway.wifi.enabled` cannot both be true on one node.
They use the same physical radio. Disable the local AP on a Wi-Fi-uplink node;
the validator and first-boot provisioning both reject the conflicting shape.

Gateway mode itself is derived from the node role: gates render
`gateway.enabled: true`; points render `gateway.enabled: false`. An authored
`gateway.enabled` value is optional and must agree with the role. When
`gateway.wifi.enabled` is true, an omitted uplink resolves to `wifi`; an
explicit uplink must also be `wifi`. Conversely, `uplink_interface: wifi`
requires `gateway.wifi.enabled: true`. These same invariants are checked again
on first boot before network configuration is changed.

On point nodes, `gateway.wifi.enabled` is allowed as a management uplink for
direct SSH or troubleshooting over an upstream Wi-Fi LAN. It does not make the
point a mesh gateway, does not provide mesh-to-WAN forwarding, and uses the
same radio that would otherwise host `local_ap`, which must be disabled.

---

## Resolved Config

The `easymanet render` command outputs the fully resolved config
after merging mesh settings, defaults, and node overrides.

Resolved `local_ap.enabled`, `gateway.enabled`, and
`gateway.wifi.enabled` values are JSON booleans, never strings or integers.
Only documented fields are rendered; arbitrary manifest fields are rejected
rather than passed to the node.

Priority (highest to lowest):
1. Node-specific values
2. `defaults` section values
3. `mesh` section values (mesh-wide, not overridable per node)

## Validation Rules

| Rule | Error Level |
|------|-------------|
| version must be 1 | Error |
| All fields must use their documented YAML type; booleans and integers are not coerced from strings | Error |
| Unknown fields and control characters are rejected | Error |
| mesh.id is required | Error |
| mesh.password is required | Error |
| mesh.channel is required | Error |
| mesh.bandwidth_mhz must be 1, 2, 4, or 8 | Error |
| mesh.country is required | Error |
| nodes section must have at least one node | Error |
| Node names must be unique (case-insensitive) | Error |
| Hostnames must be unique | Error |
| IP addresses must be unique, strings, inside `10.41.0.0/16`, outside `10.41.1.95`-`10.41.1.110`, and not `10.41.0.0` or `10.41.255.255` | Error |
| role must be gate or point | Error |
| fleet must define exactly one gate node | Error |
| target must be one of the supported targets (e.g., rpi4-mm6108-spi) | Error |
| local_ap.password min 8 chars when enabled | Error |
| Selected node must exist in manifest | Error |
| Invalid SSH key format | Error |
| No SSH keys provided | Warning |
| root_password_hash is empty | Warning |
| Gate role without uplink_interface | Warning |
| Gate Ethernet (`eth0`) is the WAN uplink | Warning |
| mesh.country must be two-letter ISO code (e.g. US) | Error |
| gateway.wifi.enabled requires ssid and password | Error |
| local_ap.enabled and gateway.wifi.enabled cannot both be true on one node | Error |
| gateway.enabled, when authored, must match the node role | Error |
| gateway.wifi.enabled and uplink_interface: wifi must agree | Error |
| gateway.wifi.encryption must be psk2, sae, none, psk, or psk-mixed | Error |
| gateway.wifi.enabled on point nodes is management-only and warns about mesh gateway behavior and SSH exposure if enabled | Warning |

## Security

- Empty `root_password_hash` does not set a root password on the node.
- `gateway.uplink_interface: eth0` makes Ethernet the gateway WAN uplink.
  Use Wi-Fi or a separate uplink if Ethernet should stay mesh-side on
  `br-ahwlan`.
- On gate nodes, `gateway.wifi.enabled` keeps the EasyMANET API bound to the
  mesh IP by default. Flashing with `--enable-wan-api` writes
  `management.api_wan_enabled: true`, binds the API to `0.0.0.0:10411`, and
  opens WAN firewall access to topology endpoints under `/v1`.
- On gate nodes, `gateway.wifi.enabled` with SSH enabled also opens SSH on the
  WAN firewall zone.
- EasyMANET API exposure on WAN (port 10411) is opt-in, intended only for
  trusted upstream Wi-Fi LANs, and sensitive on untrusted uplinks.
- On point nodes, `gateway.wifi.enabled` can expose SSH on the upstream Wi-Fi
  LAN if SSH is enabled during flash, but it does not expose the EasyMANET API
  or provide mesh-to-WAN forwarding.
- Mesh credentials may be written to `/etc/openmanetd/config.yml` in plaintext
  when that file exists on the image.
