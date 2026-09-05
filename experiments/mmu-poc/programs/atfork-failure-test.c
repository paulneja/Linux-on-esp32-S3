#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static char order[5];
static unsigned position;
static void prepare(void) { order[position++] = 'P'; }
static void parent(void) { order[position++] = 'A'; errno = EINVAL; }
static void child(void) { order[position++] = 'C'; }
long __wrap_syscall(long number, ...) {
    (void)number;
    errno = ENOMEM;
    return -1;
}
int main(void) {
    if (pthread_atfork(prepare, parent, child)) return 1;
    if (fork() != -1 || errno != ENOMEM || strcmp(order, "PA")) return 2;
    puts("PASS atfork: failed clone calls parent callbacks and preserves errno");
    return 0;
}
