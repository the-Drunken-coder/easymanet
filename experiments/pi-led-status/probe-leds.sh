#!/bin/sh
set -eu

LED_ROOT="${LED_ROOT:-/sys/class/leds}"

log() {
    printf '%s\n' "$*"
}

detect_led() {
    if [ -n "${EASYMANET_LED_NAME:-}" ] && [ -d "$LED_ROOT/$EASYMANET_LED_NAME" ]; then
        printf '%s\n' "$LED_ROOT/$EASYMANET_LED_NAME"
        return 0
    fi

    for name in ACT act led0; do
        if [ -d "$LED_ROOT/$name" ]; then
            printf '%s\n' "$LED_ROOT/$name"
            return 0
        fi
    done

    for led in "$LED_ROOT"/*; do
        [ -d "$led" ] || continue
        case "$(basename "$led" | tr '[:upper:]' '[:lower:]')" in
            *green*|*act*)
                printf '%s\n' "$led"
                return 0
                ;;
        esac
    done

    return 1
}

set_led() {
    led="$1"
    value="$2"
    if [ -w "$led/trigger" ]; then
        echo none > "$led/trigger" 2>/dev/null || true
    fi
    echo "$value" > "$led/brightness"
}

log "LED root: $LED_ROOT"
if [ ! -d "$LED_ROOT" ]; then
    log "No LED sysfs directory found."
    exit 1
fi

log "Available LEDs:"
for led in "$LED_ROOT"/*; do
    [ -d "$led" ] || continue
    name="$(basename "$led")"
    brightness="$(cat "$led/brightness" 2>/dev/null || printf '?')"
    max_brightness="$(cat "$led/max_brightness" 2>/dev/null || printf '?')"
    trigger="$(cat "$led/trigger" 2>/dev/null || printf '?')"
    log "- $name"
    log "  brightness: $brightness / $max_brightness"
    log "  trigger: $trigger"
done

detected="$(detect_led || true)"
if [ -z "$detected" ]; then
    log "Detected EasyMANET candidate: none"
    exit 1
fi

log "Detected EasyMANET candidate: $(basename "$detected")"

case "${1:-}" in
    ""|--blink)
        ;;
    *)
        echo "usage: $0 [--blink]" >&2
        exit 2
        ;;
esac

if [ "${1:-}" = "--blink" ]; then
    log "Blinking $(basename "$detected") three times..."
    i=0
    while [ "$i" -lt 3 ]; do
        set_led "$detected" 1
        sleep 1
        set_led "$detected" 0
        sleep 1
        i=$((i + 1))
    done
fi
