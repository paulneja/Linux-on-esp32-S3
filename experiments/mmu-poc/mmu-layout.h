#ifndef MMU_LAYOUT_H
#define MMU_LAYOUT_H
#include <stdint.h>
#define PAGE_SIZE UINT32_C(0x10000)
#define MMU_COUNT 512u
#define MMU_TABLE UINT32_C(0x600c5000)
#define DATA_BASE UINT32_C(0x3c000000)
#define RAM_START UINT32_C(0x3d800000)
#define RAM_END UINT32_C(0x3e000000)
#define INVALID UINT32_C(0x4000)
#define PSRAM UINT32_C(0x8000)
#define PAGE_MASK UINT32_C(0x3fff)
#define RAM_PAGES 128u
#define ALIAS_SLOT 0x100u
#define ALIAS_ADDRESS UINT32_C(0x3d000000)
#define CODE_ADDRESS UINT32_C(0x43000000)
#define WINDOW_PAGES 12u
#define WINDOW_SIZE (WINDOW_PAGES * PAGE_SIZE)
#define CODE_CAPACITY (8u * PAGE_SIZE)
#define DATA_CAPACITY (4u * PAGE_SIZE)
#define DATA_OFFSET CODE_CAPACITY
#define PAYLOAD_DATA (ALIAS_ADDRESS + DATA_OFFSET)
struct mmu_memory { void *pages[WINDOW_PAGES]; };
static inline int ram_layout_ok(const uint32_t *map)
{
    uint8_t seen[RAM_PAGES] = {0};
    unsigned i;
    for (i = MMU_COUNT - RAM_PAGES; i < MMU_COUNT; ++i) {
        uint32_t page = map[i] & PAGE_MASK;
        if ((map[i] & ~PAGE_MASK) != PSRAM || page >= RAM_PAGES || seen[page]++)
            return 0;
    }
    return 1;
}
#endif
