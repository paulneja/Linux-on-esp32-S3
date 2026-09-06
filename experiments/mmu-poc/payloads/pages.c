#include <stdint.h>
static volatile unsigned char memory[160 * 1024];
extern uint32_t high_function(uint32_t);
uint32_t mmu_main(uint32_t argument)
{
    uint32_t i, sum = 0;
    for (i = 0; i < sizeof(memory); ++i) {
        if (memory[i]) return UINT32_MAX;
        memory[i] = (unsigned char)(i ^ argument);
    }
    for (i = 0; i < sizeof(memory); ++i) sum += memory[i];
    return sum + high_function(argument);
}
