/* Local ESP32-S3/N16R8 experiment. MMU writes require --remap-esp32s3. */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "mmu-layout.h"

static const char *kind(uint32_t entry)
{
    if (entry & INVALID)
        return "unmapped";
    return entry & PSRAM ? "psram" : "flash";
}

static int extends(uint32_t first, uint32_t next, unsigned distance)
{
    if (first & INVALID)
        return !!(next & INVALID);
    return !(next & INVALID) &&
           (first & PSRAM) == (next & PSRAM) &&
           (first & PAGE_MASK) + distance == (next & PAGE_MASK);
}

static int expected_ram(const uint32_t *map)
{
    unsigned i;
    for (i = 0x180; i < MMU_COUNT; ++i)
        if (map[i] != (PSRAM | (i - 0x180)))
            return 0;
    return 1;
}

static int owned_page(uintptr_t address, const uint32_t *map)
{
    unsigned slot;
    if (address < RAM_START || address > RAM_END - PAGE_SIZE ||
        address % PAGE_SIZE)
        return 0;
    slot = (unsigned)((address - DATA_BASE) / PAGE_SIZE);
    return map[slot] == (PSRAM | (slot - 0x180));
}

#ifdef __XTENSA__
#include <fcntl.h>
#include <sys/file.h>
static void dump_map(const uint32_t *map)
{
    unsigned first = 0, end;
    while (first < MMU_COUNT) {
        end = first + 1;
        while (end < MMU_COUNT && extends(map[first], map[end], end - first))
            ++end;
        printf("%03x..%03x data=0x%08lx..0x%08lx %-8s",
               first, end - 1,
               (unsigned long)(DATA_BASE + first * PAGE_SIZE),
               (unsigned long)(DATA_BASE + end * PAGE_SIZE - 1),
               kind(map[first]));
        if (!(map[first] & INVALID))
            printf(" physical=0x%08lx",
                   (unsigned long)((map[first] & PAGE_MASK) * PAGE_SIZE));
        putchar('\n');
        first = end;
    }
}
#endif

static int self_test(void)
{
    uint32_t map[MMU_COUNT];
    unsigned i;
    for (i = 0; i < MMU_COUNT; ++i)
        map[i] = i < 0x100 ? i : i < 0x180 ? INVALID : PSRAM | (i - 0x180);
#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)
    CHECK(strcmp(kind(0), "flash") == 0);
    CHECK(strcmp(kind(PSRAM), "psram") == 0);
    CHECK(strcmp(kind(INVALID | PSRAM), "unmapped") == 0);
    CHECK(extends(PSRAM | 3, PSRAM | 5, 2));
    CHECK(!extends(PSRAM | 3, 5, 2));
    CHECK(!extends(PSRAM | 3, INVALID | PSRAM | 5, 2));
    CHECK(!extends(PSRAM | 3, PSRAM | 6, 2));
    CHECK(extends(INVALID, INVALID, 10));
    CHECK(!extends(INVALID, PSRAM, 1));
    CHECK(expected_ram(map));
    CHECK(owned_page(RAM_START, map));
    CHECK(owned_page(RAM_END - PAGE_SIZE, map));
    CHECK(!owned_page(RAM_START + 1, map));
    CHECK(!owned_page(RAM_START - PAGE_SIZE, map));
    CHECK(!owned_page(RAM_END, map));
    CHECK(!owned_page(UINTPTR_MAX, map));
    map[0x180] = INVALID;
    CHECK(!expected_ram(map));
    CHECK(!owned_page(RAM_START, map));
    puts("PASS: host decoding/bounds tests (not a hardware remap test)");
    return 0;
#undef CHECK
}

#ifdef __XTENSA__
#include "mmu-remap.h"

