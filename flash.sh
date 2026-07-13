#!/usr/bin/env bash
# Build + flash the ESP32-S3 Linux emulator (app + patched kernel Image).
# Usage: ./flash.sh [PORT]   (default /dev/ttyACM0)
set -euo pipefail
PORT="${1:-/dev/ttyACM0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

cd "$HERE"

# Activate ESP-IDF v5.3 (skipped if idf.py is already on PATH).
if ! command -v idf.py >/dev/null 2>&1; then
    if [[ -n "${IDF_PATH:-}" && -f "$IDF_PATH/export.sh" ]]; then
        # shellcheck disable=SC1091
        source "$IDF_PATH/export.sh"
    else
        echo "ESP-IDF not found. Activate it first (v5.3), e.g.:" >&2
        echo "  . \"\$IDF_PATH/export.sh\"" >&2
        exit 1
    fi
fi

# The uplink WiFi credentials are gitignored; create them from the template.
if [[ ! -f main/wifi_creds.h ]]; then
    echo "main/wifi_creds.h is missing. Create it from the template:" >&2
    echo "  cp main/wifi_creds.h.example main/wifi_creds.h   # then edit it" >&2
    exit 1
fi

echo "=== build ==="
idf.py build

echo "=== flash bootloader + partition table + app ==="
idf.py -p "$PORT" -b 921600 flash

KERNEL="main/Image_mmu"
ROOTFS="main/rootfs.ext4"
[[ -f "$KERNEL" ]] || { echo "Missing $KERNEL" >&2; exit 1; }
[[ -f "$ROOTFS" ]] || { echo "Missing $ROOTFS" >&2; exit 1; }
(( $(stat -c %s "$KERNEL") <= 6 * 1024 * 1024 )) || { echo "Kernel exceeds 6MB partition" >&2; exit 1; }
(( $(stat -c %s "$ROOTFS") <= 8 * 1024 * 1024 )) || { echo "Rootfs exceeds 8MB partition" >&2; exit 1; }

echo "=== flash MMU kernel @ 0x110000 + ext4 rootfs @ 0x710000 ==="
esptool.py --chip esp32s3 -p "$PORT" -b 921600 \
    --before default_reset --after hard_reset \
    write_flash 0x110000 "$KERNEL" 0x710000 "$ROOTFS"

echo "=== done. Connect to WiFi 'esp32-linux' (pass 'linux1234') and: telnet 192.168.4.1 ==="
echo "    or watch the local serial boot:  python tools/capture_boot.py 60"
