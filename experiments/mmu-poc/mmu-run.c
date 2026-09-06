#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include "mmu-elf.h"
#include "mmu-window.h"
#include "mmu-services.h"

struct program { struct mmu_memory memory; struct mmu_image image; };
static unsigned execution_timeout = 2;
static sigjmp_buf escape;
static volatile sig_atomic_t in_payload;
static unsigned char signal_stack[32768];
static sigset_t payload_mask;
static const int caught_signals[] = {
    SIGALRM, SIGINT, SIGTERM, SIGHUP, SIGQUIT, SIGSEGV, SIGBUS, SIGILL, SIGFPE
};

static void signal_handler(int sig)
{
    if (in_payload) siglongjmp(escape, sig);
    _exit(128 + sig);
}
static int setup_signals(void)
{
    unsigned i;
    sigset_t blocked;
    stack_t stack = {.ss_sp = signal_stack, .ss_size = sizeof(signal_stack)};
    struct sigaction action;
    sigfillset(&blocked);
    if (sigprocmask(SIG_SETMASK, &blocked, NULL) || sigaltstack(&stack, NULL)) return 1;
    memset(&action, 0, sizeof(action));
    action.sa_handler = signal_handler;
    action.sa_flags = SA_ONSTACK;
    sigfillset(&action.sa_mask);
    sigfillset(&payload_mask);
    for (i = 0; i < sizeof(caught_signals) / sizeof(*caught_signals); ++i) {
        if (sigaction(caught_signals[i], &action, NULL)) return 1;
        sigdelset(&payload_mask, caught_signals[i]);
    }
    return 0;
}

static int load_program(const char *path, struct program *program)
{
    struct stat st;
    unsigned char header[ELF_HEADER_LIMIT];
    const char *error;
    size_t have = 0, wanted;
    unsigned p;
    int result = 1, fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); return 1; }
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 52 ||
        st.st_size > (off_t)ELF_FILE_LIMIT) {
        fprintf(stderr, "STOP: invalid payload file size/type: %s\n", path);
        goto done;
    }
    wanted = (size_t)st.st_size < sizeof(header) ? (size_t)st.st_size : sizeof(header);
    while (have < wanted) {
        ssize_t got = read(fd, header + have, wanted - have);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) { fputs("STOP: short ELF read\n", stderr); goto done; }
        have += (size_t)got;
    }
    error = mmu_elf_validate_headers(header, have, (size_t)st.st_size, &program->image);
    if (error) { fprintf(stderr, "STOP: %s: %s\n", path, error); goto done; }
    for (p = 0; p < WINDOW_PAGES; ++p) {
        uintptr_t address;
        if (!(program->image.page_mask & (1u << p))) continue;
        void *page = mmap(NULL, PAGE_SIZE, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (page == MAP_FAILED) { perror("STOP: native page mmap"); goto done; }
        program->memory.pages[p] = page;
        address = (uintptr_t)program->memory.pages[p];
        if (address < RAM_START || address > RAM_END - PAGE_SIZE || address % PAGE_SIZE) {
            fputs("STOP: allocated page outside linear PSRAM\n", stderr); goto done;
        }
        memset(page, 0, PAGE_SIZE);
    }
    for (p = 0; p < program->image.count; ++p) {
        const struct mmu_segment *segment = &program->image.segments[p];
        uint32_t copied = 0;
        if (lseek(fd, segment->source, SEEK_SET) < 0) { perror("ELF seek"); goto done; }
        while (copied < segment->filesz) {
            uint32_t offset = segment->offset + copied;
            uint32_t chunk = PAGE_SIZE - offset % PAGE_SIZE;
            ssize_t got;
            if (chunk > segment->filesz - copied) chunk = segment->filesz - copied;
            got = read(fd, (unsigned char *)program->memory.pages[offset / PAGE_SIZE] +
                       offset % PAGE_SIZE, chunk);
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) { fputs("STOP: short LOAD read\n", stderr); goto done; }
            copied += (uint32_t)got;
        }
    }
    printf("Loaded %s: page_mask=0x%02x entry=0x%08lx segments=%u\n", path,
           program->image.page_mask, (unsigned long)program->image.entry, program->image.count);
    result = 0;
done:
    close(fd);
    return result;
}

static int invoke(const struct program *program, uint32_t argument,
                  const struct mmu_api *api, uint32_t *value)
{
    uint32_t descriptor[2] = {program->image.entry, 0};
    uint32_t (*function)(uint32_t, const struct mmu_api *) =
        (uint32_t (*)(uint32_t, const struct mmu_api *))(void *)descriptor;
    int caught = sigsetjmp(escape, 1);
    if (!caught) {
        sigset_t blocked;
        in_payload = 1;
        alarm(execution_timeout);
        if (sigprocmask(SIG_SETMASK, &payload_mask, NULL)) return -1;
        *value = function(argument, api);
        sigfillset(&blocked);
        if (sigprocmask(SIG_SETMASK, &blocked, NULL)) return -1;
    }
    alarm(0);
    in_payload = 0;
    return caught;
}

static void fatal_stop(struct mmu_window *window)
{
    fprintf(stderr, "FATAL stage=%u: pages retained; RESET BOARD, do not kill.\n",
            window->stage);
    fflush(NULL);
    for (;;) pause();
}

