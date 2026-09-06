#ifndef MMU_WINDOW_H
#define MMU_WINDOW_H
#include "mmu-hw.h"
struct mmu_window { struct mmu_memory *active; unsigned stage; int fatal; uint32_t cycles; };

static uint32_t page_entry(void *page)
{ return page ? PSRAM | (((uintptr_t)page - RAM_START) / PAGE_SIZE) : INVALID; }

static int instruction_invalidate(unsigned page)
{
    unsigned line = (REG32(IC_CTRL) & 8u) ? 32u : 16u;
    if (REG32(IC_SYNC) & 1u) return 0;
    register_write(IC_ADDR, CODE_ADDRESS + page * PAGE_SIZE);
    register_write(IC_SIZE, (REG32(IC_SIZE) & UINT32_C(0xff800000)) |
                   PAGE_SIZE / line);
    register_write(IC_SYNC, REG32(IC_SYNC) | 1u);
    if (!wait_bits(IC_SYNC, 3u, 2u)) return 0;
    __asm__ volatile("isync" ::: "memory");
    return 1;
}

static int autoload_suspend(uint32_t reg, uint32_t saved)
{
    if (!(saved & 4u)) return 1;
    register_write(reg, saved & ~4u);
    register_write(reg, REG32(reg) | 512u);
    if (!wait_bits(reg, 8u, 8u)) return 0;
    register_write(reg, REG32(reg) & ~512u);
    return 1;
}

static int window_switch(struct mmu_window *w, struct mmu_memory *next)
{
    uint32_t ps, prid, c0, c1, da, ia, daddr, dsize, iaddr, isize, start;
    unsigned mode, line, p;
    int failed = 1;
    w->stage = 1;
    __asm__ volatile("rsr %0, prid" : "=a"(prid));
    if (((prid >> 13) & 1u) != 1u || w->fatal) return 1;
    __asm__ volatile("rsil %0, 15" : "=a"(ps) :: "memory");
    start = cycles_now();
    c0 = REG32(RTC_OPTIONS) & STALL_C0_MASK;
    c1 = REG32(RTC_STALL) & STALL_C1_MASK;
    if (c0 || c1) goto irq;
    register_write(RTC_OPTIONS, (REG32(RTC_OPTIONS) & ~STALL_C0_MASK) | (2u << 2));
    register_write(RTC_STALL, (REG32(RTC_STALL) & ~STALL_C1_MASK) | (0x21u << 26));
    __asm__ volatile("rsync\n nop\n nop\n nop\n nop" ::: "memory");
    w->stage = 2;
    mode = (REG32(DC_CTRL) >> 3) & 3u;
    if (!(REG32(DC_CTRL) & 1u) || !(REG32(IC_CTRL) & 1u) || mode > 2 ||
        (REG32(DC_SYNC) & 7u) || (REG32(IC_SYNC) & 1u) ||
        (REG32(0x600c400c) & 3u) || (REG32(0x600c406c) & 3u)) goto core;
    for (p = 0; p < WINDOW_PAGES; ++p) {
        void *oldpage = w->active ? w->active->pages[p] : NULL;
        void *newpage = next ? next->pages[p] : NULL;
        if (REG32(MMU_TABLE + 4 * (ALIAS_SLOT + p)) != page_entry(oldpage)) goto core;
        if (newpage && REG32(MMU_TABLE + 4 * (((uintptr_t)newpage - DATA_BASE) / PAGE_SIZE))
                       != page_entry(newpage)) goto core;
    }
    line = 16u << mode;
    da = REG32(DC_AUTO); ia = REG32(IC_AUTO);
    daddr = REG32(DC_ADDR); dsize = REG32(DC_SIZE);
    iaddr = REG32(IC_ADDR); isize = REG32(IC_SIZE);
    w->stage = 3;
    if (!autoload_suspend(DC_AUTO, da) || !autoload_suspend(IC_AUTO, ia)) goto fatal;
    w->stage = 4;
    for (p = 0; p < WINDOW_PAGES; ++p) {
        uint32_t alias = ALIAS_ADDRESS + p * PAGE_SIZE;
        void *oldpage = w->active ? w->active->pages[p] : NULL;
        void *newpage = next ? next->pages[p] : NULL;
        if (!oldpage && !newpage) continue;
        if (oldpage && !cache_operation(alias, line, 2u)) goto fatal;
        if (!cache_operation(alias, line, 1u) || !instruction_invalidate(p)) goto fatal;
        if (newpage && (!cache_operation((uintptr_t)newpage, line, 2u) ||
                        !cache_operation((uintptr_t)newpage, line, 1u))) goto fatal;
    }
    w->stage = 5;
    for (p = 0; p < WINDOW_PAGES; ++p)
        register_write(MMU_TABLE + 4 * (ALIAS_SLOT + p), page_entry(next ? next->pages[p] : NULL));
    w->active = next;
    for (p = 0; p < WINDOW_PAGES; ++p)
        if (next && next->pages[p] &&
            (!cache_operation(ALIAS_ADDRESS + p * PAGE_SIZE, line, 1u) ||
             !instruction_invalidate(p))) goto fatal;
    w->stage = 6;
    failed = 0;
    goto caches;
fatal:
    w->fatal = 1;
caches:
    if (!(REG32(DC_SYNC) & 7u)) {
        register_write(DC_ADDR, daddr); register_write(DC_SIZE, dsize);
    }
    if (!(REG32(IC_SYNC) & 1u)) {
        register_write(IC_ADDR, iaddr); register_write(IC_SIZE, isize);
    }
    register_write(DC_AUTO, da); register_write(IC_AUTO, ia);
core:
    register_write(RTC_STALL, (REG32(RTC_STALL) & ~STALL_C1_MASK) | c1);
    register_write(RTC_OPTIONS, (REG32(RTC_OPTIONS) & ~STALL_C0_MASK) | c0);
irq:
    w->cycles = cycles_now() - start;
    __asm__ volatile("wsr %0, ps\n rsync\n isync" :: "a"(ps) : "memory");
    return failed;
}
#endif
