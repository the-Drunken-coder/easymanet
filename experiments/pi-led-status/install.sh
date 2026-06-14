#!/bin/sh
set -eu

target="${1:-}"
if [ -z "$target" ]; then
    echo "usage: $0 root@10.41.254.1" >&2
    exit 2
fi

script_dir="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
remote_dir="/tmp/easymanet-led"

ssh "$target" "mkdir -p '$remote_dir'"
scp \
    "$script_dir/probe-leds.sh" \
    "$script_dir/led-internet-status.sh" \
    "$target:$remote_dir/"
ssh "$target" "chmod +x '$remote_dir/probe-leds.sh' '$remote_dir/led-internet-status.sh'"

cat <<EOF
Installed LED experiment scripts to $target:$remote_dir

Probe:
  ssh $target $remote_dir/probe-leds.sh

Blink detected LED:
  ssh $target $remote_dir/probe-leds.sh --blink

Run internet status loop:
  ssh $target $remote_dir/led-internet-status.sh
EOF
