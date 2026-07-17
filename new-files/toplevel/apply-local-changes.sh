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

# Host dev tree: native-s3/ is a sibling of this repo's parent directory.
# Docker image: native-s3/patches and native-s3/new-files are copied in at
# build time under ./local-changes instead (see Dockerfile).
if [ -d ../../native-s3 ]; then
	LOCAL="$(cd ../../native-s3 && pwd)"
elif [ -d local-changes ]; then
	LOCAL="$(cd local-changes && pwd)"
else
	echo "error: neither ../../native-s3 nor ./local-changes found -- need patches/ and new-files/" >&2
	exit 1
fi

case "${1:-}" in
buildroot)
	[ -d build/buildroot ] || { echo "error: build/buildroot missing -- clone it first" >&2; exit 1; }
	echo ">>> buildroot: applying tracked-file changes"
	cd build/buildroot
	if git apply --check "$LOCAL/patches/03-buildroot-tracked-changes.patch" 2>/dev/null; then
		git apply "$LOCAL/patches/03-buildroot-tracked-changes.patch"
	else
		echo "    (already applied or diverged -- skipping, verify manually if unexpected)"
	fi
	cd ../..
	echo ">>> buildroot: copying new files (board profile, espctl, init scripts)"
	rsync -a "$LOCAL/new-files/board/" build/buildroot/board/
	rsync -a "$LOCAL/new-files/configs/" build/buildroot/configs/
	;;
esp-hosted)
	[ -d build/esp-hosted/esp_hosted_ng ] || { echo "error: build/esp-hosted/esp_hosted_ng missing -- clone it first" >&2; exit 1; }
	echo ">>> esp-hosted firmware: applying AP-support patch + committing locally"
	echo "    (esp_driver/CMakeLists.txt runs 'git reset --hard' on every cmake invocation;"
	echo "     a local commit is the only thing that survives that -- see PLAN.md)"
	cd build/esp-hosted/esp_hosted_ng
	if git log --oneline -1 | grep -q "local-only, never push"; then
		echo "    already committed locally -- skipping"
	else
		git apply "$LOCAL/patches/02-firmware-network-adapter-ap-support.patch"
		cp "$LOCAL/new-files/esp-hosted/network_adapter/partition_table.esp32s3.16m8r" \
			"$LOCAL/new-files/esp-hosted/network_adapter/sdkconfig.defaults.esp32s3.16m8r" \
			esp/esp_driver/network_adapter/
		git add esp/esp_driver/network_adapter/main/ \
			esp/esp_driver/network_adapter/partition_table.esp32s3.16m8r \
			esp/esp_driver/network_adapter/sdkconfig.defaults.esp32s3.16m8r
		git -c user.email="local@backup" -c user.name="local-backup" \
			commit -m "AP support + 16m8r profile files (local-only, never push)"
	fi
	;;
*)
	echo "usage: $0 buildroot|esp-hosted" >&2
	exit 1
	;;
esac
