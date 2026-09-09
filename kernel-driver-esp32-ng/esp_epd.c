// SPDX-License-Identifier: GPL-2.0-only
// Text stream transport. This is not a framebuffer device.
#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/delay.h>
#include "esp.h"
#include "utils.h"
#include "esp_api.h"
#include "esp_if.h"
static DEFINE_MUTEX(epd_lock);
static struct esp_adapter *epd_adapter;
static bool registered;
static ssize_t epd_write(struct file *file,const char __user *data,size_t count,loff_t *pos)
{
    struct esp_payload_header *hdr;
    struct sk_buff *skb;
    size_t size;
    u16 pad;
    int ret;
    unsigned retries=0;
    if(!count)return 0;
    count=min_t(size_t,count,512);
    if(mutex_lock_interruptible(&epd_lock))return -ERESTARTSYS;
    if(!epd_adapter || !epd_adapter->if_ops || !epd_adapter->if_ops->write){ret=-ENODEV;goto done;}
    pad=sizeof(*hdr);
    pad+=SKB_DATA_ADDR_ALIGNMENT-((count+pad)%SKB_DATA_ADDR_ALIGNMENT);
    size=pad+count;
    skb=esp_alloc_skb(size);
    if(!skb){ret=-ENOMEM;goto done;}
    memset(skb_put(skb,size),0,size);
    hdr=(void*)skb->data;
    hdr->if_type=ESP_EPD_IF;
    hdr->len=cpu_to_le16(count);hdr->offset=cpu_to_le16(pad);
    if(copy_from_user(skb->data+pad,data,count)){
        dev_kfree_skb_any(skb);ret=-EFAULT;goto done;
    }
    if(epd_adapter->capabilities&ESP_CHECKSUM_ENABLED)
        hdr->checksum=cpu_to_le16(compute_checksum(skb->data,size));
    // The shmem backend consumes the passed reference even on queue-full.
    // Retain our own reference so backpressure retries do not lose text.
    for(;;) {
        ret=esp_send_packet(epd_adapter,skb_get(skb));
        if(ret!=-EBUSY)break;
        if(++retries==500){ret=-ETIMEDOUT;break;}
        if(msleep_interruptible(10)){ret=-ERESTARTSYS;break;}
    }
    dev_kfree_skb_any(skb);
    if(!ret)ret=count;
done:
    mutex_unlock(&epd_lock);return ret;
}
static const struct file_operations epd_ops={
    .owner=THIS_MODULE,.write=epd_write,.llseek=no_llseek,
};
static struct miscdevice epd_device={
    .minor=MISC_DYNAMIC_MINOR,.name="epd",.fops=&epd_ops,.mode=0600,
};
int esp_epd_init(struct esp_adapter *adapter)
{
    int ret;
    mutex_lock(&epd_lock);
    ret=misc_register(&epd_device);
    if(!ret){epd_adapter=adapter;registered=true;}
    mutex_unlock(&epd_lock);
    return ret;
}
void esp_epd_deinit(void)
{
    mutex_lock(&epd_lock);epd_adapter=NULL;mutex_unlock(&epd_lock);
    if(registered){misc_deregister(&epd_device);registered=false;}
}
