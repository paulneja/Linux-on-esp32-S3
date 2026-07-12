// ============================================================================
// psram.h - Updated for internal PSRAM
// ============================================================================
/*
 * Copyright (c) 2023, Jisheng Zhang <jszhang@kernel.org>. All rights reserved.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef PSRAM_H
#define PSRAM_H

#include <stdint.h>
#include <stddef.h>

int psram_init(void);
int psram_read(uint32_t addr, void *buf, int len);
int psram_write(uint32_t addr, void *buf, int len);

void *psram_get_base(void);
size_t psram_get_size(void);

#endif /* PSRAM_H */

