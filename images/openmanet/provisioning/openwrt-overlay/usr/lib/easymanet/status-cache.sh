#!/bin/sh
# Refresh stale-aware EasyMANET status and topology snapshots.

set -u

SCRIPT_DIR="${EASYMANET_LIB_DIR:-/usr/lib/easymanet}"
PROVISION_JSON="${EASYMANET_PROVISION_JSON:-/etc/easymanet/provision.json}"
API_PORT="${EASYMANET_API_PORT:-10411}"
FETCH_TIMEOUT="${EASYMANET_API_FETCH_TIMEOUT:-1}"
MAX_TOPOLOGY_PEER_PROBES="${EASYMANET_API_MAX_TOPOLOGY_PEER_PROBES:-8}"
: "${EASYMANET_STATUS_CACHE_INTERVAL:=10}"
: "${EASYMANET_STATUS_CACHE_LOG:=/var/log/easymanet-status-cache.log}"

MODE="loop"
case "${1:-}" in
    "")
        ;;
    --once)
        MODE="once"
        ;;
    *)
        echo "usage: $0 [--once]" >&2
        exit 2
        ;;
esac

case "$MAX_TOPOLOGY_PEER_PROBES" in
    ""|*[!0-9]*)
        MAX_TOPOLOGY_PEER_PROBES=8
        ;;
esac

case "$EASYMANET_STATUS_CACHE_INTERVAL" in
    ""|0|*[!0-9]*)
        EASYMANET_STATUS_CACHE_INTERVAL=10
        ;;
esac

log_cache() {
    mkdir -p "$(dirname "$EASYMANET_STATUS_CACHE_LOG")" 2>/dev/null || true
    printf '[%s] %s\n' "$(date)" "$*" >> "$EASYMANET_STATUS_CACHE_LOG" 2>/dev/null || true
}

if [ ! -f "$PROVISION_JSON" ]; then
    log_cache "provision payload $PROVISION_JSON not available"
    [ "$MODE" = "once" ] && exit 0
    while true; do
        sleep "$EASYMANET_STATUS_CACHE_INTERVAL"
    done
fi

# shellcheck source=provision-lib.sh
. "$SCRIPT_DIR/provision-lib.sh"
# shellcheck source=api-lib.sh
. "$SCRIPT_DIR/api-lib.sh"
# shellcheck source=status-lib.sh
. "$SCRIPT_DIR/status-lib.sh"

refresh_once() {
    topology_payload="$(topology_live_json_body)"
    topology_cache="$(json_cache_object live fresh "$(epoch_now)")"
    topology_snapshot="$(json_with_cache "$topology_payload" "$topology_cache")"
    status_snapshot="$(status_live_json_body "$topology_snapshot")"

    write_json_atomic "$(topology_cache_file)" "$topology_snapshot" || return 1
    write_json_atomic "$(status_cache_file)" "$status_snapshot" || return 1
}

log_cache "starting status cache mode=$MODE interval=$EASYMANET_STATUS_CACHE_INTERVAL cache_dir=$(cache_dir)"

if [ "$MODE" = "once" ]; then
    refresh_once || exit 1
    exit 0
fi

while true; do
    refresh_once || log_cache "status cache refresh failed"
    sleep "$EASYMANET_STATUS_CACHE_INTERVAL"
done
