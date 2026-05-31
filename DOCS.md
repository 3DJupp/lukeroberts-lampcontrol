# Luke Roberts Lamp Control – Addon Documentation

Standalone Home Assistant addon that acts as a **BLE Bluetooth proxy** for
Luke Roberts smart lamps (Model F / Luvo).  No ESPHome, no extra hardware —
the addon runs directly on the Home Assistant host, connects to the lamp over
Bluetooth, and exposes a full `light` entity via **MQTT Auto-Discovery**.

## Requirements

- Home Assistant OS or Supervised (with access to the host Bluetooth adapter)
- A running **MQTT broker** (the [Mosquitto addon][mosquitto] works out of the box)
- A Luke Roberts lamp (Model F or Luvo) within Bluetooth range
- The lamp's **Bluetooth MAC address** (find it in the Luke Roberts app under
  Settings → Lamp → Connection info)

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu → **Repositories** and add:
   ```
   https://github.com/3DJupp/lukeroberts-lampcontrol
   ```
3. Find **Luke Roberts Lamp Control** and click **Install**

## Configuration

| Option | Default | Description |
|---|---|---|
| `lamp_mac` | *(required)* | Lamp Bluetooth MAC address, e.g. `AA:BB:CC:DD:EE:FF` |
| `lamp_name` | `Luke Roberts Lamp` | Friendly name shown in Home Assistant |
| `mqtt_host` | `core-mosquitto` | MQTT broker hostname or IP |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_user` | *(empty)* | MQTT username (leave blank if not required) |
| `mqtt_password` | *(empty)* | MQTT password |
| `mqtt_topic_prefix` | `lukeroberts` | Topic prefix; entities appear under `<prefix>/<mac>/…` |
| `log_level` | `info` | Log verbosity: `debug`, `info`, `warning`, `error` |

## How it works

1. On startup the addon connects to the lamp over BLE.
2. It reads the **Device Information** (manufacturer, model, firmware) and
   walks the lamp's **scene list** (up to 16 scenes) using the Luke Roberts
   Lamp Control API v1.3.
3. It publishes an MQTT Auto-Discovery message so Home Assistant automatically
   creates a `light` entity with:
   - **On / Off** control
   - **Brightness** (0–100 %)
   - **Colour temperature** (2700 K – 4000 K)
   - **Effects** — one entry per scene discovered on the lamp
4. A **keepalive ping** is sent every 6 s while the lamp is in use, preventing
   the firmware's 8 s idle-disconnect.

## MQTT topics

| Topic | Direction | Description |
|---|---|---|
| `lukeroberts/<mac>/availability` | addon → HA | `online` / `offline` |
| `lukeroberts/<mac>/light/state` | addon → HA | JSON state (brightness, color_temp, effect) |
| `lukeroberts/<mac>/light/set` | HA → addon | JSON command |
| `lukeroberts/<mac>/scenes` | addon → HA | Raw scene list (JSON) |

### Command examples

Turn off:
```json
{"state": "OFF"}
```

Turn on at 60 % brightness, 3000 K:
```json
{"state": "ON", "brightness": 153, "color_temp": 333}
```

Activate a scene:
```json
{"state": "ON", "effect": "Reading"}
```

## Lovelace dashboard

A sample card is provided in [`dashboard/lamp-card.yaml`](dashboard/lamp-card.yaml).
Replace `aabbccddeeff` with your lamp's MAC (colons removed, lowercase).

## Troubleshooting

- **Lamp not found** — verify the MAC address; ensure Bluetooth is enabled on
  the HA host and the lamp is powered on and within range.
- **MQTT not connecting** — check broker hostname/port and credentials; make
  sure the Mosquitto addon (or your external broker) is running.
- **No entities in HA** — confirm that MQTT integration is set up in HA
  (`Settings → Devices & Services → Add Integration → MQTT`).
- **Scenes not updating** — the addon re-enumerates scenes on every BLE
  reconnect; power-cycle the lamp or restart the addon to force a refresh.

[mosquitto]: https://github.com/home-assistant/addons/tree/master/mosquitto
