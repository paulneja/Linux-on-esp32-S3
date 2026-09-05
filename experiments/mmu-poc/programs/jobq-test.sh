#!/usr/bin/dash
set -eu
work=$(mktemp -d /tmp/jobq-test.XXXXXX)
trap 'rm -f "$work/log"; rmdir "$work"' EXIT
jobq -j 2 -m 128 -r 384 -- /bin/sleep 1 ::: /bin/sleep 1 ::: /bin/true > "$work/log"
cat "$work/log"
grep -q 'active=2' "$work/log"
test "$(grep -c '^START ' "$work/log")" -eq 3
test "$(grep -c '^EXIT .*code=0 ' "$work/log")" -eq 3
if jobq -r 2147483647 -w 1 -- /bin/true > "$work/log" 2>&1; then exit 1; fi
! grep -q '^START ' "$work/log"
grep -q ADMISSION_TIMEOUT "$work/log"
if jobq -- /does-not-exist > "$work/log" 2>&1; then exit 1; fi
grep -q 'code=127' "$work/log"
if jobq -t 1 -- /bin/sleep 3 > "$work/log" 2>&1; then exit 1; fi
grep -q 'code=137' "$work/log"
echo 'PASS: jobq concurrency=2, memory refusal, exec failure and timeout'
