#ifndef MMU_API_H
#define MMU_API_H
#include <stdint.h>
#include <stddef.h>
#define MMU_API_VERSION 1u
enum mmu_operation { MMU_WRITE = 1, MMU_READ, MMU_OPEN, MMU_CLOSE,
                     MMU_ALLOC, MMU_FREE, MMU_CLOCK_MS };
struct mmu_api {
    uint32_t version, size;
    uintptr_t entry, got; /* Host CALL0/FDPIC descriptor, consumed by call.S. */
    uint32_t argc;
    const char *const *argv;
};
/* Results: nonnegative success, negative errno; ALLOC returns NULL on failure. */
intptr_t mmu_call(const struct mmu_api *, uintptr_t, uintptr_t, uintptr_t, uintptr_t);
static inline intptr_t mmu_write(const struct mmu_api *a, unsigned fd, const void *p, size_t n)
{ return mmu_call(a, MMU_WRITE, fd, (uintptr_t)p, n); }
static inline intptr_t mmu_read(const struct mmu_api *a, unsigned fd, void *p, size_t n)
{ return mmu_call(a, MMU_READ, fd, (uintptr_t)p, n); }
static inline intptr_t mmu_open(const struct mmu_api *a, const char *path, int create)
{ return mmu_call(a, MMU_OPEN, (uintptr_t)path, create, 0); }
static inline intptr_t mmu_close(const struct mmu_api *a, unsigned fd)
{ return mmu_call(a, MMU_CLOSE, fd, 0, 0); }
static inline void *mmu_alloc(const struct mmu_api *a, size_t n)
{ return (void *)mmu_call(a, MMU_ALLOC, n, 0, 0); }
static inline intptr_t mmu_free(const struct mmu_api *a, void *p)
{ return mmu_call(a, MMU_FREE, (uintptr_t)p, 0, 0); }
#endif
