#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
flags=(-std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined)
clang "${flags[@]}" -I common tests/test_terminal.c common/terminal.c -o "$tmp/terminal"
"$tmp/terminal"
clang "${flags[@]}" -DCONFIG_IDF_TARGET_ESP32S3=1 -I tests/stubs -I epdiy/src \
    tests/test_queue.c epdiy/src/output_common/line_queue.c -o "$tmp/queue"
"$tmp/queue"
clang -std=c11 -Wall -Wextra -Werror -Wno-deprecated-declarations -fsyntax-only linux/epd-shell.c

python3 tests/test_login_mirror.py
