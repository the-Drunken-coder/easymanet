#!/bin/sh
# EasyMANET generic first-boot provisioning script.
#
# Expects node-specific provision.json on the FAT boot partition at:
#   /boot/easymanet/provision.json
# and copies it into overlay storage before applying configuration.

set -eu

LOG_FILE="/var/log/easymanet.log"
PROVISIONED_FLAG="/etc/easymanet/provisioned"
PROVISION_DIR="/etc/easymanet"
PROVISION_JSON="$PROVISION_DIR/provision.json"
BOOT_MOUNT_TMP="/tmp/easymanet-boot"
BOOT_JSON=""
BOOT_MOUNTED_TMP=0

exec 2>>"$LOG_FILE"
echo "=== EasyMANET provisioning started $(date) ===" >> "$LOG_FILE"

cleanup() {
    if [ "$BOOT_MOUNTED_TMP" -eq 1 ]; then
        umount "$BOOT_MOUNT_TMP" 2>/dev/null || true
        rmdir "$BOOT_MOUNT_TMP" 2>/dev/null || true
    fi
}

trap cleanup EXIT

json_path() {
    path="@"
    for key in "$@"; do
        path="${path}.${key}"
    done
    printf '%s' "$path"
}

json_val() {
    jsonfilter -i "$PROVISION_JSON" -e "$(json_path "$@")" 2>/dev/null || true
}

