/* Single-threaded fork entry for NOMMU uClibc, with bounded atfork callbacks.
 * The kernel still rejects fork from a multithreaded address space. This does
 * not repair arbitrary pthread locks or support unloading callback DSOs. */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#define FORK_CALLBACKS 32
struct fork_callbacks {
    void (*prepare)(void);
    void (*parent)(void);
    void (*child)(void);
};
static struct fork_callbacks callbacks[FORK_CALLBACKS];
static unsigned callback_count;
static pthread_mutex_t callback_lock = PTHREAD_MUTEX_INITIALIZER;

int __register_atfork(void (*prepare)(void), void (*parent)(void),
                      void (*child)(void), void *dso_handle)
{
    (void)dso_handle;
    int error = pthread_mutex_lock(&callback_lock);
    if (error) return error;
    if (callback_count == FORK_CALLBACKS) {
        pthread_mutex_unlock(&callback_lock);
        return ENOMEM;
    }
    callbacks[callback_count++] = (struct fork_callbacks){prepare, parent, child};
    pthread_mutex_unlock(&callback_lock);
    return 0;
}

int pthread_atfork(void (*prepare)(void), void (*parent)(void), void (*child)(void))
{
    return __register_atfork(prepare, parent, child, NULL);
}

pid_t fork(void)
{
    struct fork_callbacks active[FORK_CALLBACKS];
    int error = pthread_mutex_lock(&callback_lock);
    if (error) { errno = error; return -1; }
    unsigned count = callback_count;
    for (unsigned i = 0; i < count; i++) active[i] = callbacks[i];
    pthread_mutex_unlock(&callback_lock);
    for (unsigned i = count; i > 0; i--)
        if (active[i - 1].prepare) active[i - 1].prepare();

    pid_t pid = (pid_t)syscall(SYS_clone, (unsigned long)SIGCHLD,
                             0UL, 0UL, 0UL, 0UL);
    int saved_errno = errno;
    for (unsigned i = 0; i < count; i++) {
        void (*callback)(void) = pid == 0 ? active[i].child : active[i].parent;
        if (callback) callback();
    }
    errno = saved_errno;
    return pid;
}
