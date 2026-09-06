#!/bin/sh
# Post-build hook: defaults seed writable /home on first boot, not /www.
set -e
test "$#" = 1
target=$1
test "$target" != /
test -f "$target/bin/busybox"
board=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d "$target/usr/share/esp32-home"
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -czf "$target/usr/share/esp32-home/www.tar.gz" -C "$board/home-defaults" www
install -m 644 "$board/home-defaults/README.txt" "$target/usr/share/esp32-home/README.txt"
install -m 755 "$board/rootfs_overlay/etc/init.d/S06home-users" "$target/usr/share/esp32-home/S06home-users"
install -m 644 "$board/rootfs_overlay/etc/skel/.profile" "$target/usr/share/esp32-home/user.profile"
install -d "$target/usr/share/esp32-cron"
install -m 755 "$board/rootfs_overlay/etc/init.d/S50crond" "$target/usr/share/esp32-cron/S50crond"
# Target was validated above; only the old, explicitly retired document root.
if [ -e "$target/www" ] || [ -L "$target/www" ]; then rm -r -- "$target/www"; fi
