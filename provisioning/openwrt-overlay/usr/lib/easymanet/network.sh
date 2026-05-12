#!/bin/sh
# EasyMANET network helpers shared by provisioning and late boot repair.

EASYMANET_NETWORK_LOG="${EASYMANET_NETWORK_LOG:-/var/log/easymanet-network.log}"
EASYMANET_PROVISION_JSON="${EASYMANET_PROVISION_JSON:-/etc/easymanet/provision.json}"

easymanet_log_network() {
    echo "[$(date)] $*" >> "$EASYMANET_NETWORK_LOG"
}

easymanet_json_path() {
    path="@"
    for key in "$@"; do
        path="${path}.${key}"
    done
    printf '%s' "$path"
}

easymanet_json_val() {
    [ -s "$EASYMANET_PROVISION_JSON" ] || return 0
    jsonfilter -i "$EASYMANET_PROVISION_JSON" -e "$(easymanet_json_path "$@")" 2>/dev/null || true
}

easymanet_find_lan_bridge_section() {
    uci show network | sed -n "s/^network\.\([^.=]*\)\.name='br-lan'$/\1/p" | head -n 1
}

easymanet_ensure_lan_bridge_port() {
    port="$1"
    bridge="$(easymanet_find_lan_bridge_section)"
    if [ -z "$bridge" ]; then
        bridge="$(uci add network device)"
        uci set network."$bridge".name="br-lan" >> "$EASYMANET_NETWORK_LOG" 2>&1
        uci set network."$bridge".type="bridge" >> "$EASYMANET_NETWORK_LOG" 2>&1
    fi

    uci set network.lan.device="br-lan" >> "$EASYMANET_NETWORK_LOG" 2>&1
    uci -q delete network."$bridge".ports 2>/dev/null || true
    uci add_list network."$bridge".ports="$port" >> "$EASYMANET_NETWORK_LOG" 2>&1
}

easymanet_repair_management_lan() {
    reason="${1:-manual}"
    mgmt_iface="eth0"

    role="$(easymanet_json_val node role 2>/dev/null || true)"
    uplink="$(easymanet_json_val node gateway uplink_interface 2>/dev/null || true)"
    [ -n "$uplink" ] || uplink="eth0"

    easymanet_log_network "ensuring $mgmt_iface stays on br-lan for management reason=$reason role=$role uplink=$uplink"

    # If wan is currently sitting on the management interface (the gate-eth0
    # default), tear it down so it doesn't fight br-lan. Wi-Fi-uplink wan on
    # phy1-sta0 must be left alone.
    wan_device="$(uci -q get network.wan.device || true)"
    wan_ifname="$(uci -q get network.wan.ifname || true)"
    if [ "$wan_device" = "$mgmt_iface" ] || [ "$wan_ifname" = "$mgmt_iface" ]; then
        /sbin/ifdown wan >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
        /sbin/ifdown wan6 >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
        uci -q delete network.wan 2>/dev/null || true
        uci -q delete network.wan6 2>/dev/null || true
    fi

    easymanet_ensure_lan_bridge_port "$mgmt_iface"
    uci commit network >> "$EASYMANET_NETWORK_LOG" 2>&1
    /sbin/ifup lan >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
    ubus call network reload >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
    ip link set "$mgmt_iface" up >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
    brctl addif br-lan "$mgmt_iface" >> "$EASYMANET_NETWORK_LOG" 2>&1 || true
}
