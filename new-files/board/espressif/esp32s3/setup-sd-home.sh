#!/bin/sh

set -e

test "$#" = 1
target=$1

test "$target" != /
test -f "$target/etc/fstab"

# SD card partition 1 is used as writable /home.
sed -i \
    's|^mtd:home[[:space:]].*|/dev/mmcblk0p1 /home ext2 nofail 0 0|' \
    "$target/etc/fstab"

# home-init originally accepts only JFFS2.
# Accept either JFFS2 or ext2 as a writable /home.
sed -i \
    's/\$3 == "jffs2"/(\$3 == "jffs2" || \$3 == "ext2")/' \
    "$target/usr/sbin/home-init"
