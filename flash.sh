#!/bin/sh
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMG="$DIR/images"
PORT=""
ERASE=0
PARTS=0

usage() {
	cat <<'EOF'
Usage: ./flash.sh [-p PORT] [--images DIR] [--parts] [--erase]

Requires Python 3 and esptool. Images come from images/ beside this script
unless --images points somewhere else, such as a build-output artifacts
directory.
  -p, --port PORT  Serial/COM adapter (otherwise autodetected)
  --images DIR     Read the images from DIR instead of images/
  --parts          Write separate images; preserve /home unless --erase is used
  --erase          Erase the entire chip before writing; destroys all board data
  -h, --help       Show this help

The default full-image write overwrites /etc and /home even without --erase.
--parts also overwrites /etc, including accounts and network configuration.
--parts --erase writes home.jffs2 when the directory has one; without it the
partition is left erased, which the board formats on its first write.
All inputs are checked before device access.
EOF
	exit "${1:-0}"
}

while [ $# -gt 0 ]; do
	case "$1" in
	-p|--port) PORT="${2:?-p needs a port}"; shift 2 ;;
	--images)  IMG="${2:?--images needs a directory}"; shift 2 ;;
	--erase)   ERASE=1; shift ;;
	--parts)   PARTS=1; shift ;;
	-h|--help) usage 0 ;;
	*) echo "unknown option: $1" >&2; usage 1 >&2 ;;
	esac
done

command -v python3 >/dev/null 2>&1 || { echo "error: Python 3 is required" >&2; exit 1; }
CSV="$DIR/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r"
OFFSETS=$(python3 - "$IMG" "$CSV" "$PARTS" "$ERASE" <<'PY'
import csv
from pathlib import Path
import struct
import sys

image_dir, table = map(Path, sys.argv[1:3])
parts_mode, erase = sys.argv[3:5]
flash_size = 16 * 1024 * 1024

def check_image(name, limit, exact=False):
    path = image_dir / name
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
    if size <= 0 or size > limit or (exact and size != limit):
        raise ValueError(f'{path}: invalid size {size}; expected '
                         + (str(limit) if exact else f'1..{limit}') + ' bytes')
    return path

try:
    if parts_mode == '0':
        check_image('linux-esp32s3-native-full.bin', flash_size, exact=True)
    else:
        parts = {}
        with table.open() as stream:
            for row in csv.reader(stream):
                if not row or not row[0].strip() or row[0].lstrip().startswith('#'):
                    continue
                name = row[0].strip()
                if len(row) < 5 or name in parts:
                    raise ValueError(f'{table}: malformed or duplicate partition {name}')
                offset, size = (int(field.strip(), 0) for field in row[3:5])
                if offset < 0x9000 or size <= 0 or (offset | size) % 4096:
                    raise ValueError(f'{name}: invalid partition offset or size')
                if offset + size > flash_size:
                    raise ValueError(f'{name}: partition exceeds 16 MiB flash')
                parts[name] = (offset, size)
        end = 0x9000
        for name, (offset, size) in sorted(parts.items(), key=lambda item: item[1][0]):
            if offset < end:
                raise ValueError(f'{name}: overlapping partitions')
            end = offset + size
        required = ('factory', 'etc', 'linux', 'rootfs', 'home')
        for name in required:
            if name not in parts:
                raise ValueError(f'{table}: missing {name} partition')
        check_image('bootloader.bin', 0x8000)
        binary = check_image('partition-table.bin', 0x1000).read_bytes()
        installed = {}
        for pos in range(0, len(binary) - 31, 32):
            magic, _, _, offset, size, label, _ = struct.unpack_from('<HBBII16sI', binary, pos)
            if magic != 0x50AA:
                break
            name = label.split(b'\0', 1)[0].decode('ascii')
            if name in installed:
                raise ValueError(f'partition-table.bin: duplicate partition {name}')
            installed[name] = (offset, size)
        if installed != parts:
            raise ValueError('partition-table.bin does not match CSV partition names/offsets/sizes')
        for name, filename in zip(required, ('network_adapter.bin', 'etc.jffs2',
                                             'xipImage', 'rootfs.cramfs', 'home.jffs2')):
            if name != 'home':
                check_image(filename, parts[name][1])
            elif erase == '1' and (image_dir / filename).exists():
                check_image(filename, parts[name][1], exact=True)
        print(' '.join(str(parts[name][0]) for name in required))
except (OSError, ValueError, struct.error) as error:
    sys.exit(f'error: preflight failed: {error}; no board data was changed')
PY
)

if [ "$PARTS" = 1 ]; then
	# shellcheck disable=SC2086
	set -- $OFFSETS
	OFF_APP=$1; OFF_ETC=$2; OFF_LINUX=$3; OFF_ROOTFS=$4; OFF_HOME=$5
	set -- 0x0 "$IMG/bootloader.bin" 0x8000 "$IMG/partition-table.bin" \
		"$OFF_APP" "$IMG/network_adapter.bin" "$OFF_ETC" "$IMG/etc.jffs2" \
		"$OFF_LINUX" "$IMG/xipImage" "$OFF_ROOTFS" "$IMG/rootfs.cramfs"
	if [ "$ERASE" = 1 ]; then
		if [ -f "$IMG/home.jffs2" ]; then
			set -- "$@" "$OFF_HOME" "$IMG/home.jffs2"
		else
			echo "Note: no home.jffs2 here; /home is left erased and formatted on first write."
		fi
		echo "Warning: --parts --erase resets /etc and /home; all board data will be lost."
	else
		echo "Warning: --parts preserves /home but overwrites /etc (accounts and configuration)."
	fi
else
	set -- 0x0 "$IMG/linux-esp32s3-native-full.bin"
	echo "Warning: the full image overwrites /etc and /home, even without --erase."
fi

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

if [ "$ERASE" = 1 ]; then
	echo "==> Erasing the whole chip (this wipes /home too)"
	# shellcheck disable=SC2086
	$ESPTOOL --chip esp32s3 -p "$PORT" -b 460800 erase_flash
fi

echo "==> Flashing validated images"
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 -p "$PORT" -b 460800 --before default_reset --after hard_reset \
	write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m "$@"

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
