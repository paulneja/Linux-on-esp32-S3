#!/bin/bash
set -euo pipefail

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$REPO/images"
PROFILE=esp32s3_devkit_c1_16m

die() { echo "error: $*" >&2; exit 1; }

SRC="${1:-}"
if [ -z "$SRC" ]; then
	for d in ../esp32-linux-build ./esp32-linux-build ./build-output; do
		if [ -d "$d/build" ] || [ -d "$d/buildroot" ]; then
			SRC="$d"
			break
		fi
	done
	[ -n "$SRC" ] || die "cannot find a build tree; pass esp32-linux-build/ or build-output/ as an argument"
fi
[ -d "$SRC" ] || die "$SRC does not exist"
SRC=$(CDPATH= cd -- "$SRC" && pwd -P)
if [ -d "$SRC/build" ]; then
	BUILD="$SRC/build"
elif [ -d "$SRC/buildroot" ] && [ -d "$SRC/esp-hosted" ]; then
	BUILD="$SRC"
else
	die "$SRC is neither an esp32-linux-build tree (no build/ in it) nor a build directory (no buildroot/ and esp-hosted/ in it) -- has the build run?"
fi

BR="$BUILD/build-buildroot-$PROFILE/images"
HOST="$BUILD/build-buildroot-$PROFILE/host"
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

CSV="$REPO/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r"
GEN=$(find "$BUILD/" -path '*partition_table/gen_esp32part.py' -print -quit 2>/dev/null) \
	|| die "gen_esp32part.py not found under $BUILD"
[ -n "$GEN" ] || die "gen_esp32part.py not found under $BUILD"
echo "==> partition table (from $(basename "$CSV"))"
python3 "$GEN" "$CSV" "$OUT/partition-table.bin" >/dev/null

eval "$(awk -F', *' '
	/^[a-z]/ {
		gsub(/[ \t]/, "", $1)
		if ($1 == "linux")  printf "OFF_LINUX=%s SIZE_LINUX=%s ",   $4, $5
		if ($1 == "rootfs") printf "OFF_ROOTFS=%s SIZE_ROOTFS=%s ", $4, $5
		if ($1 == "etc")    printf "OFF_ETC=%s SIZE_ETC=%s ",       $4, $5
		if ($1 == "factory")printf "OFF_APP=%s SIZE_APP=%s ",       $4, $5
		if ($1 == "home")   printf "OFF_HOME=%s SIZE_HOME=%s ",     $4, $5
	}' "$CSV")"

echo "==> collecting build outputs"
cp -v "$NA/build/bootloader/bootloader.bin" "$OUT/bootloader.bin"
cp -v "$NA/build/network_adapter.bin"       "$OUT/network_adapter.bin"
cp -v "$BR/etc.jffs2"                        "$OUT/etc.jffs2"
cp -v "$BR/xipImage"                         "$OUT/xipImage"
cp -v "$BR/rootfs.cramfs"                    "$OUT/rootfs.cramfs"

MKFS=""
if [ -f "$HOST/sbin/mkfs.jffs2" ]; then
	[ -x "$HOST/sbin/mkfs.jffs2" ] || chmod +x "$HOST/sbin/mkfs.jffs2" 2>/dev/null || true
	[ -x "$HOST/sbin/mkfs.jffs2" ] && MKFS="$HOST/sbin/mkfs.jffs2"
fi
if [ -z "$MKFS" ] && command -v mkfs.jffs2 >/dev/null 2>&1; then
	MKFS=$(command -v mkfs.jffs2)
fi

if [ -n "$MKFS" ]; then
	echo "==> building the factory /home"
	EMPTY_HOME=$(mktemp -d)
	trap 'rm -rf -- "$EMPTY_HOME"' EXIT
	chmod 755 "$EMPTY_HOME"
	"$MKFS" -l -e 65536 -U -f --pad=$(($SIZE_HOME)) \
		-d "$EMPTY_HOME" -o "$OUT/home.jffs2"
else
	echo "==> no usable mkfs.jffs2; leaving the home partition erased"
	echo "    (build trees copied through CI artifacts lose the executable bit;"
	echo "     the board formats an erased home on its first write)"
	rm -f "$OUT/home.jffs2"
fi

