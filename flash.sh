#!/bin/sh
#
# Flash Linux on an ESP32-S3 (native Xtensa build).
#
# Default: writes the single combined image to offset 0x0 — everything a bare
# board needs (bootloader, partition table, WiFi firmware, /etc, kernel,
# rootfs). Nothing else is required.
#
#   ./flash.sh                      # combined image, autodetected port
#   ./flash.sh -p /dev/ttyUSB0      # pick the port
#   ./flash.sh --erase              # full chip erase first (recommended once)
#   ./flash.sh --parts              # flash the 6 pieces separately instead
#
# Requires esptool (pip install esptool) or an activated ESP-IDF environment.
# Board: ESP32-S3 with 16 MB flash / 8 MB Octal PSRAM (N16R8).
#
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMG="$DIR/images"
PORT=""
ERASE=0
PARTS=0

usage() { sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
	case "$1" in
	-p|--port) PORT="${2:?-p needs a port}"; shift 2 ;;
	--erase)   ERASE=1; shift ;;
	--parts)   PARTS=1; shift ;;
	-h|--help) usage 0 ;;
	*) echo "unknown option: $1" >&2; usage 1 >&2 ;;
	esac
done

# --- locate esptool -----------------------------------------------------
if command -v esptool.py >/dev/null 2>&1; then
	ESPTOOL="esptool.py"
elif command -v esptool >/dev/null 2>&1; then
	ESPTOOL="esptool"
elif python3 -c 'import esptool' >/dev/null 2>&1; then
	ESPTOOL="python3 -m esptool"
else
	echo "error: esptool not found. Install it with:" >&2
	echo "    pip install esptool" >&2
	echo "or activate your ESP-IDF environment (. \$IDF_PATH/export.sh)." >&2
	exit 1
fi

# --- locate the board ---------------------------------------------------
if [ -z "$PORT" ]; then
	for p in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0 /dev/ttyUSB1; do
		[ -e "$p" ] && { PORT="$p"; break; }
	done
	[ -n "$PORT" ] || { echo "error: no board found; pass -p /dev/ttyXXX" >&2; exit 1; }
	echo "Using port $PORT (override with -p)"
fi

COMMON="--chip esp32s3 -p $PORT -b 460800 --before default_reset --after hard_reset"
FLASHOPTS="--flash_mode dio --flash_size 16MB --flash_freq 80m"

if [ "$ERASE" = 1 ]; then
	echo "==> Erasing the whole chip (this wipes /home too)"
	# shellcheck disable=SC2086
	$ESPTOOL --chip esp32s3 -p "$PORT" -b 460800 erase_flash
fi

if [ "$PARTS" = 1 ]; then
	echo "==> Flashing the 6 images separately"
	# shellcheck disable=SC2086
	$ESPTOOL $COMMON write_flash $FLASHOPTS \
		0x0      "$IMG/bootloader.bin" \
		0x8000   "$IMG/partition-table.bin" \
		0x10000  "$IMG/network_adapter.bin" \
		0xb0000  "$IMG/etc.jffs2" \
		0x120000 "$IMG/xipImage" \
		0x5a0000 "$IMG/rootfs.cramfs"
else
	echo "==> Flashing the combined image at 0x0"
	# shellcheck disable=SC2086
	$ESPTOOL $COMMON write_flash $FLASHOPTS \
		0x0 "$IMG/linux-esp32s3-native-full.bin"
fi

cat <<'EOF'

Done. Open the serial console at 115200 baud, e.g.:

    screen /dev/ttyACM0 115200      (or: picocom -b 115200 /dev/ttyACM0)

Log in as root / changeme123 and change the password with `passwd`.
No WiFi is configured on a fresh flash — the boot log printing
"Starting network: ... FAIL" is expected. Connect with:

    wifi connect "YOUR SSID" "YOUR PASSWORD"

Then telnet in from your LAN, or keep using the serial console.
EOF
