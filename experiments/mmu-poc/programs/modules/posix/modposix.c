#include "py/runtime.h"
#include <errno.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>

extern pid_t fork(void);

static mp_obj_t posix_fork(void) {
    fflush(NULL);
    pid_t pid = fork();
    if (pid < 0) mp_raise_OSError(errno);
    return mp_obj_new_int(pid);
}
static MP_DEFINE_CONST_FUN_OBJ_0(posix_fork_obj, posix_fork);

static mp_obj_t posix_waitpid(mp_obj_t pid_in, mp_obj_t options_in) {
    int status = 0;
    pid_t pid;
    do {
        pid = waitpid(mp_obj_get_int(pid_in), &status, mp_obj_get_int(options_in));
    } while (pid < 0 && errno == EINTR);
    if (pid < 0) mp_raise_OSError(errno);
    mp_obj_t result[] = {mp_obj_new_int(pid), mp_obj_new_int(status)};
    return mp_obj_new_tuple(2, result);
}
static MP_DEFINE_CONST_FUN_OBJ_2(posix_waitpid_obj, posix_waitpid);

static mp_obj_t posix_pipe(void) {
    int fd[2];
    if (pipe(fd) < 0) mp_raise_OSError(errno);
    mp_obj_t result[] = {mp_obj_new_int(fd[0]), mp_obj_new_int(fd[1])};
    return mp_obj_new_tuple(2, result);
}
static MP_DEFINE_CONST_FUN_OBJ_0(posix_pipe_obj, posix_pipe);

static mp_obj_t posix_close(mp_obj_t fd_in) {
    if (close(mp_obj_get_int(fd_in)) < 0) mp_raise_OSError(errno);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(posix_close_obj, posix_close);

static mp_obj_t posix_write(mp_obj_t fd_in, mp_obj_t data_in) {
    mp_buffer_info_t buf;
    mp_get_buffer_raise(data_in, &buf, MP_BUFFER_READ);
    ssize_t count;
    do { count = write(mp_obj_get_int(fd_in), buf.buf, buf.len); }
    while (count < 0 && errno == EINTR);
    if (count < 0) mp_raise_OSError(errno);
    return mp_obj_new_int(count);
}
static MP_DEFINE_CONST_FUN_OBJ_2(posix_write_obj, posix_write);

static mp_obj_t posix_read(mp_obj_t fd_in, mp_obj_t size_in) {
    mp_int_t size = mp_obj_get_int(size_in);
    if (size < 0 || size > 4096) mp_raise_ValueError(MP_ERROR_TEXT("read size must be 0..4096"));
    vstr_t buf;
    vstr_init_len(&buf, size);
    ssize_t count;
    do { count = read(mp_obj_get_int(fd_in), buf.buf, size); }
    while (count < 0 && errno == EINTR);
    if (count < 0) {
        int error = errno;
        vstr_clear(&buf);
        mp_raise_OSError(error);
    }
    buf.len = count;
    return mp_obj_new_bytes_from_vstr(&buf);
}
static MP_DEFINE_CONST_FUN_OBJ_2(posix_read_obj, posix_read);

static mp_obj_t posix_exit(mp_obj_t code_in) {
    _exit(mp_obj_get_int(code_in));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(posix_exit_obj, posix_exit);

static const mp_rom_map_elem_t posix_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_posix)},
    {MP_ROM_QSTR(MP_QSTR_fork), MP_ROM_PTR(&posix_fork_obj)},
    {MP_ROM_QSTR(MP_QSTR_waitpid), MP_ROM_PTR(&posix_waitpid_obj)},
    {MP_ROM_QSTR(MP_QSTR_pipe), MP_ROM_PTR(&posix_pipe_obj)},
    {MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&posix_close_obj)},
    {MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&posix_read_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&posix_write_obj)},
    {MP_ROM_QSTR(MP_QSTR__exit), MP_ROM_PTR(&posix_exit_obj)},
    {MP_ROM_QSTR(MP_QSTR_WNOHANG), MP_ROM_INT(WNOHANG)},
};
static MP_DEFINE_CONST_DICT(posix_globals, posix_globals_table);
const mp_obj_module_t posix_module = {
    .base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&posix_globals,
};
MP_REGISTER_MODULE(MP_QSTR_posix, posix_module);