fits() {
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
if [ -n "$MKFS" ]; then
	fits "$OUT/home.jffs2"  "$OFF_HOME"   "$SIZE_HOME"   home.jffs2
fi

echo "==> checking for baked-in WiFi credentials"
ETC_TEXT=$(strings "$OUT/etc.jffs2")
if grep -qE '^[[:space:]]*psk="' <<<"$ETC_TEXT"; then
	echo "  !! etc.jffs2 contains a psk= line." >&2
	echo "  !! Delete build-buildroot-$PROFILE/target/etc/wpa_supplicant.conf" >&2
	echo "  !! and rebuild: WiFi is meant to be set at runtime with 'wifi connect'." >&2
	die "refusing to package an image with credentials in it"
fi
if grep -qE '^[[:space:]]*key_mgmt=NONE' <<<"$ETC_TEXT"; then
	echo "  !! etc.jffs2 has a key_mgmt=NONE network block -- this image would" >&2
	echo "  !! join any open WiFi by itself. no-open-wifi.sh should have removed" >&2
	echo "  !! /etc/wpa_supplicant.conf; check BR2_ROOTFS_POST_BUILD_SCRIPT." >&2
	die "refusing to package an image that auto-joins open networks"
fi
echo "    clean"

echo "==> checking Linux vector address against the firmware"
KCONF="$REPO/new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config"
FW_ELF="$NA/build/network_adapter.elf"

elf_symbol_addr() {
	python3 -c '
import struct, sys
b = open(sys.argv[1], "rb").read()
shoff, = struct.unpack_from("<I", b, 0x20)
shentsize, shnum = struct.unpack_from("<HH", b, 0x2e)
secs = [struct.unpack_from("<10I", b, shoff + i * shentsize) for i in range(shnum)]
for _, typ, _, _, off, size, link, _, _, entsize in secs:
    if typ != 2 or not entsize:      # SHT_SYMTAB
        continue
    strs = b[secs[link][4]:secs[link][4] + secs[link][5]]
    for s in range(off, off + size, entsize):
        nameoff, value = struct.unpack_from("<II", b, s)
        if strs[nameoff:strs.index(b"\0", nameoff)] == sys.argv[2].encode():
            print("%08x" % value)
            sys.exit(0)
' "$1" "$2" 2>/dev/null || true
}

if [ ! -f "$FW_ELF" ]; then
	echo "  !! cannot verify: firmware ELF missing ($FW_ELF)." >&2
	echo "  !! Check by hand that space_for_vectors there" >&2
	echo "  !! equals CONFIG_VECTORS_ADDR in $KCONF" >&2
else
	FW_VEC=$(elf_symbol_addr "$FW_ELF" space_for_vectors)
	K_VEC=$(sed -n 's/^CONFIG_VECTORS_ADDR=0x\([0-9a-fA-F]*\).*/\1/p' "$KCONF" | head -1)
	FW_VEC=$(printf '%s' "$FW_VEC" | tr 'A-F' 'a-f')
	K_VEC=$(printf '%s' "$K_VEC" | tr 'A-F' 'a-f' | sed 's/^0*//')
	FW_CMP=$(printf '%s' "$FW_VEC" | sed 's/^0*//')

	if [ -z "$FW_VEC" ] || [ -z "$K_VEC" ]; then
		echo "  !! could not read one of the addresses -- verify by hand." >&2
	elif [ "$FW_CMP" != "$K_VEC" ]; then
		echo "    address moved: firmware 0x$FW_VEC, kernel 0x$K_VEC"
		echo "==> realigning the kernel and rebuilding it"

		sed -i "s/^CONFIG_VECTORS_ADDR=.*/CONFIG_VECTORS_ADDR=0x$FW_VEC/" "$KCONF" \
			|| die "could not update $KCONF"
		KDOTCONF="$BUILD/build-buildroot-$PROFILE/build/linux-xtensa-6.11-esp32-tag/.config"
		[ -f "$KDOTCONF" ] && \
			sed -i "s/^CONFIG_VECTORS_ADDR=.*/CONFIG_VECTORS_ADDR=0x$FW_VEC/" "$KDOTCONF"

		if [ ! -f "$BUILD/xtensa-dynconfig/esp32s3.so" ]; then
			die "the vector address moved, so the kernel has to be rebuilt,
       but there is no xtensa toolchain here:
       $BUILD/xtensa-dynconfig/esp32s3.so is missing.
       Run the full build instead of repackaging an existing tree."
		fi

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

		K_VEC=$(sed -n 's/^CONFIG_VECTORS_ADDR=0x\([0-9a-fA-F]*\).*/\1/p' "$KCONF" | head -1)
		K_VEC=$(printf '%s' "$K_VEC" | tr 'A-F' 'a-f' | sed 's/^0*//')
		[ "$FW_CMP" = "$K_VEC" ] || die "still mismatched after rebuild"
		echo "    realigned to 0x$FW_VEC and kernel rebuilt"
	else
		echo "    vectors at 0x$FW_VEC, kernel agrees"
	fi
fi

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
	"$OFF_ROOTFS"  "$OUT/rootfs.cramfs" \
	${MKFS:+"$OFF_HOME" "$OUT/home.jffs2"} >/dev/null

echo
echo "Done. images/ now holds:"
ls -1sh "$OUT" | sed 's/^/    /'
echo
echo "sha256  $(sha256sum "$OUT/linux-esp32s3-native-full.bin" | cut -d' ' -f1)"
echo "Flash it with:  ./flash.sh --erase"
