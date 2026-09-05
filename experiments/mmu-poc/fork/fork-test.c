#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern pid_t fork(void);
static volatile unsigned global_value = 123;
static volatile unsigned bss_value;
static unsigned tests;

static void fail(const char *what)
{
    dprintf(2, "FAIL: %s errno=%d (%s) pid=%ld\n", what, errno,
            strerror(errno), (long)getpid());
    _exit(1);
}
#define CHECK(x) do { if (!(x)) fail(#x); } while (0)
static void pass(const char *what)
{
    printf("PASS: %s\n", what);
    fflush(stdout);
    tests++;
}
static pid_t spawn(void)
{
    pid_t pid = fork();
    CHECK(pid >= 0);
    return pid;
}
static void reap(pid_t child, int code)
{
    int status;
    CHECK(waitpid(child, &status, 0) == child);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == code);
}
static void transfer(int fd, void *buf, size_t len, int writing)
{
    char *p = buf;
    while (len) {
        ssize_t n = writing ? write(fd, p, len) : read(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        CHECK(n > 0);
        p += n;
        len -= (size_t)n;
    }
}

int main(int argc, char **argv)
{
    volatile unsigned stack_value = 456;
    unsigned *heap = malloc(8192);
    int p2c[2], c2p[2], status;
    pid_t child, parent = getpid();
    unsigned i, token;
    if (argc == 2 && !strcmp(argv[1], "--exec-child")) return 42;
    CHECK(heap);
    alarm(25);
    for (i = 0; i < 2048; i++) heap[i] = i ^ 0x13579U;
    CHECK(pipe(p2c) == 0 && pipe(c2p) == 0);
    fflush(NULL);
    child = spawn();
    if (!child) {
        CHECK(getpid() != parent && getppid() == parent);
        CHECK(global_value == 123 && bss_value == 0 && stack_value == 456);
        global_value = 999; bss_value = 777; stack_value = 888;
        for (i = 0; i < 2048; i++) {
            CHECK(heap[i] == (i ^ 0x13579U));
            heap[i] = i ^ 0x24680U;
        }
        close(p2c[1]); close(c2p[0]);
        for (i = 0; i < 64; i++) {
            transfer(p2c[0], &token, sizeof(token), 0);
            CHECK(token == i);
            CHECK(global_value == 999 && bss_value == 777 && stack_value == 888);
            CHECK(heap[2047] == (2047U ^ 0x24680U));
            token += 1000;
            transfer(c2p[1], &token, sizeof(token), 1);
        }
        _exit(37);
    }
    printf("fork: parent=%ld child=%ld stack=%p heap=%p\n",
           (long)parent, (long)child, (void *)&stack_value, (void *)heap);
    fflush(stdout);
    close(p2c[0]); close(c2p[1]);
    for (i = 0; i < 64; i++) {
        token = i;
        transfer(p2c[1], &token, sizeof(token), 1);
        transfer(c2p[0], &token, sizeof(token), 0);
        CHECK(token == i + 1000);
        CHECK(global_value == 123 && bss_value == 0 && stack_value == 456);
        CHECK(heap[2047] == (2047U ^ 0x13579U));
    }
    close(p2c[1]); close(c2p[0]);
    reap(child, 37);
    pass("independent globals/BSS/stack/heap, 64 bidirectional pipe handshakes, waitpid=37");

    child = spawn();
    if (!child) {
        pid_t grandchild;
        global_value = 321;
        grandchild = spawn();
        if (!grandchild) {
            CHECK(global_value == 321);
            global_value = 654;
            _exit(23);
        }
        reap(grandchild, 23);
        CHECK(global_value == 321);
        _exit(24);
    }
    reap(child, 24);
    CHECK(global_value == 123);
    pass("nested fork, three independent processes");

    child = spawn();
    if (!child) {
        execlp(argv[0], argv[0], "--exec-child", (char *)NULL);
        fail("exec");
    }
    reap(child, 42);
    CHECK(global_value == 123 && heap[2047] == (2047U ^ 0x13579U));
    pass("fork + exec + waitpid=42");

    CHECK(pipe(p2c) == 0);
    child = spawn();
    if (!child) {
        close(p2c[1]);
        transfer(p2c[0], &token, sizeof(token), 0);
        _exit(99);
    }
    close(p2c[0]);
    CHECK(kill(child, SIGTERM) == 0);
    CHECK(waitpid(child, &status, 0) == child);
    CHECK(WIFSIGNALED(status) && WTERMSIG(status) == SIGTERM);
    close(p2c[1]);
    pass("SIGTERM and signal exit status");

    for (i = 0; i < 8; i++) {
        child = spawn();
        if (!child) { global_value = i + 1; _exit((int)i); }
        reap(child, (int)i);
        CHECK(global_value == 123);
    }
    pass("eight repeated forks, child teardown preserves parent");
    free(heap);
    alarm(0);
    printf("PASS: fork suite %u/5\n", tests);
    return tests == 5 ? 0 : 1;
}
