// ESP-IDF side of the Paperboard text console. All renderer work stays on core 0.
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include <stdio.h>
#include "epd_procedural.h"
#include "terminal.h"
static PbTerminal current,shown;
static bool dirty[PB_HEIGHT], batch[PB_HEIGHT];
static QueueHandle_t queue;
struct chunk { unsigned len; uint8_t bytes[128]; };
static void console_task(void* arg) {
    (void)arg;
    TickType_t last=xTaskGetTickCount();
    bool pending=true,failed=false;
    unsigned updates=0;
    for(;;) {
        struct chunk c;
        if(xQueueReceive(queue,&c,pdMS_TO_TICKS(20))==pdTRUE) {
            pb_feed(&current,c.bytes,c.len);pending=true;
        }
        if(!pending || failed || xTaskGetTickCount()-last<pdMS_TO_TICKS(500))continue;
        epd_poweron();
        if(updates && updates%100==0) {
            epd_clear();pb_init(&shown);shown.cursor_visible=false;
        }
        PbRaster r={&current,&shown};pb_dirty_lines(&r,dirty);
        enum EpdDrawError error=EPD_DRAW_SUCCESS;
        // At most 48 active rows fit entirely in the 64-slot internal ring.
        // Each batch completes all stock DU phases before advancing.
        unsigned count=0;
        memset(batch,0,sizeof(batch));
        for (int y=0;y<PB_HEIGHT;++y) {
            if (dirty[y]) {batch[y]=true;++count;}
            if (count==48 || (y==PB_HEIGHT-1 && count)) {
                error=epd_draw_procedural(pb_raster_line,&r,batch,MODE_DU,25);
                if (error) break;
                memset(batch,0,sizeof(batch));count=0;
            }
        }
        epd_poweroff();
        if(error) {
            ESP_LOGE("paperboard","draw failed 0x%x; display stopped until reboot",error);
            failed=true;
        } else {shown=current;++updates;}
        last=xTaskGetTickCount();pending=false;
    }
}
void pb_console_write(const uint8_t* data,size_t len) {
    if(!queue)return;
    while(len) {
        struct chunk c={.len=len>128?128:len};
        memcpy(c.bytes,data,c.len);
        xQueueSend(queue,&c,portMAX_DELAY);
        data+=c.len;len-=c.len;
    }
}
void pb_console_init(void) {
    // Must run on core 0 BEFORE linux_boot takes over core 1. No external-RAM malloc.
    configASSERT(xPortGetCoreID()==0);
    epd_init(&sverio_paperboard_v1,&ED097TC2,EPD_LUT_1K|EPD_FEED_QUEUE_32);
    epd_set_vcom(1500);epd_set_lcd_pixel_clock_MHz(5);
    printf("paperboard v3: core=%d clock=5MHz feed_rows=64 batch_rows=48 prebuffered=1 internal_free=%u\n",
           xPortGetCoreID(), (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    pb_init(&current);pb_init(&shown);shown.cursor_visible=false;
    epd_poweron();epd_clear();epd_poweroff();
    const char* banner="Paperboard / ED097TC2\r\nLinux console: run epd-shell over serial.\r\n\r\n";
    pb_feed(&current,(const uint8_t*)banner,strlen(banner));
    queue=xQueueCreate(8,sizeof(struct chunk));configASSERT(queue);
    configASSERT(xTaskCreatePinnedToCore(console_task,"paperboard",6144,NULL,2,NULL,0)==pdPASS);
}
