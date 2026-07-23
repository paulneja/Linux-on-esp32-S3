#!/bin/bash
# Applies this project's local modifications (AP support, NAT/DNS, security
# hardening, espctl, 16MB board profile) on top of a freshly cloned upstream
# tree. Called automatically by rebuild-esp32s3-linux-wifi.sh right after
# each clone, before that source is built -- see the two call sites there.
#
# Why this exists: build/ (buildroot, esp-hosted, the kernel source) is
# fetched fresh from upstream on a clean checkout and is not itself part of
# this repo. Without this script, a clean checkout (including inside Docker)
# reproduces jcmvbkbc's original project, not this one -- the local patches
# were being applied by hand, once per session, and never wired into the
# automated flow, which is the gap this closes.
#
# The kernel driver patch (AP support in esp32-ng) is NOT applied here: it's
# wired directly into buildroot via BR2_LINUX_KERNEL_PATCH in
# configs/esp32s3_devkit_c1_16m_defconfig, so buildroot re-applies it after
# every kernel extraction automatically, including re-extractions triggered
# mid-session. That one file class kept getting silently reverted when it
# depended on "just don't touch this directory" instead.
#
# Usage: apply-local-changes.sh buildroot|esp-hosted
set -euo pipefail
cd "$(dirname "$0")"

# Find the checkout of this project (the one holding patches/ and new-files/).
# Do not hardcode its directory name: it depends on where the user cloned it.
#   1. $LOCAL_CHANGES, if the caller points us at it explicitly.
#   2. ./local-changes -- the Docker image copies patches/ and new-files/ there
#      at build time (see Dockerfile).
#   3. Otherwise look for a checkout next to, or one level above, this tree.
has_changes() { [ -d "$1/patches" ] && [ -d "$1/new-files" ]; }

LOCAL=""
if [ -n "${LOCAL_CHANGES:-}" ]; then
	has_changes "$LOCAL_CHANGES" || {
		echo "error: LOCAL_CHANGES=$LOCAL_CHANGES has no patches/ and new-files/" >&2
		exit 1
	}
	LOCAL="$(cd "$LOCAL_CHANGES" && pwd)"
elif has_changes local-changes; then
	LOCAL="$(cd local-changes && pwd)"
else
	for d in ../* ../../*; do
		if has_changes "$d"; then LOCAL="$(cd "$d" && pwd)"; break; fi
	done
fi

if [ -z "$LOCAL" ]; then
	cat >&2 <<-EOF
	error: cannot find this project's patches/ and new-files/.
	Clone https://github.com/paulneja/Linux-on-esp32-S3 next to this tree, or
	point us at an existing checkout:
	    LOCAL_CHANGES=/path/to/Linux-on-esp32-S3 $0 ${1:-buildroot}
	EOF
	exit 1
fi
echo ">>> using local changes from: $LOCAL"

case "${1:-}" in
buildroot)
	[ -d build/buildroot ] || { echo "error: build/buildroot missing -- clone it first" >&2; exit 1; }
	echo ">>> buildroot: applying tracked-file changes"
	cd build/buildroot
	# "already applied" and "does not apply" are NOT the same thing, and
	# treating them alike once cost a whole silent bad build: the patch
	# carried a binary file git apply cannot reconstruct, so it failed on
	# every fresh clone, got skipped as if it were already applied, and the
	# image shipped without /etc/fstab, inetd.conf, S05home or the libcurl
	# fix -- with the build reporting success. Tell them apart, and stop.
	if git apply --check "$LOCAL/patches/03-buildroot-tracked-changes.patch" 2>/dev/null; then
		git apply "$LOCAL/patches/03-buildroot-tracked-changes.patch"
	elif git apply --check --reverse "$LOCAL/patches/03-buildroot-tracked-changes.patch" 2>/dev/null; then
		echo "    already applied -- skipping"
	else
		echo "error: 03-buildroot-tracked-changes.patch does not apply and is" >&2
		echo "       not already applied. Building on would silently produce an" >&2
		echo "       incomplete image. Details:" >&2
		git apply --check "$LOCAL/patches/03-buildroot-tracked-changes.patch" >&2 || true
		exit 1
	fi
	cd ../..
	echo ">>> buildroot: copying new files (board profile, espctl, init scripts)"
	rsync -a "$LOCAL/new-files/board/" build/buildroot/board/
	rsync -a "$LOCAL/new-files/configs/" build/buildroot/configs/
	;;
esp-hosted)
	[ -d build/esp-hosted/esp_hosted_ng ] || { echo "error: build/esp-hosted/esp_hosted_ng missing -- clone it first" >&2; exit 1; }
	echo ">>> esp-hosted firmware: applying the firmware patch + committing locally"
	echo "    (esp_driver/CMakeLists.txt runs 'git reset --hard' on every cmake invocation;"
	echo "     a local commit is the only thing that survives that -- see DEVELOPMENT.md)"
	cd build/esp-hosted/esp_hosted_ng
	if git log --oneline -1 | grep -q "local-only, never push"; then
		echo "    already committed locally -- skipping"
	else
		git apply "$LOCAL/patches/02-firmware-network-adapter.patch"
		cp "$LOCAL/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r" \
			"$LOCAL/new-files/esp-hosted/network_adapter/sdkconfig.defaults.esp32s3.16m8r" \
			esp/esp_driver/network_adapter/
		# sdkconfig.defaults.esp32s3 (no .16m8r) is patched too and does not
		# live under main/, so it needs its own entry here or the commit
		# drops it and cmake's reset --hard then reverts it.
		git add esp/esp_driver/network_adapter/main/ \
			esp/esp_driver/network_adapter/sdkconfig.defaults.esp32s3 \
			esp/esp_driver/network_adapter/partition_table.esp32s3.16m8r \
			esp/esp_driver/network_adapter/sdkconfig.defaults.esp32s3.16m8r
		git -c user.email="local@backup" -c user.name="local-backup" \
			commit -m "network_adapter: this project's firmware (local-only, never push)"
	fi

	# The vendored ESP-IDF needs one symbol unhidden for the SoftAP path to
	# link. cmake initialises this submodule itself, but only later, so do it
	# here -- the same command it runs, so its run becomes a no-op.
	echo ">>> esp-hosted: patching the vendored ESP-IDF"
	IDF=esp/esp_driver/esp-idf
	if [ ! -e "$IDF/.git" ]; then
		echo "    fetching the esp-idf submodule"
		git submodule update --init --depth=1 "$IDF" >/dev/null
	fi
	if git -C "$IDF" apply --check "$LOCAL/patches/06-idf-hostap-sta-join.patch" 2>/dev/null; then
		git -C "$IDF" apply "$LOCAL/patches/06-idf-hostap-sta-join.patch"
		echo "    applied"
	elif git -C "$IDF" apply --check --reverse "$LOCAL/patches/06-idf-hostap-sta-join.patch" 2>/dev/null; then
		echo "    already applied -- skipping"
	else
		echo "error: 06-idf-hostap-sta-join.patch neither applies nor is applied." >&2
		exit 1
	fi
	;;
*)
	echo "usage: $0 buildroot|esp-hosted" >&2
	exit 1
	;;
esac
