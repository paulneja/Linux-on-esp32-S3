#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
extern pid_t fork(void);
static char order[8];
static unsigned position;
static void prep_a(void) { order[position++] = 'a'; }
static void prep_b(void) { order[position++] = 'b'; }
static void parent_a(void) { order[position++] = 'A'; }
static void parent_b(void) { order[position++] = 'B'; }
static void child_a(void) { order[position++] = '1'; }
static void child_b(void) { order[position++] = '2'; }
int main(void) {
    if (pthread_atfork(prep_a, parent_a, child_a) ||
        pthread_atfork(prep_b, parent_b, child_b)) return 1;
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 2; }
    if (pid == 0) _exit(strcmp(order, "ba12") ? 3 : 0);
    int status;
    if (waitpid(pid, &status, 0) != pid || status || strcmp(order, "baAB")) return 4;
    for (unsigned i = 2; i < 32; i++)
        if (pthread_atfork(NULL, NULL, NULL)) return 5;
    if (pthread_atfork(NULL, NULL, NULL) != ENOMEM) return 6;
    puts("PASS atfork: reverse prepare, forward parent/child, independent state, bounded registry");
    return 0;
}
