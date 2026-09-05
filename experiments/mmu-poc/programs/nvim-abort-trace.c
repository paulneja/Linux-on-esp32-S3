#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
extern void __real_abort(void) __attribute__((noreturn));
void __wrap_abort(void) __attribute__((noreturn));
void __wrap_abort(void) {
    void *caller = __builtin_return_address(0);
    Dl_info info = {0};
    int error = errno;
    dladdr(caller, &info);
    fprintf(stderr, "NVIM ABORT caller=%p symbol=%s base=%p errno=%d\n", caller,
            info.dli_sname ? info.dli_sname : "?", info.dli_fbase, error);
    __real_abort();
}
