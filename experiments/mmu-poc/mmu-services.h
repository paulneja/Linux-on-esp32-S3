#ifndef MMU_SERVICES_H
#define MMU_SERVICES_H
#include "sdk/mmu-api.h"
void services_init(struct mmu_api *, unsigned argc, char **argv);
void services_cleanup(void);
#endif
