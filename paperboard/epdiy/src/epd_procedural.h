#pragma once
#include "epdiy.h"
#ifdef __cplusplus
extern "C" {
#endif
// Call on the same core that initialized epdiy, with exclusive renderer access.
// provider fills exactly epd_width() bytes, aligned by the renderer.
enum EpdDrawError epd_draw_procedural(
    void (*provider)(void*, int, uint8_t*), void* arg,
    const bool* dirty_lines, enum EpdDrawMode mode, int temperature);
#ifdef __cplusplus
}
#endif
