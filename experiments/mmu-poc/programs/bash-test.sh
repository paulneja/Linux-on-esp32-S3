#!/bin/bash
set -euo pipefail
[[ ${BASH_VERSINFO[0]} -eq 5 ]]
array=(uno dos tres)
declare -A ports=([tcp]=49173 [udp]=49174)
[[ ${array[1]} == dos && ${ports[tcp]} == 49173 ]]
[[ abcd =~ ^a.*d$ ]]
printf 'PASS bash: arrays, associative arrays and regex\n'
value=parent
(value=child; [[ $value == child ]])
[[ $value == parent ]]
value=$(printf 'one\ntwo\nthree\n' | grep t | wc -l)
[[ $value -eq 2 ]]
printf 'PASS bash: fork isolation, substitution and pipeline\n'
set +e
(exit 7) | (exit 0)
statuses=("${PIPESTATUS[@]}")
set -e
[[ ${statuses[0]} == 7 && ${statuses[1]} == 0 ]]
printf 'PASS bash: PIPESTATUS\n'
mapfile -t lines < <(printf 'alpha\nbeta\n')
[[ ${#lines[@]} == 2 && ${lines[1]} == beta ]]
printf 'PASS bash: process substitution and mapfile\n'
(exit 9) &
child=$!
set +e
wait "$child"
status=$?
set -e
[[ $status == 9 ]]
seen=no
trap 'seen=yes' USR1
kill -USR1 $$
[[ $seen == yes ]]
trap - USR1
for ((i=0; i<10; i++)); do
    [[ $(printf '%s' "$i") == "$i" ]]
done
printf 'PASS bash: wait, signals and ten repeated forks\n'
printf 'BASH TEST PASS %s\n' "$BASH_VERSION"
