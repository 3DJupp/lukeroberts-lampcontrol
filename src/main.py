"""Luke Roberts Lamp Control – Home Assistant Addon entry point."""

import asyncio
import logging
import signal
import sys

import config as cfg_mod
from lamp import LukeRobertsLamp
from mqtt_client import MQTTClient


async def main() -> None:
    config = cfg_mod.load()

    log_level = getattr(logging, config["log_level"].upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logger = logging.getLogger(__name__)
    logger.info("Luke Roberts Lamp Control starting (lamp MAC: %s)", config["lamp_mac"])

    lamp = LukeRobertsLamp(config["lamp_mac"], config["lamp_name"])
    mqtt = MQTTClient(config, lamp)

    # Connect to MQTT first so discovery is ready before BLE connects
    await mqtt.start()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown(lamp, mqtt, logger)))

    # Run the BLE connection loop (reconnects forever)
    await lamp.run(on_event=mqtt.on_lamp_event)


async def _shutdown(lamp, mqtt, logger) -> None:
    logger.info("Shutting down …")
    if lamp.connected:
        await mqtt._publish_availability(False)
        if lamp._client:
            try:
                await lamp._client.disconnect()
            except Exception:
                pass
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    asyncio.run(main())
