#include "mmu-api.h"
static size_t length(const char *s) { size_t n = 0; while (s[n]) ++n; return n; }
static int equal(const char *a, const char *b)
{ while (*a && *a == *b) { ++a; ++b; } return *a == *b; }
static int output(const struct mmu_api *api, unsigned fd, const void *buffer, size_t size)
{
    const unsigned char *p = buffer;
    while (size) {
        size_t chunk = size > 4096 ? 4096 : size;
        intptr_t written = mmu_write(api, fd, p, chunk);
        if (written <= 0) return 1;
        p += written; size -= (size_t)written;
    }
    return 0;
}
static void text(const struct mmu_api *api, const char *s)
{ (void)output(api, 1, s, length(s)); }
static void number(const struct mmu_api *api, uint32_t n)
{
    char buffer[11]; unsigned count = 0;
    do { buffer[count++] = (char)('0' + n % 10); n /= 10; } while (n);
    while (count) (void)output(api, 1, &buffer[--count], 1);
}
static uint32_t heap_test(const struct mmu_api *api)
{
    unsigned char *blocks[32];
    unsigned i, j;
    for (i = 0; i < 32; ++i) {
        blocks[i] = mmu_alloc(api, 4096);
        if (!blocks[i]) return 1;
        for (j = 0; j < 4096; ++j) blocks[i][j] = (unsigned char)(i ^ j);
    }
    if (mmu_alloc(api, 1)) return 2; /* 128 KiB budget exhausted. */
    for (i = 0; i < 32; ++i) {
        for (j = 0; j < 4096; ++j)
            if (blocks[i][j] != (unsigned char)(i ^ j)) return 3;
        if (mmu_free(api, blocks[i])) return 4;
    }
    blocks[0] = mmu_alloc(api, 128 * 1024);
    if (!blocks[0]) return 5;
    if (mmu_free(api, blocks[0])) return 6;
    if (mmu_free(api, blocks[0]) >= 0) return 7; /* Double free rejected. */
    text(api, "PASS: 128 KiB heap, allocation limit, reuse and double-free rejection\n");
    return 0;
}
uint32_t mmu_main(uint32_t unused, const struct mmu_api *api)
{
    unsigned char *buffer;
    intptr_t input, destination = 1, got;
    uint32_t bytes = 0, lines = 0, words = 0;
    unsigned i;
    int count_mode, copy_mode, in_word = 0;
    (void)unused;
    if (!api || api->version != MMU_API_VERSION || api->size < sizeof(*api)) return 1;
    if (api->argc == 2 && equal(api->argv[1], "heap-test")) return heap_test(api);
    if (api->argc == 3 && equal(api->argv[1], "fault-resources")) {
        if (!mmu_alloc(api, 65536) || mmu_open(api, api->argv[2], 1) < 0) return 1;
        text(api, "Intentional fault with 64 KiB and one file still owned\n");
        __asm__ volatile("ill");
        return 1;
    }
    count_mode = api->argc >= 2 && equal(api->argv[1], "wc");
    copy_mode = api->argc >= 2 && equal(api->argv[1], "copy");
    if (!((api->argc == 3 && (count_mode || equal(api->argv[1], "cat"))) ||
          (api->argc == 4 && copy_mode))) {
        text(api, "Usage: tools.elf cat FILE | wc FILE | copy FILE /tmp/mmu-NEW | heap-test\n");
        return 2;
    }
    buffer = mmu_alloc(api, 4096);
    if (!buffer) { text(api, "Allocation failed\n"); return 1; }
    input = mmu_open(api, api->argv[2], 0);
    if (input < 0) { text(api, "Cannot open input\n"); return 1; }
    if (copy_mode) {
        destination = mmu_open(api, api->argv[3], 1);
        if (destination < 0) { text(api, "Cannot create new /tmp/mmu-* output\n"); return 1; }
    }
    while ((got = mmu_read(api, (unsigned)input, buffer, 4096)) > 0) {
        bytes += (uint32_t)got;
        if (!count_mode && output(api, (unsigned)destination, buffer, (size_t)got)) return 1;
        for (i = 0; i < (unsigned)got; ++i) {
            int space = buffer[i] == ' ' || (buffer[i] >= '\t' && buffer[i] <= '\r');
            if (buffer[i] == '\n') ++lines;
            if (!space && !in_word) ++words;
            in_word = !space;
        }
    }
    if (got < 0) { text(api, "Read failed\n"); return 1; }
    if (count_mode) {
        number(api, lines); text(api, " lines, ");
        number(api, words); text(api, " words, ");
        number(api, bytes); text(api, " bytes\n");
    } else if (copy_mode) { text(api, "Copied "); number(api, bytes); text(api, " bytes\n"); }
    if (mmu_close(api, (unsigned)input)) return 1;
    if (copy_mode && mmu_close(api, (unsigned)destination)) return 1;
    return mmu_free(api, buffer) ? 1 : 0;
}
