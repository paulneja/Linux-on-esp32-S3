/* Include the implementation to exercise the identical private dispatcher. */
#include "mmu-services.c"
#include <assert.h>
int main(void)
{
    struct mmu_api api;
    char path[] = "/tmp/mmu-services-XXXXXX", data[16] = {0};
    intptr_t h, pointer;
    int temporary = mkstemp(path);
    assert(temporary >= 0); close(temporary); assert(!unlink(path));
    services_init(&api, 0, NULL);
    assert(host_call(999, 0, 0, 0) == -ENOSYS);
    assert(host_call(MMU_OPEN, (uintptr_t)"/tmp/../etc/test", 1, 0) == -EPERM);
    assert(host_call(MMU_OPEN, (uintptr_t)"/tmp/mmu-dir/file", 1, 0) == -EPERM);
    assert(host_call(MMU_OPEN, (uintptr_t)"/dev/zero", 0, 0) == -EINVAL);
    h = host_call(MMU_OPEN, (uintptr_t)path, 1, 0); assert(h >= 3);
    assert(host_call(MMU_WRITE, h, (uintptr_t)"hello\n", 6) == 6);
    assert(host_call(MMU_CLOSE, h, 0, 0) == 0);
    assert(host_call(MMU_CLOSE, h, 0, 0) == -EBADF);
    assert(host_call(MMU_OPEN, (uintptr_t)path, 1, 0) == -EEXIST);
    h = host_call(MMU_OPEN, (uintptr_t)path, 0, 0); assert(h >= 3);
    assert(host_call(MMU_READ, h, (uintptr_t)data, sizeof(data)) == 6);
    assert(!strcmp(data, "hello\n"));
    assert(host_call(MMU_READ, h, (uintptr_t)data, 4097) == -EINVAL);
    assert(host_call(MMU_READ, 100, (uintptr_t)data, 1) == -EBADF);
    pointer = host_call(MMU_ALLOC, HEAP_LIMIT, 0, 0); assert(pointer);
    assert(!host_call(MMU_ALLOC, 1, 0, 0));
    assert(host_call(MMU_FREE, pointer + 1, 0, 0) == -EINVAL);
    assert(!host_call(MMU_FREE, pointer, 0, 0));
    assert(host_call(MMU_FREE, pointer, 0, 0) == -EINVAL);
    assert(host_call(MMU_ALLOC, 4096, 0, 0));
    services_cleanup(); /* Deliberately retain a file and allocation above. */
    assert(heap_used == 0 && files[h - 3] == -1);
    assert(!unlink(path));
    puts("PASS: services IO, write policy, heap bounds and resource cleanup");
    return 0;
}
