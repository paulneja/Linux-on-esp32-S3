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
