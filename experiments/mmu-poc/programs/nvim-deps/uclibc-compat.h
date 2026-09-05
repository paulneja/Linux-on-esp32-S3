/* Build the genuine uClibc Netlink implementation outside libc. */
#include <features.h>
#include <errno.h>
#include <sys/types.h>
extern pid_t fork(void);
extern int login_tty(int fd);
#define libutil_hidden_def(name)
#define __ASSUME_NETLINK_SUPPORT 1
#define __UCLIBC_SUPPORT_AI_ADDRCONFIG__ 1
#define __MAX_ALLOCA_CUTOFF 4096
#define PAGE_SIZE 4096
#define internal_function
#define __libc_use_alloca(size) 0
#define extend_alloca(buffer, length, new_length) \
    ((length) = (new_length), __builtin_alloca(length))
#ifndef __attribute_noinline__
#define __attribute_noinline__ __attribute__((noinline))
#endif
#ifndef attribute_hidden
#define attribute_hidden __attribute__((visibility("hidden")))
#endif
#ifndef __set_errno
#define __set_errno(value) (errno = (value))
#endif
#ifndef libc_hidden_def
#define libc_hidden_def(name)
#endif
#ifndef libc_hidden_proto
#define libc_hidden_proto(name)
#endif
