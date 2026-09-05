#include <stdint.h>
uint32_t mmu_main(uint32_t n)
{
    (void)n;
    for (;;) __asm__ volatile("nop");
}
