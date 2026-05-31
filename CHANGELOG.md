# Changelog

## 1.0.0 – 2026-05-31

- Initial release
- Direct BLE connection to Luke Roberts lamps (Model F / Luvo) from HA host
- MQTT Auto-Discovery: `light` entity with brightness, colour temperature, scenes
- Full scene enumeration on connect using Lamp Control API v1.3 linked-list walk
- Keepalive ping every 6 s (within 30 s of last user command)
- Automatic reconnect with exponential back-off (5 s → 60 s)
- Device Information Service read-out (manufacturer, model, firmware)
- Multi-arch images: aarch64, amd64, armhf, armv7
