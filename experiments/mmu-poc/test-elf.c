#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mmu-elf.h"
static unsigned char sample[160];
static unsigned checks;
static void put(unsigned char *p, uint32_t v)
{ p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static void reset(void)
{
    memset(sample, 0, sizeof(sample));
    memcpy(sample, "\177ELF\1\1\1", 7);
    sample[16] = 2; sample[18] = 94; sample[20] = 1;
    put(sample + 24, CODE_ADDRESS); put(sample + 28, 52);
    sample[40] = 52; sample[42] = 32; sample[44] = 2;
    put(sample + 52, 1); put(sample + 56, 128);
    put(sample + 60, CODE_ADDRESS); put(sample + 68, 4);
    put(sample + 72, 4); put(sample + 76, 5);
    put(sample + 84, 1); put(sample + 88, 132);
    put(sample + 92, PAYLOAD_DATA); put(sample + 100, 4);
    put(sample + 104, 12); put(sample + 108, 6);
    memcpy(sample + 128, "CODEDATA", 8);
}
static void reject(size_t size)
{
    struct mmu_image image, original;
    memset(&image, 0xa5, sizeof(image)); original = image;
    assert(mmu_elf_validate(sample, size, &image));
    assert(!memcmp(&image, &original, sizeof(image)));
    ++checks;
}
int main(int argc, char **argv)
{
    struct mmu_image image;
    unsigned char *page = malloc(WINDOW_SIZE);
    struct mmu_memory memory;
    unsigned i;
    uint32_t random = 47;
    assert(page);
    for (i = 0; i < WINDOW_PAGES; ++i) memory.pages[i] = page + i * PAGE_SIZE;
    reset();
    assert(!mmu_elf_validate(sample, sizeof(sample), &image));
    assert(!mmu_elf_validate_headers(sample, 116, sizeof(sample), &image));
    assert(mmu_elf_validate_headers(sample, 115, sizeof(sample), &image));
    assert(mmu_elf_validate_headers(sample, 52, sizeof(sample), &image));
    checks += 3;
    mmu_elf_copy(sample, &image, &memory);
    assert(!memcmp(page, "CODE", 4));
    assert(!memcmp(page + DATA_OFFSET, "DATA", 4));
    assert(!page[DATA_OFFSET + 4] && !page[PAGE_SIZE - 1]);
    assert(image.page_mask == ((1u << 0) | (1u << (DATA_OFFSET / PAGE_SIZE))));
    ++checks;
    for (i = 0; i < 136; ++i) reject(i);
#define BAD(at, value) do { reset(); put(sample + (at), (value)); reject(sizeof(sample)); } while (0)
    BAD(0, 0); BAD(4, 0x010102); BAD(7, 65); BAD(16, 3);
    BAD(20, 0); BAD(24, PAYLOAD_DATA); BAD(24, CODE_ADDRESS + 4);
    BAD(28, UINT32_MAX); BAD(40, 0); BAD(44, 33);
    BAD(52, 2); BAD(52, 3); BAD(52, 7);
    BAD(56, UINT32_MAX); BAD(60, CODE_ADDRESS - 1);
    BAD(68, 5); BAD(72, UINT32_MAX); BAD(76, 7); BAD(80, 3);
    BAD(92, PAYLOAD_DATA - 1); BAD(100, 13); BAD(104, DATA_CAPACITY + 1);
    reset(); put(sample + 92, CODE_ADDRESS); put(sample + 108, 5); reject(sizeof(sample));
    /* Deterministic mutation smoke test; ASan/UBSan check validator+copy bounds. */
    for (i = 0; i < 50000; ++i) {
        unsigned j, changes = i % 8 + 1;
        reset();
        for (j = 0; j < changes; ++j) {
            random = random * 1664525u + 1013904223u;
            sample[random % sizeof(sample)] ^= (unsigned char)(random >> 24);
        }
        if (!mmu_elf_validate(sample, sizeof(sample), &image))
            mmu_elf_copy(sample, &image, &memory);
    }
    for (i = 1; i < (unsigned)argc; ++i) {
        unsigned char *file = malloc(ELF_FILE_LIMIT);
        FILE *stream = fopen(argv[i], "rb");
        size_t size;
        const char *error;
        assert(file && stream);
        size = fread(file, 1, ELF_FILE_LIMIT, stream);
        assert(!ferror(stream)); fclose(stream);
        error = mmu_elf_validate(file, size, &image);
        if (error) { fprintf(stderr, "%s: %s\n", argv[i], error); return 1; }
        mmu_elf_copy(file, &image, &memory);
        printf("PASS: %s entry=0x%08x\n", argv[i], image.entry);
        free(file);
    }
    free(page);
    printf("PASS: %u format checks + 50000 mutations\n", checks);
    return 0;
}
