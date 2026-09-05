#!/usr/bin/dash
set -eu
task_dir=$(mktemp -d /tmp/mmu-dash.XXXXXX)
cd "$task_dir"
value=parent
( value=child; test "$value" = child )
test "$value" = parent
echo 'PASS dash: subshell variable isolation'
result=$(printf 'one\ntwo\nthree\n' | /bin/grep t | /usr/bin/wc -l)
test "$result" -eq 2
echo 'PASS dash: command substitution and three-stage pipeline'
( printf left > left ) &
left_pid=$!
( printf right > right ) &
right_pid=$!
wait "$left_pid"
wait "$right_pid"
test "$(cat left)$(cat right)" = leftright
echo 'PASS dash: background jobs and wait'
if ( exit 7 ); then exit 1; else code=$?; fi
test "$code" -eq 7
echo 'PASS dash: child exit status'
trapped=no
trap 'trapped=yes' USR1
kill -USR1 $$
test "$trapped" = yes
trap - USR1
echo 'PASS dash: signal trap'
i=0
while test "$i" -lt 10; do
    result=$( ( printf '%s' "$i" ) )
    test "$result" -eq "$i"
    i=$((i + 1))
done
echo 'PASS dash: ten nested substitutions'
printf 'DASH REAL TEST PASS directory=%s\n' "$task_dir"
