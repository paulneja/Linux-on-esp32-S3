/* ESP32-S3-only laboratory backend. No ROM calls (Linux uses CALL0).
 * Register sequences follow ESP-IDF cpu.c and the S3 ROM cache item routines.
 * A transaction pauses core 0 and masks local interrupts; no libc in that interval.
 */
#ifndef MMU_REMAP_H
#define MMU_REMAP_H

#include "mmu-hw.h"

struct remap_result {
    unsigned switches;
    unsigned comparisons;
    uint32_t cycles;
    unsigned stage;
    int fatal;
};

/* 0 = clean success, 1 = safely restored failure; fatal means reset required.
 * The caller must retain its allocations on fatal cache failure.
 */
static int remap_pages(void **pages, struct remap_result *result)
{
    volatile uint32_t *alias = (volatile uint32_t *)(uintptr_t)ALIAS_ADDRESS;
    uint32_t ps, prid, saved_c0, saved_c1, saved_auto, saved_addr, saved_size;
    uint32_t start, entry[2];
    unsigned line_mode, line_size, p, i, phase;
    int failed = 1, mapped = 0, dirty = 0, suspended = 0;

    __asm__ volatile("rsr %0, prid" : "=a"(prid));
    if (((prid >> 13) & 1u) != 1u) {
        result->stage = 1;
        return 1; /* Never stall the core executing this code. */
    }
    for (p = 0; p < 2; ++p) {
        unsigned slot = ((uintptr_t)pages[p] - DATA_BASE) / PAGE_SIZE;
        entry[p] = REG32(MMU_TABLE + slot * 4u);
    }
    __asm__ volatile("rsil %0, 15" : "=a"(ps) :: "memory");
    start = cycles_now();
    saved_c0 = REG32(RTC_OPTIONS) & STALL_C0_MASK;
    saved_c1 = REG32(RTC_STALL) & STALL_C1_MASK;
    result->stage = 2;
    if (saved_c0 || saved_c1)
        goto restore_irq;
    register_write(RTC_OPTIONS, (REG32(RTC_OPTIONS) & ~STALL_C0_MASK) | (2u << 2));
    register_write(RTC_STALL, (REG32(RTC_STALL) & ~STALL_C1_MASK) | (0x21u << 26));
    __asm__ volatile("rsync\n nop\n nop\n nop\n nop" ::: "memory");

    saved_auto = REG32(DC_AUTO);
    saved_addr = REG32(DC_ADDR);
    saved_size = REG32(DC_SIZE);
    line_mode = (REG32(DC_CTRL) >> 3) & 3u;
    result->stage = 3;
    if (!(REG32(DC_CTRL) & 1u) || line_mode > 2 ||
        (REG32(DC_SYNC) & 7u) ||
        REG32(MMU_TABLE + ALIAS_SLOT * 4u) != INVALID ||
        (REG32(UINT32_C(0x600c400c)) & 3u))
        goto restore_core;
    line_size = 16u << line_mode;

    /* Suspend automatic prefetch around aligned writeback (S3 erratum). */
    result->stage = 4;
    if (saved_auto & 4u) {
        register_write(DC_AUTO, saved_auto & ~4u);
        register_write(DC_AUTO, REG32(DC_AUTO) | 512u);
        suspended = 1;
        if (!wait_bits(DC_AUTO, 8u, 8u))
            goto cleanup;
        register_write(DC_AUTO, REG32(DC_AUTO) & ~512u);
    }
    result->stage = 5;
    for (p = 0; p < 2; ++p) {
        if (!cache_operation((uintptr_t)pages[p], line_size, 2u) ||
            !cache_operation((uintptr_t)pages[p], line_size, 1u))
            goto cleanup;
    }
    if (!cache_operation(ALIAS_ADDRESS, line_size, 1u))
        goto cleanup;

    /* First A/B passes write owned pages. Later A/B passes verify persistence
     * through the SAME virtual address, comparing every 32-bit word. */
    for (phase = 0; phase < 4; ++phase) {
        p = phase & 1u;
        result->stage = 10 + phase;
        register_write(MMU_TABLE + ALIAS_SLOT * 4u, entry[p]);
        mapped = 1;
        ++result->switches;
        if (!cache_operation(ALIAS_ADDRESS, line_size, 1u))
            goto cleanup;
        for (i = 0; i < PAGE_SIZE / sizeof(*alias); ++i) {
            uint32_t expected = UINT32_C(0xa5000000) ^ (p << 20) ^ i;
            if (phase >= 2)
                expected ^= UINT32_C(0x00550000);
            if (alias[i] != expected)
                goto cleanup;
            ++result->comparisons;
        }
        if (phase < 2) {
            dirty = 1;
            for (i = 0; i < PAGE_SIZE / sizeof(*alias); ++i)
                alias[i] = UINT32_C(0xa5550000) ^ (p << 20) ^ i;
            if (!cache_operation(ALIAS_ADDRESS, line_size, 2u))
                goto cleanup;
            dirty = 0;
        }
        if (!cache_operation(ALIAS_ADDRESS, line_size, 1u))
            goto cleanup;
    }
    failed = 0;
cleanup:
    if (dirty && !cache_operation(ALIAS_ADDRESS, line_size, 2u)) {
        result->fatal = 1;
        failed = 1;
    }
    if (mapped && !result->fatal) {
        if (!cache_operation(ALIAS_ADDRESS, line_size, 1u)) {
            result->fatal = 1;
            failed = 1;
        } else {
            register_write(MMU_TABLE + ALIAS_SLOT * 4u, INVALID);
        }
    }
    if (!(REG32(DC_SYNC) & 7u)) {
        register_write(DC_ADDR, saved_addr);
        register_write(DC_SIZE, saved_size);
    } else {
        result->fatal = 1;
        failed = 1;
    }
    if (suspended)
        register_write(DC_AUTO, saved_auto);
restore_core:
    register_write(RTC_STALL, (REG32(RTC_STALL) & ~STALL_C1_MASK) | saved_c1);
    register_write(RTC_OPTIONS, (REG32(RTC_OPTIONS) & ~STALL_C0_MASK) | saved_c0);
restore_irq:
    result->cycles = cycles_now() - start;
    __asm__ volatile("wsr %0, ps\n rsync" :: "a"(ps) : "memory");
    return failed;
}
#endif