int main(int argc, char **argv)
{
    struct program programs[2] = {0};
    struct mmu_window window = {0};
    struct mmu_api api;
    unsigned i, count, calls;
    uint32_t argument = 0, value = 0;
    int test, execmode, result = 1, lock;
    if (argc == 2 && !strcmp(argv[1], "info")) {
        unsigned mapped = 0;
        for (i = 0; i < WINDOW_PAGES; ++i)
            if (REG32(MMU_TABLE + (ALIAS_SLOT + i) * 4) != INVALID) ++mapped;
        printf("MMU window: %s mapped=%u/%u data=0x%08lx code=0x%08lx capacity=%lu\n",
               mapped ? "BUSY" : "OFF", mapped, WINDOW_PAGES,
               (unsigned long)ALIAS_ADDRESS, (unsigned long)CODE_ADDRESS,
               (unsigned long)WINDOW_SIZE);
        return 0;
    }
    test = argc == 2 && !strcmp(argv[1], "self-test");
    execmode = argc >= 3 && !strcmp(argv[1], "exec");
    if (!test && !execmode && !(argc == 4 && !strcmp(argv[1], "run"))) {
        fprintf(stderr, "Usage: %s info | self-test | run payload.elf uint32 | exec payload.elf [args...]\n", argv[0]);
        fputs("Trusted bare CALL0 payloads only; NOT ordinary Linux binaries or a sandbox.\n", stderr);
        return 2;
    }
    if (!test && !execmode) {
        char *end;
        unsigned long n;
        errno = 0;
        n = strtoul(argv[3], &end, 0);
        if (errno || !argv[3][0] || argv[3][0] == '-' || *end || n > UINT32_MAX) {
            fputs("Invalid uint32 argument\n", stderr); return 2;
        }
        argument = (uint32_t)n;
    }
    if (execmode) execution_timeout = 10;
    services_init(&api, execmode ? (unsigned)argc - 2 : 0, execmode ? argv + 2 : NULL);
    lock = open("/run/mmu-window.lock", O_CREAT | O_RDWR, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) {
        perror("MMU window lock (another launcher may be active)"); return 1;
    }
    for (i = 0; i < WINDOW_PAGES; ++i)
        if (REG32(MMU_TABLE + 4 * (ALIAS_SLOT + i)) != INVALID) {
            fputs("STOP: alias already mapped\n", stderr); goto done;
        }
    for (i = 0x180; i < MMU_COUNT; ++i)
        if (REG32(MMU_TABLE + 4 * i) != (PSRAM | (i - 0x180))) {
            fputs("STOP: expected 8 MiB PSRAM layout not found\n", stderr); goto done;
        }
    count = test ? 2 : 1;
    calls = test ? 4 : 1;
    for (i = 0; i < count; ++i) {
        const char *path = test ? (i ? "/usr/share/mmu/counter-b.elf" :
                                      "/usr/share/mmu/counter-a.elf") : argv[2];
        if (load_program(path, &programs[i])) goto done;
    }
    if (setup_signals()) { perror("signal setup"); goto done; }
    fflush(NULL);
    for (i = 0; i < calls; ++i) {
        static const uint32_t expected[] = {103, 1006, 106, 1012};
        struct program *program = &programs[i % count];
        int caught;
        if (window_switch(&window, &program->memory)) {
            fprintf(stderr, "FAIL: map stage=%u\n", window.stage); goto cleanup;
        }
        printf("MMU ON: program=%u code=0x%08lx switch_cycles=%lu\n", i % count,
               (unsigned long)program->image.entry, (unsigned long)window.cycles);
        fflush(stdout);
        caught = invoke(program, test ? 3 : argument, &api, &value);
        if (caught) {
            fprintf(stderr, "Payload stopped: signal=%d%s\n", caught,
                    caught == SIGALRM ? " (timeout)" : "");
            result = caught > 0 ? 128 + caught : 1;
            goto cleanup;
        }
        printf("Result: %lu\n", (unsigned long)value);
        if (test && value != expected[i]) {
            fprintf(stderr, "FAIL: expected %lu\n", (unsigned long)expected[i]);
            goto cleanup;
        }
    }
    result = execmode ? (value <= 125 ? (int)value : 1) : 0;
cleanup:
    if (window.fatal) fatal_stop(&window);
    if (window.active && window_switch(&window, NULL)) fatal_stop(&window);
    for (i = 0; i < WINDOW_PAGES; ++i)
        if (REG32(MMU_TABLE + 4 * (ALIAS_SLOT + i)) != INVALID) fatal_stop(&window);
    puts("MMU OFF: alias invalid, core 0 and IRQs restored.");
    if (!result && test) {
        uint32_t a, b;
        memcpy(&a, programs[0].memory.pages[DATA_OFFSET / PAGE_SIZE], 4);
        memcpy(&b, programs[1].memory.pages[DATA_OFFSET / PAGE_SIZE], 4);
        if (a != 106 || b != 1012) {
            fputs("FAIL: native state readback\n", stderr); result = 1;
        } else puts("PASS: executable A -> B -> A -> B; independent state, native readback.");
    }
done:
    services_cleanup();
    for (i = 0; i < WINDOW_PAGES; ++i) {
        if (programs[0].memory.pages[i]) munmap(programs[0].memory.pages[i], PAGE_SIZE);
        if (programs[1].memory.pages[i]) munmap(programs[1].memory.pages[i], PAGE_SIZE);
    }
    close(lock);
    return result;
}
