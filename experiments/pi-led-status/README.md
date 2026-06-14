# Pi LED Status Experiment

Small live-test scripts for proving Raspberry Pi onboard LED control before
baking it into the EasyMANET image.

The intended loop is:

1. Flash and boot a normal EasyMANET node.
2. SSH into it.
3. Upload these scripts.
4. Probe available LEDs.
5. Run the internet-status loop and watch the green LED.

## Install

Pass the reachable radio hostname/IP as the first argument:

```sh
./experiments/pi-led-status/install.sh root@10.41.254.1
```

## Probe

```sh
ssh root@10.41.254.1 /tmp/easymanet-led/probe-leds.sh
```

To blink the detected green/ACT LED three times:

```sh
ssh root@10.41.254.1 /tmp/easymanet-led/probe-leds.sh --blink
```

## Run Status Loop

```sh
ssh root@10.41.254.1 /tmp/easymanet-led/led-internet-status.sh
```

The loop turns the detected green/ACT LED on when the radio can reach the
public internet and off when it cannot.

Run one check and exit:

```sh
ssh root@10.41.254.1 /tmp/easymanet-led/led-internet-status.sh --once
```

Useful overrides:

```sh
EASYMANET_LED_NAME=ACT /tmp/easymanet-led/led-internet-status.sh
EASYMANET_LED_TARGETS="1.1.1.1 8.8.8.8" /tmp/easymanet-led/led-internet-status.sh
EASYMANET_LED_INTERVAL=5 /tmp/easymanet-led/led-internet-status.sh
```
