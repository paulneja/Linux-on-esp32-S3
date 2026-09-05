#include <stdint.h>
static volatile uint32_t counter = 100;
uint32_t mmu_main(uint32_t add)
{ counter += add; return counter; }
