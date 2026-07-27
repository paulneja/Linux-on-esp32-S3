#! /bin/sh
#
# Post-build size trims for things buildroot installs that this board does not
# need at runtime. Kept separate from the upstream trim-libs.sh so it stays
# with this project and is easy to extend.

set -e

# luac is the Lua *compiler*. The board only runs Lua scripts (the httpd status
# CGI), which the interpreter handles; compiling .lua sources is a host-side
# job, never done on the board. The interpreter and liblua stay -- only the
# ~224K compiler goes.
rm -f "$1/usr/bin/luac"

# Take iptables out of the boot sequence without uninstalling it. rcS runs
# /etc/init.d/S??*, so dropping the S35 prefix is enough: the script stays and
# can still be started by hand with `/etc/init.d/iptables start`.
#
# It has nothing to do at boot -- there are no saved rules to restore since the
# SoftAP's NAT was removed -- and starting it anyway costs ~0.6 s of every boot
# on this target, where each process spawn is expensive.
if [ -f "$1/etc/init.d/S35iptables" ]; then
	mv -f "$1/etc/init.d/S35iptables" "$1/etc/init.d/iptables"
fi
