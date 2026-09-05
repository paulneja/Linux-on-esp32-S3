#!/bin/sh
# Supply fork() to dynamically linked Xtensa FDPIC programs on forkbank Linux.
# This is NOT an ELF/CPU emulator; static binaries cannot use LD_PRELOAD.
if [ "$#" -eq 0 ]; then
    echo 'usage: fork-run PROGRAM [ARGS...]' >&2
    exit 2
fi
LD_PRELOAD="/usr/lib/libfork.so.0${LD_PRELOAD:+:$LD_PRELOAD}"
export LD_PRELOAD
exec "$@"
