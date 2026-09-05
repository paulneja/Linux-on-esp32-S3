#!/usr/bin/dash
set -eu
work=$(mktemp -d /tmp/hush-login.XXXXXX)
trap 'rm -f "$work/.profile" "$work/profile-count"; rmdir "$work"' EXIT
printf '%s\n' 'echo once >> "$HOME/profile-count"' 'p=$(printf profile-substitution); test "$p" = profile-substitution || exit 80' > "$work/.profile"
HOME="$work" /bin/bash --noprofile --norc -c 'exec -a -sh /bin/busybox -c '\''
    test "$0" = -sh || exit 81
    test "$(printf "%s" "$0")" = -sh || exit 82
    i=0
    while [ "$i" -lt 20 ]; do
        v=$(printf "%s" "$(printf nested-ok)")
        test "$v" = nested-ok || exit 83
        i=$((i+1))
    done
    read v <<EOF
heredoc-ok
EOF
    test "$v" = heredoc-ok || exit 84
    test "$(id -u)" = 0 || exit 85
'\'''
test "$(wc -l < "$work/profile-count")" -eq 1
echo 'PASS: hush -sh login sourced profile once; nested substitutions preserve $0; heredoc and id'
