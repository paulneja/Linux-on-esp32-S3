#pragma once
#include <stdlib.h>
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
static inline void* heap_caps_aligned_alloc(size_t align,size_t size,int caps) {
    (void)caps;return aligned_alloc(align,(size+align-1)/align*align);
}
#define heap_caps_free free
