#include <stdint.h>
/* Iterative Fibonacci, explicitly bounded to the uint32_t range. */
uint32_t mmu_main(uint32_t n)
{
    uint32_t a = 0, b = 1;
    if (n > 47) return UINT32_MAX;
    while (n--) { uint32_t next = a + b; a = b; b = next; }
    return a;
}
