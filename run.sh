#!/usr/bin/env bash
set -e

echo "[Info] Starting Luke Roberts Lamp Control"
cd /app
exec python3 -u main.py
