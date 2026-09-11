#include "terminal.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void send(PbTerminal* t,const char* s){pb_feed(t,(const uint8_t*)s,strlen(s));}
int main(void) {
    PbTerminal a,b; uint8_t line[PB_WIDTH+2]; bool dirty[PB_HEIGHT];
    pb_init(&a);send(&a,"abc\rZ");assert(a.cells[0][0].ch=='Z'&&a.cells[0][1].ch=='b');
    send(&a,"\033[34;75HQ!");assert(a.cells[32][74].ch=='Q'&&a.cells[33][0].ch=='!');
    send(&a,"\033[2J\033[H\033[7mA\033[0mB");
    assert(a.cells[0][0].inverse&& !a.cells[0][1].inverse);
    send(&a,"\033[1;2H\033[K");assert(a.cells[0][1].ch==' '&&a.cells[0][0].ch=='A');
    send(&a,"\033]0;hidden\007X");assert(a.cells[0][1].ch=='X');
    send(&a,"\033[999999999999999999;99999H");assert(a.x==74&&a.y==33);
    // Fragmented escape sequences produce identical results.
    pb_init(&a);pb_init(&b);
    const char* text="hello\033[2;3Hworld\033[7m!\033[0m\r\nnext\033[?25l";
    send(&a,text);for(size_t i=0;i<strlen(text);i++)pb_feed(&b,(const uint8_t*)text+i,1);
    assert(!memcmp(&a,&b,sizeof(a)));
    // Direction of differential bytes: white->black is 0x0f, black->white 0xf0.
    pb_init(&a);pb_init(&b);a.cursor_visible=b.cursor_visible=false;
    send(&a,"\033[7m ");PbRaster r={&a,&b};memset(line,0xa5,sizeof(line));
    pb_raster_line(&r,0,line+1);assert(line[0]==0xa5&&line[PB_WIDTH+1]==0xa5);
    for(int x=1;x<=16;x++)assert(line[x]==0x0f);
    r=(PbRaster){&b,&a};pb_raster_line(&r,0,line+1);for(int x=1;x<=16;x++)assert(line[x]==0xf0);
    pb_raster_line(&r,824,line+1);for(int x=1;x<=PB_WIDTH;x++)assert(line[x]==0xff);
    pb_dirty_lines(&r,dirty);assert(dirty[0]&&dirty[23]&&!dirty[24]&&!dirty[824]);
    // Arbitrary serial bytes cannot escape grid/parameter bounds (run with ASan/UBSan).
    unsigned seed=123;for(unsigned i=0;i<200000;i++) {
        seed=1664525*seed+1013904223;uint8_t ch=seed>>24;pb_feed(&a,&ch,1);
        assert(a.x<PB_COLS&&a.y<PB_ROWS&&a.nparam<8);
    }
    printf("terminal tests passed; two states: %zu bytes\n",2*sizeof(PbTerminal));
}
