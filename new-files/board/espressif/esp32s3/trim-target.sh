#! /bin/sh
# Copyright (c) 2026 Paulneja. GPLv3, see LICENSE. https://github.com/paulneja/Linux-on-esp32-S3

set -e

# Nothing NEEDs these: readelf -d over every ELF in the image lists
# libncurses for nano and bash, and libnl-3 and libnl-genl-3 for iw and
# wpa_supplicant, and none of them names these four. buildroot's own
# trim-libs.sh already does the same for libnl-nf, libnl-route and libnl-xfrm.
rm -f "$1/usr/lib/"libform* "$1/usr/lib/"libmenu* "$1/usr/lib/"libpanel*
rm -f "$1/usr/lib/"libnl-idiag*

# Buildroot's esp32s3 board directory carries four dropbear private host keys
# and they are tracked in a public repository, so every board built from it
# would answer SSH with the same key -- and ship it world readable. inetd runs
# dropbear with -R, which generates a key per board into the writable /etc on
# the first connection, so the baked-in ones are only harmful.
rm -f "$1/etc/dropbear/"*_host_key

# /var/log is a symlink into the 1777 /tmp in buildroot's skeleton, so syslogd
# writes authentication records where any local user can read them. /run is
# 0755 and is mounted before syslogd starts.
if [ -L "$1/var/log" ]; then
	rm -f "$1/var/log"
	ln -s ../run/log "$1/var/log"
fi

# swapon/swapoff cannot work: CONFIG_SWAP depends on an MMU and this kernel is
# NOMMU, so both inittab lines are a guaranteed failing fork+exec per boot.
if [ -f "$1/etc/inittab" ]; then
	sed -i '/^::sysinit:\/sbin\/swapon /d; /^::shutdown:\/sbin\/swapoff /d' \
		"$1/etc/inittab"

	grep -q '^ttyGS3::' "$1/etc/inittab" ||
		sed -i '/^console::respawn:/a\
ttyGS3::respawn:/sbin/getty -L ttyGS3 0 vt100' \
			"$1/etc/inittab"
fi
