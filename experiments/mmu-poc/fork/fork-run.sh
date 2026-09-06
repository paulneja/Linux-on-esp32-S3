#!/bin/sh
if [ "$#" -eq 0 ]; then
    echo 'usage: fork-run PROGRAM [ARGS...]' >&2
    exit 2
fi
LD_PRELOAD="/usr/lib/libfork.so.0${LD_PRELOAD:+:$LD_PRELOAD}"
export LD_PRELOAD
exec "$@"
