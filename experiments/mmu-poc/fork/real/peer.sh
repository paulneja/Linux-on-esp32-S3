#!/usr/bin/dash
set -eu
case "$1" in
left) other=right ;;
right) other=left ;;
*) exit 2 ;;
esac
printf started > "$1.started"
i=0
while ! test -f "$other.started"; do
    i=$((i + 1))
    test "$i" -lt 30 || exit 3
    sleep 0.1
done
printf '%s\n' "$1" > "$1"
