#!/usr/bin/env python3
"""Compile the actual patched bgp_resize with a host fixture."""
from pathlib import Path
import os
import subprocess
import sys

source_dir = Path(sys.argv[1])
output = Path(sys.argv[2])
source = (source_dir / "jobs.c").read_text()
start = source.index("static void\nbgp_resize ()")
end = source.index("\nstatic ps_index_t\nbgp_getindex", start)
fixture = r'''
#include <assert.h>
#include <limits.h>
#include <stdlib.h>
#include <stdio.h>
typedef int ps_index_t;
struct pidstat { int bucket_next, bucket_prev, pid, status; };
struct { struct pidstat *storage; int nalloc, head; } bgpids;
struct { int c_childmax; } js;
#define TYPE_MAXIMUM(t) INT_MAX
#define PIDSTAT_TABLE_SZ 4096
#define BGPIDS_TABLE_SZ 512
#define MAX_CHILD_MAX 32768
#define NO_PIDSTAT -1
#define NO_PID -1
int pidstat_table[PIDSTAT_TABLE_SZ];
static size_t calls, last_size;
static void *xrealloc(void *ptr, size_t size) {
    calls++; last_size = size;
    ptr = realloc(ptr, size); assert(ptr); return ptr;
}
'''
test = r'''
int main(void) {
    js.c_childmax = MAX_CHILD_MAX;
    bgp_resize();
    assert(bgpids.nalloc == 512 && last_size == 8192 && calls == 1);
    for (int i = 0; i < MAX_CHILD_MAX; i++) {
        bgp_resize();
        assert(bgpids.head == i && bgpids.nalloc > i);
        bgpids.storage[bgpids.head++].pid = 1000 + i;
    }
    for (int i = 0; i < MAX_CHILD_MAX; i++)
        assert(bgpids.storage[i].pid == 1000 + i);
    size_t before = calls;
    bgp_resize();
    assert(bgpids.nalloc == MAX_CHILD_MAX && bgpids.head == 0 && calls == before);
    free(bgpids.storage);
    puts("PASS bash PID cache: starts at 8 KiB, lazy growth, preserves entries, wraps at original limit");
}
'''
subprocess.run(["cc", "-x", "c", "-std=c99", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-o", str(output), "-"],
               input=fixture + source[start:end] + test, text=True, check=True)
# LeakSanitizer cannot inspect tasks under the desktop sandbox's ptrace layer.
subprocess.run([str(output.resolve())], check=True,
               env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
