#!/bin/bash
#
# Collect the binaries a build produced into images/, and merge them into the
# single flashable image published with the releases.
#
# The build driver (rebuild-esp32s3-linux-wifi.sh) compiles everything but
# stops there: it does not gather the results or package them. This closes that
# gap, so images/ can be regenerated from a build instead of by hand.
#
#   ./make-images.sh /path/to/esp32-linux-build
#   ./make-images.sh                 # tries ../esp32-linux-build, ./esp32-linux-build
#
# Produces, in images/:
#   bootloader.bin  partition-table.bin  network_adapter.bin
#   etc.jffs2  xipImage  rootfs.cramfs
#   linux-esp32s3-native-full.bin   <- the combined image for offset 0x0
#
# Requires esptool (pip install esptool) and python3.
#
set -euo pipefail

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$REPO/images"
PROFILE=esp32s3_devkit_c1_16m

die() { echo "error: $*" >&2; exit 1; }

# --- locate the build tree ----------------------------------------------
SRC="${1:-}"
if [ -z "$SRC" ]; then
	for d in ../esp32-linux-build ./esp32-linux-build; do
		[ -d "$d/build" ] && { SRC="$d"; break; }
	done
	[ -n "$SRC" ] || die "cannot find esp32-linux-build; pass it as an argument"
fi
SRC=$(CDPATH= cd -- "$SRC" && pwd)
BUILD="$SRC/build"
[ -d "$BUILD" ] || die "$BUILD does not exist -- has the build run?"

BR="$BUILD/build-buildroot-$PROFILE/images"
NA="$BUILD/esp-hosted/esp_hosted_ng/esp/esp_driver/network_adapter"

for f in "$BR/xipImage" "$BR/rootfs.cramfs" "$BR/etc.jffs2" \
         "$NA/build/network_adapter.bin" "$NA/build/bootloader/bootloader.bin"; do
	[ -f "$f" ] || die "missing build output: $f"
done

if command -v esptool.py >/dev/null 2>&1; then ESPTOOL="esptool.py"
elif command -v esptool >/dev/null 2>&1; then ESPTOOL="esptool"
elif python3 -c 'import esptool' >/dev/null 2>&1; then ESPTOOL="python3 -m esptool"
else die "esptool not found (pip install esptool)"; fi

mkdir -p "$OUT"

# --- partition table ----------------------------------------------------
# Generate it from the CSV, never from the firmware build: that build emits a
# partition-table.bin from an older CSV that puts rootfs at the wrong offset,
# and the kernel derives the rootfs XIP address from the partition table, so
# booting it panics with "Cannot open root device".
CSV="$REPO/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r"
GEN=$(find "$BUILD" -path '*partition_table/gen_esp32part.py' -print -quit 2>/dev/null) \
	|| die "gen_esp32part.py not found under $BUILD"
[ -n "$GEN" ] || die "gen_esp32part.py not found under $BUILD"
echo "==> partition table (from $(basename "$CSV"))"
python3 "$GEN" "$CSV" "$OUT/partition-table.bin" >/dev/null

# Read the offsets back out of the CSV so they cannot drift from this script.
eval "$(awk -F', *' '
	/^[a-z]/ {
		gsub(/[ \t]/, "", $1)
		if ($1 == "linux")  printf "OFF_LINUX=%s SIZE_LINUX=%s ",   $4, $5
		if ($1 == "rootfs") printf "OFF_ROOTFS=%s SIZE_ROOTFS=%s ", $4, $5
		if ($1 == "etc")    printf "OFF_ETC=%s SIZE_ETC=%s ",       $4, $5
		if ($1 == "factory")printf "OFF_APP=%s SIZE_APP=%s ",       $4, $5
	}' "$CSV")"

# --- collect ------------------------------------------------------------
echo "==> collecting build outputs"
cp -v "$NA/build/bootloader/bootloader.bin" "$OUT/bootloader.bin"
cp -v "$NA/build/network_adapter.bin"       "$OUT/network_adapter.bin"
cp -v "$BR/etc.jffs2"                        "$OUT/etc.jffs2"
cp -v "$BR/xipImage"                         "$OUT/xipImage"
cp -v "$BR/rootfs.cramfs"                    "$OUT/rootfs.cramfs"

