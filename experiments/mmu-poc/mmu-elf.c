#include <string.h>
#include "mmu-elf.h"
static uint32_t u16(const unsigned char *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8; }
static uint32_t u32(const unsigned char *p)
{ return u16(p) | u16(p + 2) << 16; }

const char *mmu_elf_validate_headers(const unsigned char *f, size_t header_size, size_t n,
                                     struct mmu_image *out)
{
    struct mmu_image image = {0};
    uint32_t phoff, phnum, i;
    int executable_entry = 0;
    if (header_size < 52 || n < 52 || n > ELF_FILE_LIMIT)
        return "ELF size outside limits";
    if (memcmp(f, "\177ELF", 4) || f[4] != 1 || f[5] != 1 || f[6] != 1 ||
        f[7] != 0 || f[8] != 0 || u16(f + 16) != 2 || u16(f + 18) != 94 ||
        u32(f + 20) != 1 || u16(f + 40) != 52 || u16(f + 42) != 32)
        return "requires ELF32 LE Xtensa ET_EXEC, non-FDPIC bare CALL0 ABI";
    phoff = u32(f + 28);
    phnum = u16(f + 44);
    if (!phnum || phnum > 32 || phoff < 52 || phoff > n || phoff > header_size ||
        phnum > (n - phoff) / 32 || phnum > (header_size - phoff) / 32)
        return "invalid program header table";
    image.entry = u32(f + 24);
    for (i = 0; i < phnum; ++i) {
        const unsigned char *p = f + phoff + i * 32;
        uint32_t type = u32(p), source = u32(p + 4), va = u32(p + 8);
        uint32_t filesz = u32(p + 16), memsz = u32(p + 20);
        uint32_t flags = u32(p + 24), align = u32(p + 28), offset, base, capacity;
        unsigned j;
        if (type == 2 || type == 3 || type == 7)
            return "dynamic loader, dependencies and TLS are unsupported";
        if (type != 1)
            continue;
        if (image.count == ELF_LOAD_LIMIT || filesz > memsz ||
            source > n || filesz > n - source)
            return "invalid LOAD size or file bounds";
        /* GNU ld emits an empty data PHDR for code-only payloads. */
        if (!memsz)
            continue;
        if (align > 1 && ((align & (align - 1)) ||
                         (va % align != source % align)))
            return "invalid LOAD alignment";
        if (flags == 5) {
            base = CODE_ADDRESS;
            offset = 0;
            capacity = CODE_CAPACITY;
        } else if (flags == 4 || flags == 6) {
            base = PAYLOAD_DATA;
            offset = DATA_OFFSET;
            capacity = DATA_CAPACITY;
        } else {
            return "LOAD must be RX code or R/RW data (no W+X)";
        }
        if (va < base || va - base > capacity ||
            memsz > capacity - (va - base))
            return "LOAD outside the reserved code/data window";
        offset += va - base;
        if (flags == 5 && image.entry >= va && image.entry - va < filesz)
            executable_entry = 1;
        for (j = 0; j < image.count; ++j) {
            const struct mmu_segment *s = &image.segments[j];
            if (offset < s->offset + s->memsz && s->offset < offset + memsz)
                return "overlapping LOAD memory";
        }
        image.segments[image.count++] =
            (struct mmu_segment){source, offset, filesz, memsz};
        for (j = offset / PAGE_SIZE; j <= (offset + memsz - 1) / PAGE_SIZE; ++j)
            image.page_mask |= 1u << j;
    }
    if (!executable_entry)
        return "entry is not inside executable file bytes";
    *out = image;
    return NULL;
}
const char *mmu_elf_validate(const unsigned char *f, size_t n, struct mmu_image *out)
{ return mmu_elf_validate_headers(f, n, n, out); }
void mmu_elf_copy(const unsigned char *file, const struct mmu_image *image,
                  struct mmu_memory *memory)
{
    unsigned i;
    for (i = 0; i < WINDOW_PAGES; ++i)
        if (image->page_mask & (1u << i)) memset(memory->pages[i], 0, PAGE_SIZE);
    for (i = 0; i < image->count; ++i) {
        const struct mmu_segment *s = &image->segments[i];
        uint32_t copied = 0;
        while (copied < s->filesz) {
            uint32_t offset = s->offset + copied;
            uint32_t chunk = PAGE_SIZE - offset % PAGE_SIZE;
            if (chunk > s->filesz - copied) chunk = s->filesz - copied;
            memcpy((unsigned char *)memory->pages[offset / PAGE_SIZE] + offset % PAGE_SIZE,
                   file + s->source + copied, chunk);
            copied += chunk;
        }
    }
}
