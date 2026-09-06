#!/bin/sh
set -e
case "${1:-}" in
    bash) test -x /bin/bash; target=/usr/bin/user-shell ;;
    sh) target=/bin/sh ;;
    *) echo 'Usage: set-user-shell bash|sh (root login only)' >&2; exit 2 ;;
esac
test "$(id -u)" = 0
test -x "$target"
mkdir /etc/.user-shell.lock
tmp=
trap 'test -z "$tmp" || rm -f "$tmp"; rmdir /etc/.user-shell.lock' EXIT
trap 'exit 1' HUP INT TERM
if [ ! -e /etc/passwd.before-user-shell ]; then
    cp -p /etc/passwd /etc/passwd.before-user-shell
fi
tmp=$(mktemp /etc/passwd.shell.XXXXXX)
cp -p /etc/passwd "$tmp"
awk -F: -v OFS=: -v shell="$target" '
    NF != 7 { bad=1 }
    $1 == "root" { roots++; $7=shell }
    { print }
    END { if (roots != 1 || bad) exit 1 }
' /etc/passwd > "$tmp"
mv "$tmp" /etc/passwd
tmp=
if ! grep -qxF "$target" /etc/shells; then printf '%s\n' "$target" >> /etc/shells; fi
echo "Root login: $target; /bin/sh and service scripts unchanged. Re-login to apply."
