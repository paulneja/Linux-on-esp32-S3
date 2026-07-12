/*
 * Copyright (c) 2023, Jisheng Zhang <jszhang@kernel.org>. All rights reserved.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "cache.h"
#include "psram.h"

#define CACHESIZE	4096
struct cacheline {
	uint8_t data[64];
};

static uint64_t accessed, hit;
static uint32_t tags[CACHESIZE/64/2][2];
static struct cacheline cachelines[CACHESIZE/64/2][2];

/*
 * bit[0]: valid
 * bit[1]: dirty
 * bit[2]: for LRU
 * bit[3:10]: reserved
 * bit[11:31]: tag
 */
#define VALID		(1 << 0)
#define DIRTY		(1 << 1)
#define LRU			(1 << 2)
#define LRU_SFT		2
#define TAG_MSK		0xfffff800

/*
 * bit[0: 5]: offset
 * bit[6: 10]: index
 * bit[11: 31]: tag
 */
static inline int get_index(uint32_t addr)
{
	return (addr >> 6) & 0x1f;
}


void cache_write(uint32_t ofs, void *buf, uint32_t size);
void cache_read(uint32_t ofs, void *buf, uint32_t size);

void cache_write(uint32_t ofs, void *buf, uint32_t size)
{

	if ((ofs & ~0x3f) != ((ofs + size - 1) & ~0x3f)) {
		uint32_t first = 64 - (ofs & 0x3f);
		cache_write(ofs, buf, first);
		cache_write((ofs + first), (uint8_t *)buf + first, size - first);
		return;
	}

	int ti = 0, i, index = get_index(ofs);
	uint32_t *tp = &tags[index][0];
	uint8_t *p = cachelines[index][0].data;

	++accessed;

	for (i = 0; i < 2; i++) {
		tp = &tags[index][i];
		p = cachelines[index][i].data;
		if (*tp & VALID) {
			if ((*tp & TAG_MSK) == (ofs & TAG_MSK)) {
				
				++hit;
				ti = i;
				break;
			} else {
				if (i != 1)
					continue;

				ti = 1 - ((*tp & LRU) >> LRU_SFT);
				tp = &tags[index][ti];
				p = cachelines[index][ti].data;

				if (*tp & DIRTY)
					psram_write(*tp & ~0x3f, p, 64);

				psram_read(ofs & ~0x3f, p, 64);
				*tp = ofs & ~0x3f;
				*tp |= VALID;
			}
		} else {
			if (i != 1)
				continue;


			ti = i;
			psram_read(ofs & ~0x3f, p, 64);
			*tp = ofs & ~0x3f;
			*tp |= VALID;
		}
	}


	tags[index][1] &= ~LRU;
	tags[index][1] |= (ti << LRU_SFT);

	tp = &tags[index][ti];
	p = cachelines[index][ti].data;
	memcpy(p + (ofs & 0x3f), buf, size);
	*tp |= DIRTY;
}

void cache_read(uint32_t ofs, void *buf, uint32_t size)
{
	if ((ofs & ~0x3f) != ((ofs + size - 1) & ~0x3f)) {
		uint32_t first = 64 - (ofs & 0x3f);
		cache_read(ofs, buf, first);
		cache_read((ofs + first), (uint8_t *)buf + first, size - first);
		return;
	}

	int ti = 0, i, index = get_index(ofs);
	uint32_t *tp = &tags[index][0];
	uint8_t *p = cachelines[index][0].data;

	++accessed;

	for (i = 0; i < 2; i++) {
		tp = &tags[index][i];
		p = cachelines[index][i].data;
		if (*tp & VALID) {
			if ((*tp & TAG_MSK) == (ofs & TAG_MSK)) {
				
				++hit;
				ti = i;
				break;
			} else {
				if (i != 1)
					continue;
				
				ti = 1 - ((*tp & LRU) >> LRU_SFT);
				tp = &tags[index][ti];
				p = cachelines[index][ti].data;

				if (*tp & DIRTY)
					psram_write(*tp & ~0x3f, p, 64);

				psram_read(ofs & ~0x3f, p, 64);
				*tp = ofs & ~0x3f;
				*tp |= VALID;
			}
		} else {
			if (i != 1)
				continue;

			ti = i;
			psram_read(ofs & ~0x3f, p, 64);
			*tp = ofs & ~0x3f;
			*tp |= VALID;
		}
	}

	tags[index][1] &= ~LRU;
	tags[index][1] |= (ti << LRU_SFT);


	p = cachelines[index][ti].data;
	memcpy(buf, p + (ofs & 0x3f), size);
}

void cache_get_stat(uint64_t *phit, uint64_t *paccessed)
{
	*phit = hit;
	*paccessed = accessed;
}
