#include <stdint.h>
#include <string.h>
#include "mmu-api.h"
#include "py/compile.h"
#include "py/runtime.h"
#include "py/gc.h"
#include "py/stackctrl.h"
#include "py/mphal.h"
#include "py/mperrno.h"
#define GC_HEAP (96u * 1024u)
#define SCRIPT_LIMIT (16u * 1024u)
static const struct mmu_api *host;

mp_uint_t mp_hal_ticks_ms(void)
{ return (mp_uint_t)mmu_call(host, MMU_CLOCK_MS, 0, 0, 0); }
mp_uint_t mp_hal_stdout_tx_strn(const char *text, size_t size)
{
    size_t total = 0;
    while (size) {
        size_t chunk = size > 4096 ? 4096 : size;
        intptr_t written = mmu_write(host, 1, text, chunk);
        if (written <= 0) break;
        total += written; text += written; size -= written;
    }
    return total;
}
static mp_obj_t file_read(mp_obj_t path_object)
{
    const char *path = mp_obj_str_get_str(path_object);
    intptr_t fd = mmu_open(host, path, 0);
    nlr_buf_t nlr;
    vstr_t value;
    if (fd < 0) mp_raise_OSError((mp_int_t)-fd);
    if (nlr_push(&nlr) == 0) {
        char buffer[512];
        intptr_t got;
        vstr_init(&value, 64);
        while ((got = mmu_read(host, (unsigned)fd, buffer, sizeof(buffer))) > 0) {
            if (value.len + got > SCRIPT_LIMIT) mp_raise_ValueError(MP_ERROR_TEXT("file exceeds 16 KiB"));
            vstr_add_strn(&value, buffer, (size_t)got);
        }
        if (got < 0) mp_raise_OSError((mp_int_t)-got);
        nlr_pop();
    } else {
        mmu_close(host, (unsigned)fd);
        nlr_raise(nlr.ret_val);
    }
    mmu_close(host, (unsigned)fd);
    return mp_obj_new_str_from_vstr(&value);
}
static MP_DEFINE_CONST_FUN_OBJ_1(file_read_obj, file_read);
static mp_obj_t file_write(mp_obj_t path_object, mp_obj_t content)
{
    const char *path = mp_obj_str_get_str(path_object);
    size_t size, written = 0;
    const char *data = mp_obj_str_get_data(content, &size);
    intptr_t fd;
    if (size > SCRIPT_LIMIT) mp_raise_ValueError(MP_ERROR_TEXT("file exceeds 16 KiB"));
    fd = mmu_open(host, path, 1);
    if (fd < 0) mp_raise_OSError((mp_int_t)-fd);
    while (written < size) {
        size_t chunk = size - written;
        intptr_t result;
        if (chunk > 4096) chunk = 4096;
        result = mmu_write(host, (unsigned)fd, data + written, chunk);
        if (result <= 0) {
            mmu_close(host, (unsigned)fd);
            mp_raise_OSError(result < 0 ? (mp_int_t)-result : MP_EIO);
        }
        written += result;
    }
    mmu_close(host, (unsigned)fd);
    return mp_obj_new_int_from_uint(written);
}
static MP_DEFINE_CONST_FUN_OBJ_2(file_write_obj, file_write);
static mp_obj_t clock_ms(void) { return mp_obj_new_int_from_uint(mp_hal_ticks_ms()); }
static MP_DEFINE_CONST_FUN_OBJ_0(clock_ms_obj, clock_ms);
static const mp_rom_map_elem_t module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_mmu)},
    {MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&file_read_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&file_write_obj)},
    {MP_ROM_QSTR(MP_QSTR_ticks_ms), MP_ROM_PTR(&clock_ms_obj)},
};
static MP_DEFINE_CONST_DICT(module_globals, module_globals_table);
const mp_obj_module_t mmu_module = {
    .base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&module_globals,
};
MP_REGISTER_MODULE(MP_QSTR_mmu, mmu_module);
void gc_collect(void)
{
    jmp_buf registers;
    uintptr_t sp, top = (uintptr_t)MP_STATE_THREAD(stack_top);
    (void)setjmp(registers);
    __asm__ volatile("mov %0, a1" : "=a"(sp));
    gc_collect_start();
    gc_collect_root((void **)registers, sizeof(registers) / sizeof(uintptr_t));
    if (sp <= top) gc_collect_root((void **)sp, (top - sp) / sizeof(uintptr_t));
    gc_collect_end();
}
void nlr_jump_fail(void *value)
{
    (void)value;
    mp_hal_stdout_tx_strn("Fatal MicroPython exception\n", 27);
    __asm__ volatile("ill");
    for (;;) {}
}
uint32_t mmu_main(uint32_t unused, const struct mmu_api *api)
{
    nlr_buf_t nlr;
    void *heap;
    char *owned_source = NULL;
    const char *source;
    size_t source_size;
    volatile uint32_t result = 0;
    (void)unused;
    if (!api || api->version != MMU_API_VERSION || api->size < sizeof(*api)) return 1;
    host = api;
    if (api->argc == 3 && !strcmp(api->argv[1], "-c")) {
        source = api->argv[2]; source_size = strlen(source);
        if (source_size > SCRIPT_LIMIT) return 2;
    } else if (api->argc == 2) {
        intptr_t fd = mmu_open(host, api->argv[1], 0), got;
        if (fd < 0) { mp_hal_stdout_tx_strn("Cannot open script\n", 19); return 1; }
        owned_source = mmu_alloc(host, SCRIPT_LIMIT + 1);
        if (!owned_source) return 1;
        source_size = 0;
        while (source_size < SCRIPT_LIMIT + 1) {
            size_t chunk = SCRIPT_LIMIT + 1 - source_size;
            if (chunk > 4096) chunk = 4096;
            got = mmu_read(host, (unsigned)fd, owned_source + source_size, chunk);
            if (got < 0) return 1;
            if (!got) break;
            source_size += got;
        }
        if (mmu_close(host, (unsigned)fd)) return 1;
        if (source_size > SCRIPT_LIMIT) return 2;
        owned_source[source_size] = 0; source = owned_source;
    } else {
        const char *usage = "MicroPython MMU: -c 'code' | script.py (16 KiB max)\n";
        mp_hal_stdout_tx_strn(usage, strlen(usage)); return 2;
    }
    heap = mmu_alloc(host, GC_HEAP);
    if (!heap) return 1;
    mp_stack_ctrl_init(); mp_stack_set_limit(40 * 1024);
    gc_init(heap, (unsigned char *)heap + GC_HEAP);
    mp_init();
    if (nlr_push(&nlr) == 0) {
        mp_lexer_t *lexer = mp_lexer_new_from_str_len(MP_QSTR__lt_stdin_gt_, source, source_size, 0);
        qstr name = lexer->source_name;
        mp_parse_tree_t tree = mp_parse(lexer, MP_PARSE_FILE_INPUT);
        mp_obj_t function = mp_compile(&tree, name, false);
        mp_call_function_0(function);
        nlr_pop();
    } else {
        mp_obj_print_exception(&mp_plat_print, (mp_obj_t)nlr.ret_val);
        result = 1;
    }
    mp_deinit();
    mmu_free(host, heap); mmu_free(host, owned_source);
    return result;
}
