"""Load addon options from /data/options.json (written by HA Supervisor)."""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

OPTIONS_FILE = "/data/options.json"

DEFAULTS = {
    "lamp_mac":          "",
    "lamp_name":         "Luke Roberts Lamp",
    "mqtt_host":         "core-mosquitto",
    "mqtt_port":         1883,
    "mqtt_user":         "",
    "mqtt_password":     "",
    "mqtt_topic_prefix": "lukeroberts",
    "log_level":         "info",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(OPTIONS_FILE):
        with open(OPTIONS_FILE) as fh:
            opts = json.load(fh)
        cfg.update({k: v for k, v in opts.items() if v != "" or k not in DEFAULTS})
    else:
        logger.warning("Options file %s not found — using defaults", OPTIONS_FILE)

    if not cfg.get("lamp_mac"):
        logger.error("lamp_mac is required. Please configure it in the addon options.")
        sys.exit(1)

    return cfg
