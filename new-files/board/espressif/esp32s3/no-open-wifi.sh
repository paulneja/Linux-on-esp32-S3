#! /bin/sh
#
# Remove the default /etc/wpa_supplicant.conf that buildroot's wpa_supplicant
# package installs unconditionally (WPA_SUPPLICANT_INSTALL_TARGET_CMDS). Its
# contents are:
#
#     ap_scan=1
#     network={
#       key_mgmt=NONE
#     }
#
# A network block with no ssid and key_mgmt=NONE matches ANY open network, so a
# board flashed with it joins whatever unencrypted AP is in range, by itself,
# at boot. That is how a from-scratch build ended up associated with a carrier
# hotspot nobody had configured.
#
# The released images never had this file, but only by accident: it had been
# deleted by hand from an incremental target/ and buildroot does not reinstall
# it once the package is built, so nothing here reproduced its absence.
#
# Removing it is what the rest of the system expects. With no config,
# wpa_supplicant exits at boot (the "FAIL" after "Starting network") and the
# radio stays idle until someone chooses a network -- `wifi connect`, or the
# BLE dialog, both of which write this file themselves.

set -e

rm -f "$1/etc/wpa_supplicant.conf"

# The overlay's example must survive: it is what `wifi` copies from.
[ -f "$1/etc/wpa_supplicant.conf.example" ] || {
	echo "no-open-wifi.sh: /etc/wpa_supplicant.conf.example is missing" >&2
	exit 1
}
