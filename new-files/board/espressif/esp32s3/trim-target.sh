#! /bin/sh

set -e

rm -f "$1/usr/bin/luac"

if [ -f "$1/etc/init.d/S35iptables" ]; then
	mv -f "$1/etc/init.d/S35iptables" "$1/etc/init.d/iptables"
fi

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
fi
