"""BLE driver for Luke Roberts smart lamps (Model F / Luvo).

Protocol reference: Luke Roberts Lamp Control API v1.3 (2019-07-09)
  Control Service:   44092840-0567-11E6-B862-0002A5D5C51B
  External API char: 44092842-0567-11E6-B862-0002A5D5C51B  (write + notify)

All commands start with 0xA0 followed by the API version byte.
Responses arrive as BLE notifications on the same characteristic.
"""

import asyncio
import logging
from typing import Callable, Dict, Optional

from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError, BleakError

logger = logging.getLogger(__name__)

# ── UUIDs ────────────────────────────────────────────────────────────────────
CTRL_CHAR = "44092842-0567-11e6-b862-0002a5d5c51b"

DIS_CHARS = {
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "model":        "00002a24-0000-1000-8000-00805f9b34fb",
    "serial":       "00002a25-0000-1000-8000-00805f9b34fb",
    "hw_rev":       "00002a27-0000-1000-8000-00805f9b34fb",
    "fw_rev":       "00002a26-0000-1000-8000-00805f9b34fb",
    "sw_rev":       "00002a28-0000-1000-8000-00805f9b34fb",
}

# ── Scene IDs ────────────────────────────────────────────────────────────────
SCENE_OFF     = 0x00   # scene 0 = lamp off
SCENE_DEFAULT = 0xFF   # lamp's configured power-on scene

# ── Protocol constants ────────────────────────────────────────────────────────
KEEPALIVE_INTERVAL_S = 6.0   # must be < 8 s lamp idle timeout
KEEPALIVE_WINDOW_S   = 30.0  # how long after a command to keep sending pings

STATUS = {
    0x00: "OK",
    0x81: "Invalid Params",
    0x84: "Invalid Id",
    0x87: "Invalid Version",
    0xBC: "Bad Command",
    0xFC: "Forbidden",
}

KELVIN_MIN = 2700
KELVIN_MAX = 4000


# ── Command builders ──────────────────────────────────────────────────────────

def _ping() -> bytes:
    return bytes([0xA0, 0x02, 0x00])

def _query_scene(scene_id: int) -> bytes:
    return bytes([0xA0, 0x01, 0x01, scene_id & 0xFF])

def _select_scene(scene_id: int) -> bytes:
    return bytes([0xA0, 0x02, 0x05, scene_id & 0xFF])

def _set_brightness(percent: int) -> bytes:
    return bytes([0xA0, 0x01, 0x03, max(0, min(100, percent))])

def _set_color_temp(kelvin: int) -> bytes:
    k = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
    return bytes([0xA0, 0x01, 0x04, (k >> 8) & 0xFF, k & 0xFF])

def _immediate_light(flags: int, duration_ms: int, kelvin: int, brightness_255: int) -> bytes:
    """Immediate Light command (opcode 02).

    flags: bit0=uplight, bit1=downlight
    duration_ms: 0 = infinite (stays until next scene select)
    brightness_255: 0-255 scale
    """
    d = max(0, duration_ms)
    k = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
    b = max(0, min(255, brightness_255))
    return bytes([
        0xA0, 0x01, 0x02,
        flags & 0xFF,
        (d >> 8) & 0xFF, d & 0xFF,
        (k >> 8) & 0xFF, k & 0xFF,
        b,
    ])


# ── State dataclass ───────────────────────────────────────────────────────────

class LampState:
    def __init__(self) -> None:
        self.on:           bool          = False
        self.brightness:   int           = 100      # 0-100 percent
        self.color_temp_k: int           = 3000     # Kelvin
        self.scene_id:     Optional[int] = None
        self.scene_name:   Optional[str] = None


# ── Main lamp class ───────────────────────────────────────────────────────────