# --- sanity: everything must fit its partition --------------------------
fits() { # file offset size name
	local sz; sz=$(stat -c%s "$1")
	if [ "$sz" -gt "$(($3))" ]; then
		die "$4 is $sz bytes, larger than its $(($3))-byte partition"
	fi
	printf '    %-20s %8d bytes  (partition %d, %d free)\n' \
		"$4" "$sz" "$(($3))" "$(( $3 - sz ))"
}
echo "==> checking sizes"
fits "$OUT/network_adapter.bin" "$OFF_APP"    "$SIZE_APP"    network_adapter.bin
fits "$OUT/etc.jffs2"           "$OFF_ETC"    "$SIZE_ETC"    etc.jffs2
fits "$OUT/xipImage"            "$OFF_LINUX"  "$SIZE_LINUX"  xipImage
fits "$OUT/rootfs.cramfs"       "$OFF_ROOTFS" "$SIZE_ROOTFS" rootfs.cramfs

# --- sanity: no real WiFi credentials -----------------------------------
# buildroot's target/ is incremental: a stale target/etc/wpa_supplicant.conf
# from a manual test once got baked into etc.jffs2 and shipped. The overlay
# only carries wpa_supplicant.conf.example, so a clean image has no PSK line.
echo "==> checking for baked-in WiFi credentials"
if strings "$OUT/etc.jffs2" | grep -qE '^[[:space:]]*psk="'; then
	echo "  !! etc.jffs2 contains a psk= line." >&2
	echo "  !! Delete build-buildroot-$PROFILE/target/etc/wpa_supplicant.conf" >&2
	echo "  !! and rebuild: WiFi is meant to be set at runtime with 'wifi connect'." >&2
	die "refusing to package an image with credentials in it"
fi
# The opposite failure, and the one that actually shipped: buildroot's
# wpa_supplicant package installs its own /etc/wpa_supplicant.conf holding a
# network block with no ssid and key_mgmt=NONE. That matches any open network,
# so the board joins whatever unencrypted AP is in range on its own. It has no
# psk line, so the check above waves it through. no-open-wifi.sh removes it at
# post-build; this is the backstop for when that does not run.
if strings "$OUT/etc.jffs2" | grep -qE '^[[:space:]]*key_mgmt=NONE'; then
	echo "  !! etc.jffs2 has a key_mgmt=NONE network block -- this image would" >&2
	echo "  !! join any open WiFi by itself. no-open-wifi.sh should have removed" >&2
	echo "  !! /etc/wpa_supplicant.conf; check BR2_ROOTFS_POST_BUILD_SCRIPT." >&2
	die "refusing to package an image that auto-joins open networks"
fi
echo "    clean"

# --- sanity: Linux's exception vectors must land in the firmware's hole ---
# The firmware reserves 4K of IRAM for Linux's exception vectors:
#
#   static char IRAM_ATTR space_for_vectors[4096];   (main/linux_boot.c)
#
# The linker picks that address, so it MOVES whenever the firmware's size or
# layout changes. The kernel has it hard-coded in CONFIG_VECTORS_ADDR. If the
# two drift apart, Linux writes its vectors over firmware memory and dies the
# instant it executes userspace -- no panic, no console output, the boot just
# stops dead at "Run /sbin/init". Adding the BLE stack grew the firmware by
# ~117K and moved it from 0x4037c000 to 0x4037f000, which is exactly how this
# was found, after a long hunt. Never ship that silently again: check it here.
echo "==> checking Linux vector address against the firmware"
KCONF="$REPO/new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config"
FW_ELF="$NA/build/network_adapter.elf"
NM=$(command -v xtensa-esp32s3-elf-nm 2>/dev/null || \
     ls /home/*/.espressif/tools/xtensa-esp32s3-elf/*/xtensa-esp32s3-elf/bin/xtensa-esp32s3-elf-nm 2>/dev/null | head -1)

if [ -z "$NM" ] || [ ! -f "$FW_ELF" ]; then
	echo "  !! cannot verify (no xtensa nm, or firmware ELF missing)." >&2
	echo "  !! Check by hand that space_for_vectors in $FW_ELF" >&2
	echo "  !! equals CONFIG_VECTORS_ADDR in $KCONF" >&2