json_bool() {
    case "$(json_val "$@")" in
        1|true|TRUE|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

uci_set() {
    uci set "$@" >> "$LOG_FILE" 2>&1
}

uci_commit() {
    uci commit "$1" >> "$LOG_FILE" 2>&1
}

find_morse_radio() {
    radio="$(uci show wireless | sed -n "s/^wireless\.\([^.=]*\)\.type='morse'$/\1/p" | head -n 1)"
    if [ -n "$radio" ]; then
        printf '%s' "$radio"
        return 0
    fi

    uci show wireless | sed -n "s/^wireless\.\([^.=]*\)\.hwmode='11ah'$/\1/p" | head -n 1
}

find_boot_json() {
    for candidate in \
        /boot/easymanet/provision.json \
        /boot/firmware/easymanet/provision.json
    do
        if [ -s "$candidate" ]; then
            BOOT_JSON="$candidate"
            return 0
        fi
    done

    mkdir -p "$BOOT_MOUNT_TMP"
    for dev in /dev/mmcblk0p1 /dev/sda1 /dev/nvme0n1p1; do
        [ -b "$dev" ] || continue
        if mount -o ro -t vfat "$dev" "$BOOT_MOUNT_TMP" 2>/dev/null; then
            BOOT_MOUNTED_TMP=1
            if [ -s "$BOOT_MOUNT_TMP/easymanet/provision.json" ]; then
                BOOT_JSON="$BOOT_MOUNT_TMP/easymanet/provision.json"
                return 0
            fi
            umount "$BOOT_MOUNT_TMP" 2>/dev/null || true
            BOOT_MOUNTED_TMP=0
        fi
    done

    return 1
}

if [ -f "$PROVISIONED_FLAG" ]; then
    echo "Already provisioned, skipping." >> "$LOG_FILE"
    exit 0
fi

if ! find_boot_json; then
    echo "FATAL: no boot-partition provision.json found" | tee -a "$LOG_FILE"
    exit 1
fi

mkdir -p "$PROVISION_DIR"
cp "$BOOT_JSON" "$PROVISION_JSON"
chmod 0600 "$PROVISION_JSON"

if ! command -v jsonfilter >/dev/null 2>&1; then
    echo "FATAL: jsonfilter not found; cannot parse provision.json" | tee -a "$LOG_FILE"
    exit 1
fi

MESH_ID="$(json_val mesh id)"
MESH_PASSWORD="$(json_val mesh password)"
HOSTNAME="$(json_val node hostname)"
NODE_ROLE="$(json_val node role)"
NODE_IP="$(json_val node ip)"
MESH_CHANNEL="$(json_val mesh channel)"
MESH_BW="$(json_val mesh bandwidth_mhz)"
MESH_COUNTRY="$(json_val mesh country)"

if [ -z "$MESH_ID" ] || [ -z "$MESH_PASSWORD" ] || [ -z "$HOSTNAME" ]; then
    echo "FATAL: missing required mesh/node fields in provision.json" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Setting hostname to $HOSTNAME..." >> "$LOG_FILE"
uci_set system.@system[0].hostname="$HOSTNAME"
uci_set system.@system[0].timezone="UTC"
uci_commit system
echo "$HOSTNAME" > /proc/sys/kernel/hostname 2>/dev/null || true

if command -v dropbear >/dev/null 2>&1; then
    mkdir -p /etc/dropbear
fi

ROOT_PW_HASH="$(json_val management root_password_hash 2>/dev/null || true)"
if [ -n "$ROOT_PW_HASH" ]; then
    echo "Setting root password hash..." >> "$LOG_FILE"
    sed -i "s|^root:.*|root:${ROOT_PW_HASH}:19000:0:99999:7:::|" /etc/shadow 2>/dev/null || true
fi

if json_val management ssh_authorized_keys >/dev/null 2>&1; then
    SSH_KEYS="$(json_val management ssh_authorized_keys 2>/dev/null || true)"
    if [ -n "$SSH_KEYS" ]; then
        : > /etc/dropbear/authorized_keys
        printf '%s\n' "$SSH_KEYS" >> /etc/dropbear/authorized_keys
    fi
fi

echo "Configuring mesh wireless..." >> "$LOG_FILE"
while uci -q delete wireless.@wifi-iface[0] 2>/dev/null; do :; done

MESH_RADIO="$(find_morse_radio)"
if [ -z "$MESH_RADIO" ]; then
    echo "FATAL: no Morse/802.11ah wifi-device found in /etc/config/wireless" | tee -a "$LOG_FILE"
    exit 1
fi

echo "Using Morse HaLow radio $MESH_RADIO..." >> "$LOG_FILE"
uci_set wireless."$MESH_RADIO".channel="$MESH_CHANNEL"
uci_set wireless."$MESH_RADIO".htmode="HT${MESH_BW}0"
uci_set wireless."$MESH_RADIO".country="$MESH_COUNTRY"
uci_set wireless."$MESH_RADIO".disabled="0"

uci_set wireless.mesh0=wifi-iface
uci_set wireless.mesh0.device="$MESH_RADIO"
uci_set wireless.mesh0.network="mesh"
uci_set wireless.mesh0.mode="mesh"
uci_set wireless.mesh0.mesh_id="$MESH_ID"
uci_set wireless.mesh0.encryption="sae"
uci_set wireless.mesh0.key="$MESH_PASSWORD"
uci_set wireless.mesh0.mesh_fwding="1"

if json_bool node local_ap enabled; then
    LOCAL_AP_SSID="$(json_val node local_ap ssid)"
    LOCAL_AP_PASSWORD="$(json_val node local_ap password)"
    uci_set wireless.ap0=wifi-iface
    uci_set wireless.ap0.device="$MESH_RADIO"
    uci_set wireless.ap0.network="lan"
    uci_set wireless.ap0.mode="ap"
    uci_set wireless.ap0.ssid="$LOCAL_AP_SSID"
    uci_set wireless.ap0.encryption="sae"
    uci_set wireless.ap0.key="$LOCAL_AP_PASSWORD"
fi
uci_commit wireless

echo "Configuring network..." >> "$LOG_FILE"
uci_set network.mesh=interface
uci_set network.mesh.proto="static"
uci_set network.mesh.ipaddr="$NODE_IP"
uci_set network.mesh.netmask="255.255.255.0"
uci_commit network

uci_set dhcp.mesh=dhcp
uci_set dhcp.mesh.interface="mesh"
uci_set dhcp.mesh.ignore="1"
uci_commit dhcp

uci_set firewall.mesh_zone=zone
uci_set firewall.mesh_zone.name="mesh"
uci_set firewall.mesh_zone.network="mesh"
uci_set firewall.mesh_zone.input="ACCEPT"
uci_set firewall.mesh_zone.output="ACCEPT"
uci_set firewall.mesh_zone.forward="ACCEPT"
uci_commit firewall

if [ "$NODE_ROLE" = "gate" ]; then
    UPLINK="$(json_val node gateway uplink_interface 2>/dev/null || echo "eth0")"
    uci_set network.wan=interface
    uci_set network.wan.proto="dhcp"
    uci_set network.wan.ifname="$UPLINK"
    uci_set network.wan.peerdns="0"
    uci_set network.wan.dns="1.1.1.1 8.8.8.8"
    uci_commit network
fi

if [ -f /etc/openmanetd/config.yml ]; then
    cat > /etc/openmanetd/config.yml <<EOF
mesh:
  id: "${MESH_ID}"
  password: "${MESH_PASSWORD}"
  channel: ${MESH_CHANNEL}
  bandwidth_mhz: ${MESH_BW}
  country: "${MESH_COUNTRY}"
node:
  name: "$(json_val node name)"
  hostname: "${HOSTNAME}"
  role: "${NODE_ROLE}"
  ip: "${NODE_IP}"
EOF
fi

/etc/init.d/network enable 2>/dev/null || true
/etc/init.d/network restart 2>/dev/null || true
if [ -f /etc/init.d/openmanetd ]; then
    /etc/init.d/openmanetd enable 2>/dev/null || true
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$PROVISIONED_FLAG"
echo "hostname: $HOSTNAME" >> "$PROVISIONED_FLAG"
echo "role: $NODE_ROLE" >> "$PROVISIONED_FLAG"
echo "ip: $NODE_IP" >> "$PROVISIONED_FLAG"
echo "=== EasyMANET provisioning complete $(date) ===" >> "$LOG_FILE"

( sleep 5; reboot ) &
exit 0
