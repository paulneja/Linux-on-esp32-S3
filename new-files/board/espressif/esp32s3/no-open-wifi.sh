#! /bin/sh

set -e

rm -f "$1/etc/wpa_supplicant.conf"

[ -f "$1/etc/wpa_supplicant.conf.example" ] || {
	echo "no-open-wifi.sh: /etc/wpa_supplicant.conf.example is missing" >&2
	exit 1
}
