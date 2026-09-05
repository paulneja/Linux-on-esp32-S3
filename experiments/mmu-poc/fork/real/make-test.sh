#!/usr/bin/dash
set -eu
task_dir=$(mktemp -d /tmp/mmu-make.XXXXXX)
cd "$task_dir"
cp /usr/share/fork-real/Makefile.test Makefile
make -rR -j2 all
test "$(cat combined)" = "$(printf 'left\nright')"
echo 'PASS make: parallel recipes with mutual handshake and dependency ordering'
make -rR -q all
echo 'PASS make: up-to-date target'
make -rR -n -B all > dry-run
test "$(wc -l < dry-run)" -eq 3
echo 'PASS make: dry run'
if make -rR fail; then exit 1; else code=$?; fi
test "$code" -eq 2
echo 'PASS make: failing recipe produces exit status 2'
printf 'MAKE REAL TEST PASS directory=%s\n' "$task_dir"
