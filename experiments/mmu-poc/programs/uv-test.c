#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <uv.h>
static int child_ok, timer_ok;
static void child_exit(uv_process_t *process, int64_t status, int signal) {
    child_ok = status == 7 && signal == 0;
    uv_close((uv_handle_t *)process, NULL);
}
static void tick(uv_timer_t *timer) {
    timer_ok = 1;
    uv_close((uv_handle_t *)timer, NULL);
}
int main(void) {
    uv_loop_t loop;
    fprintf(stderr, "uv: initializing loop\n");
    int error = uv_loop_init(&loop);
    if (error) { fprintf(stderr, "loop: %s\n", uv_strerror(error)); return 1; }
    puts("PASS uv: loop initialized");
    uv_interface_address_t *addresses;
    int count;
    error = uv_interface_addresses(&addresses, &count);
    if (error) { fprintf(stderr, "interfaces: %s\n", uv_strerror(error)); return 2; }
    for (int i = 0; i < count; i++) printf("interface: %s\n", addresses[i].name);
    uv_free_interface_addresses(addresses, count);
    if (!count) return 3;
    puts("PASS uv: real Netlink interface enumeration");
    uv_timer_t timer;
    if (uv_timer_init(&loop, &timer) || uv_timer_start(&timer, tick, 10, 0)) return 4;
    uv_process_t child;
    char *args[] = {"/usr/bin/dash", "-c", "exit 7", NULL};
    uv_process_options_t options = {0};
    options.exit_cb = child_exit;
    options.file = args[0];
    options.args = args;
    error = uv_spawn(&loop, &child, &options);
    if (error) { fprintf(stderr, "spawn: %s\n", uv_strerror(error)); return 5; }
    uv_run(&loop, UV_RUN_DEFAULT);
    if (!timer_ok || !child_ok || uv_loop_close(&loop)) return 6;
    puts("PASS uv: timer, spawn, child exit status and loop teardown");
    return 0;
}
