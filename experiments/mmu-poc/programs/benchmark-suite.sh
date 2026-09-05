#!/usr/bin/dash
# Run in a quiet board. Times include instrumentation; global counters can
# include background services. Requested polling interval is 10 ms, not a peak guarantee.
set -eu
echo 'BENCHMARK bash'
programbench -- /bin/bash /usr/share/program-tests/bash-test.sh
echo 'BENCHMARK dash'
programbench -- /usr/bin/dash /usr/share/fork-real/dash-test.sh
echo 'BENCHMARK make'
work=$(mktemp -d /tmp/bench-make.XXXXXX)
cp /usr/share/fork-real/Makefile.test "$work/Makefile"
programbench -- /usr/bin/make -C "$work" -rR -j2 all
echo 'BENCHMARK micropython'
programbench -- /usr/bin/micropython /usr/share/program-tests/micropython-test.py
echo 'BENCHMARK socat'
programbench -- /usr/bin/socat -u EXEC:'/bin/sleep 0.2' -
echo 'BENCHMARK nc'
programbench -- /bin/nc -h
echo 'BENCHMARK busybox'
programbench -- /bin/busybox true
echo 'BENCHMARK jobq'
programbench -- /usr/bin/jobq -j 2 -m 128 -r 384 -- /bin/sleep 0.2 ::: /bin/true
echo 'BENCHMARK COMPLETE'
