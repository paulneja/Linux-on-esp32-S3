#!/usr/bin/env bash
# Build + flash the ESP32-S3 Linux emulator (app + patched kernel Image).
# Usage: ./flash.sh [PORT]   (default /dev/ttyACM0)
set -euo pipefail
PORT="${1:-/dev/ttyACM0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

source "$HOME/esp/idfenv.sh"
cd "$HERE"

echo "=== build ==="
idf.py build

echo "=== flash bootloader + partition table + app ==="
idf.py -p "$PORT" -b 921600 flash

echo "=== flash kernel Image @ 0x110000 ==="
esptool.py --chip esp32s3 -p "$PORT" -b 921600 \
    --before default_reset --after hard_reset \
    write_flash 0x110000 main/Image

echo "=== done. Connect to WiFi 'esp32-linux' (pass 'linux1234') and: telnet 192.168.4.1 ==="
echo "    or watch the local serial boot:  python tools/capture_boot.py 60"
