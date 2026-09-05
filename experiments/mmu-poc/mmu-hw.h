#ifndef MMU_HW_H
#define MMU_HW_H
#include "mmu-layout.h"
#define REG32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define DC_CTRL UINT32_C(0x600c4000)
#define DC_SYNC UINT32_C(0x600c4028)
#define DC_ADDR UINT32_C(0x600c402c)
#define DC_SIZE UINT32_C(0x600c4030)
#define DC_AUTO UINT32_C(0x600c404c)
#define IC_CTRL UINT32_C(0x600c4060)
#define IC_SYNC UINT32_C(0x600c4088)
#define IC_ADDR UINT32_C(0x600c408c)
#define IC_SIZE UINT32_C(0x600c4090)
#define IC_AUTO UINT32_C(0x600c40a0)
#define RTC_OPTIONS UINT32_C(0x60008000)
#define RTC_STALL UINT32_C(0x600080bc)
#define STALL_C0_MASK UINT32_C(0x0000000c)
#define STALL_C1_MASK UINT32_C(0xfc000000)
#define CACHE_TIMEOUT UINT32_C(2400000)

static inline uint32_t cycles_now(void)
{
    uint32_t result;
    __asm__ volatile("rsr %0, ccount" : "=a"(result));
    return result;
}
static inline void register_write(uint32_t address, uint32_t value)
{
    REG32(address) = value;
    __asm__ volatile("memw" ::: "memory");
}
static int wait_bits(uint32_t address, uint32_t mask, uint32_t expected)
{
    uint32_t start = cycles_now();
    do {
        if ((REG32(address) & mask) == expected)
            return 1;
    } while ((uint32_t)(cycles_now() - start) < CACHE_TIMEOUT);
    return 0;
}
static int cache_operation(uint32_t address, unsigned line_size, unsigned op)
{
    if (REG32(DC_SYNC) & 7u)
        return 0;
    register_write(DC_ADDR, address);
    register_write(DC_SIZE, (REG32(DC_SIZE) & UINT32_C(0xff800000)) |
                   (PAGE_SIZE / line_size));
    register_write(DC_SYNC, REG32(DC_SYNC) | op);
    return wait_bits(DC_SYNC, 15u, 8u);
}
#endif
