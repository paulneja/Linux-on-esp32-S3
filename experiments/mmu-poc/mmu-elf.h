#ifndef MMU_ELF_H
#define MMU_ELF_H
#include <stddef.h>
#include "mmu-layout.h"
#define ELF_FILE_LIMIT (1024u * 1024u)
#define ELF_LOAD_LIMIT 8u
#define ELF_HEADER_LIMIT (52u + 32u * 32u)
struct mmu_segment { uint32_t source, offset, filesz, memsz; };
struct mmu_image {
    uint32_t entry;
    unsigned count;
    unsigned page_mask;
    struct mmu_segment segments[ELF_LOAD_LIMIT];
};
const char *mmu_elf_validate(const unsigned char *file, size_t size,
                             struct mmu_image *image);
const char *mmu_elf_validate_headers(const unsigned char *header, size_t header_size,
                                    size_t file_size, struct mmu_image *image);
void mmu_elf_copy(const unsigned char *file, const struct mmu_image *image,
                  struct mmu_memory *memory);
#endif
