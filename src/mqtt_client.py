"""MQTT client with Home Assistant Auto-Discovery.

Publishes a `light` entity and handles JSON-schema commands from HA.
Compatible with Mosquitto and any standards-compliant broker.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt_lib

logger = logging.getLogger(__name__)

KELVIN_MIN = 2700
KELVIN_MAX = 4000


def _kelvin_to_mired(k: int) -> int:
    return max(1, round(1_000_000 / max(1, k)))


def _mired_to_kelvin(m: int) -> int:
    return max(KELVIN_MIN, min(KELVIN_MAX, round(1_000_000 / max(1, m))))


class MQTTClient:
    def __init__(self, config: dict, lamp) -> None:
        self._cfg  = config
        self._lamp = lamp

        mac_clean     = lamp.mac.replace(":", "").lower()
        prefix        = config.get("mqtt_topic_prefix", "lukeroberts")
        self._base    = f"{prefix}/{mac_clean}"
        self._uid     = f"lukeroberts_{mac_clean}"

        self._client:    Optional[mqtt_lib.Client]           = None
        self._loop:      Optional[asyncio.AbstractEventLoop] = None
        self._connected: bool = False

    # ── Topics ────────────────────────────────────────────────────────────────

    @property
    def _avail_t(self)  -> str: return f"{self._base}/availability"
    @property
    def _state_t(self)  -> str: return f"{self._base}/light/state"
    @property
    def _cmd_t(self)    -> str: return f"{self._base}/light/set"
    @property
    def _scenes_t(self) -> str: return f"{self._base}/scenes"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._loop   = asyncio.get_running_loop()
        self._client = mqtt_lib.Client(client_id=self._uid, clean_session=True)

        if self._cfg.get("mqtt_user"):
            self._client.username_pw_set(
                self._cfg["mqtt_user"],
                self._cfg.get("mqtt_password", ""),
            )

        self._client.will_set(self._avail_t, "offline", retain=True, qos=1)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        host = self._cfg.get("mqtt_host", "core-mosquitto")
        port = int(self._cfg.get("mqtt_port", 1883))
        logger.info("Connecting to MQTT broker %s:%d", host, port)
        self._client.connect_async(host, port, keepalive=60)
        self._client.loop_start()

        for _ in range(60):
            if self._connected:
                return
            await asyncio.sleep(0.5)
        logger.error("Could not connect to MQTT broker within 30 s")

    # ── MQTT callbacks (run in paho thread) ───────────────────────────────────

    def _on_connect(self, client, _userdata, _flags, rc: int) -> None:
        if rc != 0:
            logger.error("MQTT connect failed (rc=%d)", rc)
            return
        logger.info("MQTT connected")
        self._connected = True
        client.subscribe(self._cmd_t, qos=1)
        # Publish discovery and mark offline until BLE connects
        self._publish_discovery()
        client.publish(self._avail_t, "offline", retain=True, qos=1)

    def _on_disconnect(self, _client, _userdata, rc: int) -> None:
        logger.warning("MQTT disconnected (rc=%d)", rc)
        self._connected = False

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except Exception:
            logger.warning("Invalid JSON on %s: %r", msg.topic, msg.payload)
            return
        asyncio.run_coroutine_threadsafe(self._handle_cmd(payload), self._loop)

    # ── Command handler ───────────────────────────────────────────────────────

    async def _handle_cmd(self, payload: dict) -> None:
        lamp = self._lamp
        if not lamp.connected:
            logger.warning("Command arrived but lamp is not connected")
            return

        raw_state    = payload.get("state", "").upper()
        brightness   = payload.get("brightness")    # 0-255 (HA default scale)
        color_mired  = payload.get("color_temp")    # mireds
        effect       = payload.get("effect")

        if raw_state == "OFF":
            await lamp.turn_off()
            return

        kwargs = {}
        if effect:
            kwargs["scene_name"] = effect
        else:
            if brightness is not None:
                # HA sends 0-255; lamp uses 0-100 percent
                kwargs["brightness_pct"] = round(int(brightness) * 100 / 255)
            if color_mired is not None:
                kwargs["color_temp_k"] = _mired_to_kelvin(int(color_mired))

        await lamp.turn_on(**kwargs)

    # ── HA MQTT Auto-Discovery ────────────────────────────────────────────────

    def _device_payload(self) -> dict:
        di = self._lamp.device_info
        d: dict = {
            "identifiers":  [self._uid],
            "name":         self._lamp.name,
            "manufacturer": di.get("manufacturer", "Luke Roberts"),
            "model":        di.get("model", "Model F / Luvo"),
            "connections":  [["mac", self._lamp.mac]],
        }
        if di.get("fw_rev"):
            d["sw_version"] = di["fw_rev"]
        if di.get("serial"):
            d["serial_number"] = di["serial"]
        return d

    def _publish_discovery(self, scene_names: Optional[List[str]] = None) -> None:
        if not self._connected:
            return

        # Build effect list: named scenes (exclude Off=0 from effects; Off is
        # handled via state:OFF). Default scene 0xFF is included if present.
        effects = scene_names if scene_names is not None else self._build_effect_list()

        payload = {
            "name":               self._lamp.name,
            "unique_id":          f"{self._uid}_light",
            "object_id":          self._uid,
            "schema":             "json",
            "state_topic":        self._state_t,
            "command_topic":      self._cmd_t,
            "availability":       [{"topic": self._avail_t}],
            "payload_available":  "online",
            "payload_not_available": "offline",
            "brightness":         True,
            "color_temp":         True,
            "min_mireds":         _kelvin_to_mired(KELVIN_MAX),
            "max_mireds":         _kelvin_to_mired(KELVIN_MIN),
            "effect":             True,
            "effect_list":        effects,
            "device":             self._device_payload(),
        }
        disc_topic = f"homeassistant/light/{self._uid}/config"
        self._client.publish(disc_topic, json.dumps(payload), retain=True, qos=1)
        logger.debug("Discovery → %s", disc_topic)

    def _build_effect_list(self) -> List[str]:
        """Scene names sorted by id; scene 0 (Off) excluded from effects."""
        result = []
        for sid, name in sorted(self._lamp.scenes.items()):
            if sid == 0x00:  # Off handled via state:OFF
                continue
            result.append(name)
        return result

    # ── Lamp event handler (called from lamp via asyncio) ─────────────────────

    async def on_lamp_event(self, event: dict) -> None:
        if "available" in event:
            await self._publish_availability(event["available"])
        if "state" in event:
            await self._publish_state(event["state"])
        if "scenes" in event:
            await self._publish_scenes(event["scenes"])

    async def _publish_availability(self, available: bool) -> None:
        if not self._connected:
            return
        payload = "online" if available else "offline"
        self._client.publish(self._avail_t, payload, retain=True, qos=1)
        logger.info("Availability: %s", payload)

    async def _publish_state(self, state) -> None:
        if not self._connected:
            return
        msg: dict = {
            "state":       "ON" if state.on else "OFF",
            "brightness":  round(state.brightness * 255 / 100),
            "color_temp":  _kelvin_to_mired(state.color_temp_k),
        }
        if state.scene_name and state.on and state.scene_id != 0x00:
            msg["effect"] = state.scene_name
        self._client.publish(self._state_t, json.dumps(msg), retain=True, qos=1)
        logger.debug("State → %s", msg)

    async def _publish_scenes(self, scenes: Dict[int, str]) -> None:
        effect_list = self._build_effect_list()
        self._publish_discovery(effect_list)

        raw = {str(sid): name for sid, name in sorted(scenes.items())}
        self._client.publish(self._scenes_t, json.dumps(raw), retain=True, qos=1)
        logger.info("Scenes published (%d total)", len(scenes))
