#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define PB_COLS 75
#define PB_ROWS 34
#define PB_WIDTH 1200
#define PB_HEIGHT 825
#ifdef __cplusplus
extern "C" {
#endif
typedef struct { uint8_t ch, inverse; } PbCell;
typedef struct {
    PbCell cells[PB_ROWS][PB_COLS];
    unsigned x, y, saved_x, saved_y, state, nparam, params[8];
    bool inverse, wrap_pending, cursor_visible, private_seq;
} PbTerminal;
void pb_init(PbTerminal* t);
void pb_feed(PbTerminal* t, const uint8_t* data, size_t len);
// Callback generates one differential row: target in high nibble, previous low.
typedef struct { const PbTerminal *next, *shown; } PbRaster;
void pb_raster_line(void* context, int y, uint8_t* out);
void pb_dirty_lines(const PbRaster* r, bool dirty[PB_HEIGHT]);
#ifdef __cplusplus
}
#endif
