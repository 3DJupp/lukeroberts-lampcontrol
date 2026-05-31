# Luke Roberts Lamp Control

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant **Custom Addon** that acts as a direct BLE Bluetooth gateway
for [Luke Roberts](https://luke-roberts.com) smart lamps (Model F / Luvo).

**No ESPHome required — no extra hardware required.**

The addon runs on the Home Assistant host, connects to the lamp over the
built-in Bluetooth adapter, and exposes a full `light` entity in HA via
MQTT Auto-Discovery — just like a Shelly or ESPHome device would.

## Features

- On/Off, brightness (0–100 %), colour temperature (2700–4000 K)
- Automatic scene discovery (up to 16 scenes) → HA light effects
- Keepalive to prevent firmware idle-disconnect
- Reconnects automatically after BLE drops
- MQTT Auto-Discovery (no manual entity configuration needed)
- Multi-architecture: aarch64, amd64, armhf, armv7

## Installation

See [DOCS.md](DOCS.md) for full installation and configuration instructions.

Quick start:

1. Add this repository to your HA Addon Store:
   `https://github.com/3DJupp/lukeroberts-lampcontrol`
2. Install **Luke Roberts Lamp Control**
3. Set your lamp's MAC address in the addon options
4. Start the addon — entities appear in HA automatically

## Protocol

Uses the Luke Roberts **Lamp Control API v1.3** over BLE:

| Command | Bytes |
|---|---|
| Ping / keepalive | `A0 02 00` |
| Select scene | `A0 02 05 <id>` |
| Set brightness | `A0 01 03 <pct>` |
| Set colour temp | `A0 01 04 <K_hi> <K_lo>` |
| Immediate light | `A0 01 02 <flags> <dur> <dur> <K_hi> <K_lo> <bri>` |
| Query scene name | `A0 01 01 <id>` |

BLE characteristic: `44092842-0567-11E6-B862-0002A5D5C51B`

## Credits

Protocol documentation: Luke Roberts GmbH  
Inspired by [lukeroberts-esphome-lampcontrol](https://github.com/3DJupp/lukeroberts-esphome-lampcontrol)

## License

MIT
