#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "output_common/line_queue.h"
void epd_apply_line_mask_VE(uint8_t* line,const uint8_t* mask,int len) {
    for(int i=0;i<len;i++)line[i]&=mask[i];
}
static void test_size(int size) {
    LineQueue_t q=lq_init(size,300,true);uint8_t out[300];
    memset(q.mask_buffer,0x0f,q.mask_buffer_len);
    assert(lq_read(&q,out)==-1);
    for(int i=0;i<size-1;i++) {uint8_t* p=lq_current(&q);assert(p);memset(p,0xa5,300);lq_commit(&q);}
    assert(!lq_current(&q));
    // Start at size-1 prepared rows, before another enqueue would block.
    for(int i=0;i<8;i++){assert(lq_read(&q,out)==0);for(int x=0;x<300;x++)assert(out[x]==5);}
    for(int i=0;i<10000;i++) {
        assert(lq_current(&q));memset(lq_current(&q),0xaa,300);lq_commit(&q);assert(lq_read(&q,out)==0);
    }
    lq_reset(&q);assert(lq_read(&q,out)==-1);lq_free(&q);
}

static void test_prebuffered(void) {
    LineQueue_t q=lq_init(64,300,true);uint8_t out[300];
    memset(q.mask_buffer,0xff,q.mask_buffer_len);
    // Producer finishes before the consumer starts; sparse rows span the panel.
    for(int phase=0;phase<5;phase++) {
        for(int i=0;i<48;i++) {uint8_t* p=lq_current(&q);assert(p);memset(p,i+phase,300);lq_commit(&q);}
        int consumed=0;
        for(int y=0;y<832;y++) {
            if(y%17 || consumed==48) continue;
            assert(lq_read(&q,out)==0);
            for(int x=0;x<300;x++)assert(out[x]==consumed+phase);
            consumed++;
        }
        assert(consumed==48);assert(lq_read(&q,out)==-1);
    }
    lq_free(&q);
}

int main(void) {test_size(32);test_size(64);test_prebuffered();puts("32/64-row line queue tests passed");}
