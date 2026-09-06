#! /bin/sh

set -e

rm -f "$1/usr/bin/luac"

if [ -f "$1/etc/init.d/S35iptables" ]; then
	mv -f "$1/etc/init.d/S35iptables" "$1/etc/init.d/iptables"
fi
