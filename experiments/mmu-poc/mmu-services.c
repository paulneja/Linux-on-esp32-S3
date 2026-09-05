#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "mmu-services.h"
#define HANDLES 16u
#define ALLOCATIONS 32u
#define HEAP_LIMIT (128u * 1024u)
#define IO_LIMIT 4096u
static int files[HANDLES];
static struct { void *pointer; size_t size; } blocks[ALLOCATIONS];
static size_t heap_used;

static intptr_t dispatch(uintptr_t op, uintptr_t x, uintptr_t y, uintptr_t z)
{
    unsigned i;
    switch (op) {
    case MMU_OPEN: {
        const char *path = (const char *)x;
        struct stat st;
        int fd;
        if (!path || strnlen(path, 256) >= 256 || y > 1) return -EINVAL;
        /* Flash writes currently hang on this image. Only new, flat /tmp/mmu-*
         * files may be created. No traversal, overwrite or symlink following. */
        if (y && (strncmp(path, "/tmp/mmu-", 9) || !path[9] || strchr(path + 5, '/')))
            return -EPERM;
        for (i = 0; i < HANDLES && files[i] >= 0; ++i) {}
        if (i == HANDLES) return -EMFILE;
        fd = open(path, O_NOFOLLOW | O_NONBLOCK |
                  (y ? O_WRONLY | O_CREAT | O_EXCL : O_RDONLY), 0600);
        if (fd < 0) return -errno;
        if (fstat(fd, &st) || !S_ISREG(st.st_mode)) { close(fd); return -EINVAL; }
        files[i] = fd;
        return i + 3;
    }
    case MMU_READ:
    case MMU_WRITE: {
        ssize_t result;
        int fd;
        if (z > IO_LIMIT || (!y && z)) return -EINVAL;
        if (op == MMU_WRITE && (x == 1 || x == 2)) fd = (int)x;
        else if (x >= 3 && x < HANDLES + 3 && files[x - 3] >= 0) fd = files[x - 3];
        else return -EBADF;
        do {
            result = op == MMU_READ ? read(fd, (void *)y, z) : write(fd, (void *)y, z);
        } while (result < 0 && errno == EINTR);
        return result < 0 ? -errno : result;
    }
    case MMU_CLOSE:
        if (x < 3 || x >= HANDLES + 3 || files[x - 3] < 0) return -EBADF;
        i = close(files[x - 3]) ? errno : 0;
        files[x - 3] = -1;
        return -(intptr_t)i;
    case MMU_ALLOC:
        if (!x || x > HEAP_LIMIT - heap_used) return 0;
        for (i = 0; i < ALLOCATIONS && blocks[i].pointer; ++i) {}
        if (i == ALLOCATIONS) return 0;
        blocks[i].pointer = malloc(x);
        if (!blocks[i].pointer) return 0;
        blocks[i].size = x; heap_used += x;
        return (intptr_t)blocks[i].pointer;
    case MMU_FREE:
        if (!x) return 0;
        for (i = 0; i < ALLOCATIONS; ++i)
            if ((uintptr_t)blocks[i].pointer == x) {
                free(blocks[i].pointer); blocks[i].pointer = NULL;
                heap_used -= blocks[i].size; blocks[i].size = 0;
                return 0;
            }
        return -EINVAL;
    case MMU_CLOCK_MS: {
        struct timespec ts;
        if (clock_gettime(CLOCK_MONOTONIC, &ts)) return -errno;
        return (intptr_t)((uint32_t)ts.tv_sec * 1000u + (uint32_t)ts.tv_nsec / 1000000u);
    }
    default: return -ENOSYS;
    }
}
static intptr_t host_call(uintptr_t op, uintptr_t x, uintptr_t y, uintptr_t z)
{
    sigset_t all, previous;
    intptr_t result;
    /* Never longjmp out of malloc/free or while resource tracking is incomplete.
     * File handles are regular files only; per-call IO is bounded to 4 KiB.
     * Signals pending during a service are delivered after the tracking is safe.
     */
    sigfillset(&all);
    if (sigprocmask(SIG_BLOCK, &all, &previous)) return -errno;
    result = dispatch(op, x, y, z);
    if (sigprocmask(SIG_SETMASK, &previous, NULL)) return -errno;
    return result;
}
void services_init(struct mmu_api *api, unsigned argc, char **argv)
{
#ifdef __XTENSA__
    intptr_t (*function)(uintptr_t, uintptr_t, uintptr_t, uintptr_t) = host_call;
    const uintptr_t *descriptor = (const uintptr_t *)(void *)function;
#else
    const uintptr_t descriptor[2] = {0}; /* Host tests call host_call directly. */
#endif
    unsigned i;
    for (i = 0; i < HANDLES; ++i) files[i] = -1;
    *api = (struct mmu_api){MMU_API_VERSION, sizeof(*api), descriptor[0], descriptor[1],
                           argc, (const char *const *)argv};
}
void services_cleanup(void)
{
    unsigned i, closed = 0, freed = 0;
    size_t recovered = heap_used;
    for (i = 0; i < HANDLES; ++i) {
        if (files[i] >= 0) { close(files[i]); ++closed; }
        files[i] = -1;
    }
    for (i = 0; i < ALLOCATIONS; ++i) {
        if (blocks[i].pointer) ++freed;
        free(blocks[i].pointer); blocks[i].pointer = NULL; blocks[i].size = 0;
    }
    heap_used = 0;
    if (closed || freed)
        printf("Resources recovered: files=%u allocations=%u bytes=%lu\n",
               closed, freed, (unsigned long)recovered);
}
