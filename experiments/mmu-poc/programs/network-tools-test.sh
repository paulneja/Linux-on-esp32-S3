#!/usr/bin/dash
set -eu
task_dir=$(mktemp -d /tmp/network-tools.XXXXXX)
server=
cleanup() {
    if test -n "$server"; then
        kill "$server" 2>/dev/null || true
        wait "$server" 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM
cd "$task_dir"
printf 'file-transfer\n' > input
socat -u OPEN:input OPEN:output,creat,trunc
cmp input output
echo 'PASS socat: file transfer'

socat TCP4-LISTEN:49173,bind=127.0.0.1,reuseaddr,fork EXEC:/bin/cat > tcp.log 2>&1 &
server=$!
sleep 1
for message in first second third; do
    printf '%s\n' "$message" | nc -w 1 127.0.0.1 49173 > reply
    test "$(cat reply)" = "$message"
done
kill -0 "$server"
cleanup
server=
echo 'PASS socat + nc: TCP loopback, fork and exec, three clients'

socat -u -T2 UDP4-RECVFROM:49174,bind=127.0.0.1,reuseaddr OPEN:udp-reply,creat,trunc > udp.log 2>&1 &
server=$!
sleep 1
printf 'udp-loopback\n' | nc -u -w 1 127.0.0.1 49174
wait "$server"
server=
test "$(cat udp-reply)" = udp-loopback
echo 'PASS socat + nc: UDP loopback'

socat UNIX-LISTEN:"$task_dir/socket",fork EXEC:/bin/cat > unix.log 2>&1 &
server=$!
sleep 1
printf 'unix-loopback\n' | socat -T2 - UNIX-CONNECT:"$task_dir/socket" > unix-reply
test "$(cat unix-reply)" = unix-loopback
cleanup
server=
echo 'PASS socat: Unix socket, fork and exec'
cd /
rm -f "$task_dir/input" "$task_dir/output" "$task_dir/tcp.log" "$task_dir/reply" \
    "$task_dir/udp.log" "$task_dir/udp-reply" "$task_dir/unix.log" \
    "$task_dir/unix-reply" "$task_dir/socket"
rmdir "$task_dir"
echo 'NETWORK TOOLS TEST PASS (temporary files removed)'