static int inspect(int remap)
{
    const volatile uint32_t *table = (const volatile uint32_t *)MMU_TABLE;
    uint32_t map[MMU_COUNT];
    void *pages[2] = {NULL, NULL};
    unsigned i, p;
    int result = 1;

    puts(remap ? "ESP32-S3 MMU remap experiment: owned pages only." :
                 "ESP32-S3 MMU preflight: read-only registers; no remapping.");
    for (i = 0; i < MMU_COUNT; ++i)
        map[i] = table[i];
    dump_map(map);
    if (!expected_ram(map)) {
        fputs("STOP: expected linear 8 MiB PSRAM map not found.\n", stderr);
        return 1;
    }
    if (map[ALIAS_SLOT] != INVALID) {
        fputs("STOP: candidate alias 0x3d000000 is not empty.\n", stderr);
        return 1;
    }
    for (p = 0; p < 2; ++p) {
        volatile uint32_t *words;
        int err = posix_memalign(&pages[p], PAGE_SIZE, PAGE_SIZE);
        if (err) {
            fprintf(stderr, "STOP: allocate page %u: %s\n", p, strerror(err));
            goto done;
        }
        if (!owned_page((uintptr_t)pages[p], map)) {
            fputs("STOP: allocation outside expected PSRAM mapping.\n", stderr);
            goto done;
        }
        words = pages[p];
        for (i = 0; i < PAGE_SIZE / sizeof(*words); ++i)
            words[i] = UINT32_C(0xa5000000) ^ (p << 20) ^ i;
    }
    for (p = 0; p < 2; ++p) {
        volatile uint32_t *words = pages[p];
        for (i = 0; i < PAGE_SIZE / sizeof(*words); ++i) {
            if (words[i] != (UINT32_C(0xa5000000) ^ (p << 20) ^ i)) {
                fprintf(stderr, "STOP: allocation %u word %u mismatch.\n", p, i);
                goto done;
            }
        }
        printf("Owned page %u: native=%p size=65536 PASS\n", p, pages[p]);
    }
    for (i = 0; i < MMU_COUNT; ++i) {
        /* Core 0 may temporarily map flash. PSRAM and alias must stay stable. */
        if (i >= 0x100 && table[i] != map[i]) {
            fputs("STOP: upper MMU map changed during inspection.\n", stderr);
            goto done;
        }
    }
    puts("PASS: preflight. Candidate alias=0x3d000000, two owned pages.");
    if (remap) {
        struct remap_result stats = {0};
        sigset_t blocked, previous;
        int failed;
        sigfillset(&blocked);
        if (sigprocmask(SIG_BLOCK, &blocked, &previous)) {
            perror("sigprocmask");
            goto done;
        }
        puts("Running A -> B -> A -> B; temporarily pause core 0 and local IRQs.");
        fflush(stdout);
        failed = remap_pages(pages, &stats);
        printf("Remap: switches=%u comparisons=%u cycles=%lu stage=%u fatal=%d\n",
               stats.switches, stats.comparisons, (unsigned long)stats.cycles,
               stats.stage, stats.fatal);
        if (stats.fatal) {
            fputs("FATAL: cache cleanup failed. Allocations retained. RESET BOARD; do not kill this process.\n", stderr);
            fflush(NULL);
            for (;;)
                pause();
        }
        if (sigprocmask(SIG_SETMASK, &previous, NULL)) {
            perror("restore signals");
            goto done;
        }
        if (failed) {
            fputs("FAIL: remap aborted; core 0/IRQs restored.\n", stderr);
            goto done;
        }
        for (p = 0; p < 2; ++p) {
            volatile uint32_t *words = pages[p];
            for (i = 0; i < PAGE_SIZE / sizeof(*words); ++i) {
                if (words[i] != (UINT32_C(0xa5550000) ^ (p << 20) ^ i)) {
                    fputs("FAIL: native readback after alias writes.\n", stderr);
                    goto done;
                }
            }
        }
        if (table[ALIAS_SLOT] != INVALID) {
            fputs("FATAL: alias still mapped. RESET BOARD.\n", stderr);
            fflush(NULL);
            for (;;)
                pause();
        }
        puts("PASS: read/write A -> B -> A -> B, native readback, alias OFF.");
    } else {
        puts("Not tested: remap, cache synchronization, executable alias, fork.");
    }
    result = 0;
done:
    free(pages[1]);
    free(pages[0]);
    return result;
}
#endif

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--self-test") == 0)
        return self_test();
    if (argc == 2 && (strcmp(argv[1], "--inspect-esp32s3") == 0 ||
                      strcmp(argv[1], "--remap-esp32s3") == 0)) {
#ifdef __XTENSA__
        int remap = strcmp(argv[1], "--remap-esp32s3") == 0;
        int lock = -1, result;
        if (remap) {
            lock = open("/run/mmu-window.lock", O_CREAT | O_RDWR, 0600);
            if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) {
                perror("MMU window lock");
                if (lock >= 0) close(lock);
                return 1;
            }
        }
        result = inspect(remap);
        if (lock >= 0) close(lock);
        return result;
#else
        fputs("Hardware inspection requires the ESP32-S3 Linux build.\n", stderr);
        return 2;
#endif
    }
    printf("Usage: %s --self-test | --inspect-esp32s3 | --remap-esp32s3\n", argv[0]);
    puts("Inspection is ONLY for native NOMMU Linux on ESP32-S3/N16R8.");
    return argc == 1 ? 0 : 2;
}
