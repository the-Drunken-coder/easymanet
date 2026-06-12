# Sample Fleet

Use [`examples/three-node-field-mesh.yml`](../examples/three-node-field-mesh.yml)
as the checked-in starter fleet for local testing and release smoke runs.

To try it in the shared workspace:

```bash
easymanet init
cp examples/three-node-field-mesh.yml ~/Documents/EasyMANET/Fleets/field.yml
easymanet validate --config field --node point01
```
The installer does not create a fleet file automatically. Fleet YAML contains
mesh passwords, local AP passwords, and management keys, so user-authored
configuration should stay intentional.

For the smallest useful shape, keep one gate and one point:

```yaml
version: 1

mesh:
  id: field-deployment-alpha
  password: "replace-with-a-strong-mesh-password"
  channel: 42
  bandwidth_mhz: 2
  country: US

defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: "replace-with-a-local-ap-password"
  management:
    root_password_hash: "replace-with-hashed-password"
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... operator"

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
