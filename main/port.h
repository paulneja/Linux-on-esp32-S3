/*
 * Copyright (c) 2023, Jisheng Zhang <jszhang@kernel.org>. All rights reserved.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef PORT_H
#define PORT_H

#include <stdint.h>

uint64_t GetTimeMicroseconds();
int IsKBHit();
int ReadKBByte();
int load_images(int ram_size, int *kern_len);

/* XIP: memory-map the "rootfs" flash partition (romfs) into CPU address space.
 * Returns a read-only pointer to the mapped flash, or NULL on failure. */
const uint8_t *rootfs_mmap(void);
#endif /* PORT_H */
