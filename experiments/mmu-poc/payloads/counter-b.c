#include <stdint.h>
static volatile uint32_t counter = 1000;
uint32_t mmu_main(uint32_t add)
{ counter += 2 * add; return counter; }