class LukeRobertsLamp:
    """Manages a persistent BLE connection to a single Luke Roberts lamp."""

    def __init__(self, mac: str, name: str = "Luke Roberts Lamp") -> None:
        self.mac         = mac.upper()
        self.name        = name
        self.state       = LampState()
        self.scenes:     Dict[int, str]  = {}
        self.device_info: Dict[str, str] = {}
        self.connected   = False

        self._client:          Optional[BleakClient] = None
        self._notify_event     = asyncio.Event()
        self._notify_data:     Optional[bytes] = None
        self._cmd_lock         = asyncio.Lock()
        self._enum_lock        = asyncio.Lock()
        self._last_cmd_time:   float = 0.0
        self._want_keepalive:  bool  = False

        # Callbacks set by MQTTClient
        self._on_event: Optional[Callable] = None

    # ── Public lifecycle ──────────────────────────────────────────────────────

    async def run(self, on_event: Callable) -> None:
        """Connect and reconnect forever; call on_event(dict) on state changes."""
        self._on_event = on_event
        retry = 5
        while True:
            try:
                await self._connect_and_run()
                retry = 5
            except BleakDeviceNotFoundError:
                logger.warning("Lamp %s not found, retry in %ds", self.mac, retry)
            except BleakError as exc:
                logger.warning("BLE error: %s, retry in %ds", exc, retry)
            except Exception as exc:
                logger.error("Unexpected error: %s", exc, exc_info=True)
            finally:
                self.connected = False
                await self._emit(available=False)
            await asyncio.sleep(retry)
            retry = min(retry * 2, 60)

    # ── Public commands ───────────────────────────────────────────────────────

    async def turn_off(self) -> None:
        await self._send(_select_scene(SCENE_OFF))
        self.state.on         = False
        self.state.scene_id   = SCENE_OFF
        self.state.scene_name = self.scenes.get(SCENE_OFF)
        await self._emit(state=self.state)

    async def turn_on(
        self,
        brightness_pct:  Optional[int] = None,
        color_temp_k:    Optional[int] = None,
        scene_name:      Optional[str] = None,
    ) -> None:
        if scene_name is not None:
            sid = self._resolve_scene(scene_name)
            if sid is None:
                logger.warning("Scene '%s' not found", scene_name)
                return
            await self._send(_select_scene(sid))
            if brightness_pct is not None:
                await asyncio.sleep(0.1)
                await self._send(_set_brightness(brightness_pct))
            if color_temp_k is not None:
                await asyncio.sleep(0.1)
                await self._send(_set_color_temp(color_temp_k))
            self.state.on         = True
            self.state.scene_id   = sid
            self.state.scene_name = scene_name
            if brightness_pct is not None:
                self.state.brightness = brightness_pct
            if color_temp_k is not None:
                self.state.color_temp_k = color_temp_k
        elif brightness_pct is not None or color_temp_k is not None:
            # Use Immediate Light for direct brightness/colour control
            bri_pct = brightness_pct if brightness_pct is not None else self.state.brightness
            k       = color_temp_k   if color_temp_k   is not None else self.state.color_temp_k
            bri_255 = round(bri_pct * 255 / 100)
            # flags=0x02 → downlight sub-packet; duration=0 → infinite
            await self._send(_immediate_light(0x02, 0, k, bri_255))
            self.state.on           = True
            self.state.brightness   = bri_pct
            self.state.color_temp_k = k
            self.state.scene_id     = None
            self.state.scene_name   = None
        else:
            # Plain ON → select default (power-on) scene
            await self._send(_select_scene(SCENE_DEFAULT))
            self.state.on         = True
            self.state.scene_id   = SCENE_DEFAULT
            self.state.scene_name = self.scenes.get(SCENE_DEFAULT)

        await self._emit(state=self.state)

    async def set_brightness(self, percent: int) -> None:
        await self._send(_set_brightness(percent))
        self.state.brightness = percent
        if percent == 0:
            self.state.on = False
        await self._emit(state=self.state)

    async def set_color_temp(self, kelvin: int) -> None:
        await self._send(_set_color_temp(kelvin))
        self.state.color_temp_k = kelvin
        await self._emit(state=self.state)

    async def refresh_scenes(self) -> None:
        await self._enumerate_scenes()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_scene(self, name: str) -> Optional[int]:
        for sid, sname in self.scenes.items():
            if sname == name:
                return sid
        return None

    async def _connect_and_run(self) -> None:
        logger.info("Connecting to %s …", self.mac)
        self._client = BleakClient(self.mac, disconnected_callback=self._on_disconnect)
        await self._client.connect(timeout=20.0)
        self.connected = True
        logger.info("Connected to lamp %s", self.mac)

        await self._client.start_notify(CTRL_CHAR, self._on_notification)
        await self._read_device_info()
        await self._emit(available=True)
        await self._enumerate_scenes()

        keepalive = asyncio.create_task(self._keepalive_loop())
        try:
            while self.connected:
                await asyncio.sleep(1)
        finally:
            keepalive.cancel()
            try:
                await keepalive
            except asyncio.CancelledError:
                pass

    def _on_disconnect(self, _client: BleakClient) -> None:
        logger.warning("Lamp disconnected")
        self.connected = False

    def _on_notification(self, _handle: int, data: bytearray) -> None:
        self._notify_data = bytes(data)
        self._notify_event.set()
        status = data[0] if data else 0xFF
        logger.debug("Notify ← %s  [%s]", data.hex(), STATUS.get(status, f"0x{status:02X}"))

    async def _wait_notify(self, timeout: float = 2.0) -> Optional[bytes]:
        self._notify_event.clear()
        try:
            await asyncio.wait_for(self._notify_event.wait(), timeout)
            return self._notify_data
        except asyncio.TimeoutError:
            return None

    async def _send(self, cmd: bytes) -> Optional[bytes]:
        if not self.connected or not self._client:
            logger.warning("Not connected — dropping command %s", cmd.hex())
            return None
        async with self._cmd_lock:
            try:
                logger.debug("Send → %s", cmd.hex())
                await self._client.write_gatt_char(CTRL_CHAR, cmd, response=False)
                self._last_cmd_time  = asyncio.get_event_loop().time()
                self._want_keepalive = True
                return await self._wait_notify()
            except BleakError as exc:
                logger.error("Write failed: %s", exc)
                return None

    async def _read_device_info(self) -> None:
        info: Dict[str, str] = {}
        for key, uuid in DIS_CHARS.items():
            try:
                raw = await self._client.read_gatt_char(uuid)
                val = raw.decode("utf-8", errors="replace").strip("\x00 ")
                if val:
                    info[key] = val
            except Exception:
                pass
        self.device_info = info
        logger.info("Device info: %s", info)

    async def _enumerate_scenes(self) -> None:
        if not self.connected:
            return
        async with self._enum_lock:
            logger.info("Enumerating scenes …")
            scenes: Dict[int, str] = {}

            # Follow the lamp's linked-list enumeration starting at scene 0.
            # Each response's byte [2] is the next ID to query; 0xFF signals end.
            current_id = SCENE_OFF
            while True:
                resp = await self._send(_query_scene(current_id))
                if not resp or len(resp) < 4:
                    logger.debug("Scene %d: no valid response — stopping", current_id)
                    break
                if resp[0] != 0x00:
                    logger.debug(
                        "Scene %d: %s — stopping",
                        current_id, STATUS.get(resp[0], f"0x{resp[0]:02X}"),
                    )
                    break
                if resp[1] != 0x01:
                    logger.debug("Scene %d: unexpected opcode 0x%02X", current_id, resp[1])
                    break

                next_id = resp[2]
                name    = resp[3:].split(b"\x00")[0].decode("utf-8", errors="replace").strip()
                if not name:
                    name = f"Scene {current_id}"
                scenes[current_id] = name
                logger.debug("  [%d] '%s'  → next 0x%02X", current_id, name, next_id)

                if next_id == 0xFF or next_id == current_id:
                    break
                current_id = next_id
                await asyncio.sleep(0.1)

            # Also fetch the default (power-on) scene name
            resp = await self._send(_query_scene(SCENE_DEFAULT))
            if resp and len(resp) >= 4 and resp[0] == 0x00:
                name = resp[3:].split(b"\x00")[0].decode("utf-8", errors="replace").strip()
                if name:
                    scenes[SCENE_DEFAULT] = name

            self.scenes = scenes
            logger.info("Scenes found: %s", {k: v for k, v in scenes.items()})
            if self._on_event:
                await self._on_event({"scenes": scenes})

    async def _keepalive_loop(self) -> None:
        while self.connected:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            if not self.connected:
                break
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_cmd_time
            if self._want_keepalive and elapsed < KEEPALIVE_WINDOW_S:
                await self._send(_ping())
            elif elapsed >= KEEPALIVE_WINDOW_S:
                self._want_keepalive = False

    async def _emit(self, **kwargs) -> None:
        if self._on_event:
            await self._on_event(kwargs)