else
	FW_VEC=$("$NM" "$FW_ELF" | awk '/ space_for_vectors$/ {print $1}' | head -1)
	K_VEC=$(sed -n 's/^CONFIG_VECTORS_ADDR=0x\([0-9a-fA-F]*\).*/\1/p' "$KCONF" | head -1)
	# normalise: nm prints lowercase hex without 0x, kconfig may use either case
	FW_VEC=$(printf '%s' "$FW_VEC" | tr 'A-F' 'a-f')
	K_VEC=$(printf '%s' "$K_VEC" | tr 'A-F' 'a-f' | sed 's/^0*//')
	FW_CMP=$(printf '%s' "$FW_VEC" | sed 's/^0*//')

	if [ -z "$FW_VEC" ] || [ -z "$K_VEC" ]; then
		echo "  !! could not read one of the addresses -- verify by hand." >&2
	elif [ "$FW_CMP" != "$K_VEC" ]; then
		# Realign and rebuild rather than making the user do it: the
		# address moving is normal (any firmware change can do it), and
		# the remedy is always the same single line.
		echo "    address moved: firmware 0x$FW_VEC, kernel 0x$K_VEC"
		echo "==> realigning the kernel and rebuilding it"

		sed -i "s/^CONFIG_VECTORS_ADDR=.*/CONFIG_VECTORS_ADDR=0x$FW_VEC/" "$KCONF" \
			|| die "could not update $KCONF"
		KDOTCONF="$BUILD/build-buildroot-$PROFILE/build/linux-xtensa-6.11-esp32-tag/.config"
		[ -f "$KDOTCONF" ] && \
			sed -i "s/^CONFIG_VECTORS_ADDR=.*/CONFIG_VECTORS_ADDR=0x$FW_VEC/" "$KDOTCONF"

		# Same environment the build driver uses for the kernel.
		: "${GCC14_SHIM:=$HOME/esp/gcc14shim}"
		[ -d "$GCC14_SHIM" ] && PATH="$GCC14_SHIM:$PATH"
		[ -d "$SRC/autoconf-2.71/root/bin" ] && PATH="$SRC/autoconf-2.71/root/bin:$PATH"
		export PATH
		export XTENSA_GNU_CONFIG="$BUILD/xtensa-dynconfig/esp32s3.so"

		make -C "$BUILD/buildroot" O="$BUILD/build-buildroot-$PROFILE" \
			linux-rebuild >/dev/null 2>&1 \
			|| die "kernel rebuild failed -- rerun the build by hand"

		cp -f "$BR/xipImage" "$OUT/xipImage" || die "no xipImage after rebuild"
		fits "$OUT/xipImage" "$OFF_LINUX" "$SIZE_LINUX" xipImage

		# Trust nothing: confirm the rebuilt kernel really agrees now.
		K_VEC=$(sed -n 's/^CONFIG_VECTORS_ADDR=0x\([0-9a-fA-F]*\).*/\1/p' "$KCONF" | head -1)
		K_VEC=$(printf '%s' "$K_VEC" | tr 'A-F' 'a-f' | sed 's/^0*//')
		[ "$FW_CMP" = "$K_VEC" ] || die "still mismatched after rebuild"
		echo "    realigned to 0x$FW_VEC and kernel rebuilt"
	else
		echo "    vectors at 0x$FW_VEC, kernel agrees"
	fi
fi

# --- merge --------------------------------------------------------------
echo "==> merging into linux-esp32s3-native-full.bin"
# shellcheck disable=SC2086
$ESPTOOL --chip esp32s3 merge_bin -o "$OUT/linux-esp32s3-native-full.bin" \
	--flash_mode dio --flash_freq 80m --flash_size 16MB \
	--fill-flash-size 16MB \
	0x0            "$OUT/bootloader.bin" \
	0x8000         "$OUT/partition-table.bin" \
	"$OFF_APP"     "$OUT/network_adapter.bin" \
	"$OFF_ETC"     "$OUT/etc.jffs2" \
	"$OFF_LINUX"   "$OUT/xipImage" \
	"$OFF_ROOTFS"  "$OUT/rootfs.cramfs" >/dev/null

echo
echo "Done. images/ now holds:"
ls -1sh "$OUT" | sed 's/^/    /'
echo
echo "sha256  $(sha256sum "$OUT/linux-esp32s3-native-full.bin" | cut -d' ' -f1)"
echo "Flash it with:  ./flash.sh --erase"
