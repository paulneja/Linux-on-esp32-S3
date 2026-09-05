#!/bin/bash
# Run on the board; never clear dmesg or change the global console log level.
set -e
parameter=/sys/module/nommu/parameters/fork_bank_trace
test -w "$parameter"
test "$(cat "$parameter")" = N
trap 'printf N > "$parameter"' EXIT
count_traces() { dmesg | grep -c 'nommu: fork-bank: parent=' || :; }
before=$(count_traces)
i=0
while [ "$i" -lt 20 ]; do /bin/true; i=$((i + 1)); done
test "$(count_traces)" = "$before"
echo 'PASS: 20 external commands do not log successful forks by default'
printf Y > "$parameter"
/bin/true
printf N > "$parameter"
after=$(count_traces)
test "$after" -gt "$before"
echo 'PASS: explicit tracing records successful forks'
i=0
while [ "$i" -lt 20 ]; do /bin/true; i=$((i + 1)); done
test "$(count_traces)" = "$after"
echo 'PASS: tracing disabled again; no new successful-fork messages'
