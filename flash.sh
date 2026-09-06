#!/bin/sh
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
	CSV="$DIR/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r"
	if [ ! -f "$CSV" ]; then
		echo "error: partition table not found at $CSV" >&2
		echo "       --parts needs the full repository. If you only have" >&2
		echo "       images/, flash the combined image instead: $0" >&2
		exit 1
	fi

	OFF_APP=""; OFF_ETC=""; OFF_LINUX=""; OFF_ROOTFS=""; OFF_HOME=""
	eval "$(awk -F', *' '
		/^[a-z]/ {
			gsub(/[ \t]/, "", $1); gsub(/[ \t]/, "", $4)
			if ($1 == "factory") printf "OFF_APP=%s ",    $4
			if ($1 == "etc")     printf "OFF_ETC=%s ",    $4
			if ($1 == "linux")   printf "OFF_LINUX=%s ",  $4
			if ($1 == "rootfs")  printf "OFF_ROOTFS=%s ", $4
			if ($1 == "home")    printf "OFF_HOME=%s ",   $4
		}' "$CSV")"
	if [ -z "$OFF_APP" ] || [ -z "$OFF_ETC" ] || \
	   [ -z "$OFF_LINUX" ] || [ -z "$OFF_ROOTFS" ]; then
		echo "error: could not read the factory/etc/linux/rootfs offsets" >&2
		echo "       from $CSV" >&2
		exit 1
	fi

	HOME_ARGS=""
	if [ "$ERASE" = 1 ]; then
		if [ -z "$OFF_HOME" ]; then
			echo "error: could not read the home offset from $CSV" >&2
			exit 1
		fi
		if [ ! -f "$IMG/home.jffs2" ]; then
			echo "error: $IMG/home.jffs2 is missing; --erase leaves /home" >&2
			echo "       unformatted and the first boot hangs on its first" >&2
			echo "       write. Run ./make-images.sh to produce it." >&2
			exit 1
		fi
		HOME_ARGS="$OFF_HOME $IMG/home.jffs2"
	fi

	echo "==> Flashing the images separately"
	printf '    offsets from %s:\n' "$(basename "$CSV")"
	printf '    firmware %s   etc %s   kernel %s   rootfs %s\n' \
		"$OFF_APP" "$OFF_ETC" "$OFF_LINUX" "$OFF_ROOTFS"
	if [ -n "$HOME_ARGS" ]; then
		printf '    factory home %s\n' "$OFF_HOME"
	fi
	# shellcheck disable=SC2086
	$ESPTOOL $COMMON write_flash $FLASHOPTS \
		0x0          "$IMG/bootloader.bin" \
		0x8000       "$IMG/partition-table.bin" \
		"$OFF_APP"    "$IMG/network_adapter.bin" \
		"$OFF_ETC"    "$IMG/etc.jffs2" \
		"$OFF_LINUX"  "$IMG/xipImage" \
		"$OFF_ROOTFS" "$IMG/rootfs.cramfs" \
		$HOME_ARGS
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
No WiFi is configured on a fresh flash. The boot prints "Starting network
(background): OK" either way — it comes up behind the login prompt, and what
it actually did is in /var/log/network.log. Connect with:

    wifi connect "YOUR SSID" "YOUR PASSWORD"

Then telnet in from your LAN, or keep using the serial console.
EOF
