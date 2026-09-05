#ifndef EXPERIMENTAL_FORK_DECL_H
#define EXPERIMENTAL_FORK_DECL_H
#include <sys/types.h>
/* The original NOMMU uClibc headers omit this declaration. */
extern pid_t fork(void);
#endif
