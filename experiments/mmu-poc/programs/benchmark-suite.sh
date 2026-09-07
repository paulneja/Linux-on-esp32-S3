#!/usr/bin/dash
set -eu

available_kib() { awk '/^MemAvailable:/ {print $2}' /proc/meminfo; }

bench() {
	attempt=1
	while :; do
		if programbench "$@"; then
			return 0
		else
			code=$?
		fi
		if [ "$code" -ne 137 ] || [ "$attempt" -ge 3 ]; then
			echo "BENCH GAVE UP after $attempt attempt(s), exit=$code" >&2
			return "$code"
		fi
		echo "BENCH RETRY $attempt: measured program killed, available=$(available_kib) KiB"
		attempt=$((attempt + 1))
		sleep 3
	done
}
echo 'BENCHMARK bash'
bench -- /bin/bash /usr/share/program-tests/bash-test.sh
echo 'BENCHMARK dash'
bench -- /usr/bin/dash /usr/share/fork-real/dash-test.sh
echo 'BENCHMARK make'
work=$(mktemp -d /tmp/bench-make.XXXXXX)
cp /usr/share/fork-real/Makefile.test "$work/Makefile"
bench -- /usr/bin/make -C "$work" -rR -j2 all
rm -f "$work/Makefile" "$work/left" "$work/right" "$work/combined" "$work/left.started" "$work/right.started"
rmdir "$work"
echo 'BENCHMARK micropython'
bench -- /usr/bin/micropython /usr/share/program-tests/micropython-test.py
echo 'BENCHMARK socat'
bench -t 5 -- /usr/bin/socat -T1 -u EXEC:'/bin/echo socat-bench',pipes OPEN:/dev/null
echo 'BENCHMARK nc'
bench -- /bin/nc --help
echo 'BENCHMARK busybox'
bench -- /bin/busybox true
echo 'BENCHMARK jobq'
bench -- /usr/bin/jobq -j 2 -m 128 -r 384 -- /bin/sleep 0.2 ::: /bin/true
echo 'BENCHMARK COMPLETE'
