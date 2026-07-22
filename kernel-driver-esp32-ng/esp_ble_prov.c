// SPDX-License-Identifier: GPL-2.0-only
/*
 * BLE provisioning pipe for Linux-on-ESP32-S3.
 *
 * Exposes /dev/esp-ble, a plain byte pipe between userspace and the BLE
 * (Nordic UART Service) link that the ESP32 firmware runs on core 0. A phone
 * connects over BLE, and whatever it types arrives here; whatever userspace
 * writes here goes back to the phone.
 *
 * The point is joining the board to a WiFi network with no PC and no serial
 * cable: a small daemon reads this device, runs the same scan/pick/password
 * dialog as the `wifi` command, and connects. The dialog lives in userspace
 * (not in the firmware) because Linux is what owns the WiFi connection --
 * having the firmware join on its own would desynchronise the driver state.
 *
 * Transport: packets tagged ESP_BLE_PROV_IF over the existing shmem link, so
 * this rides the multiplexing that is already there rather than adding a
 * second channel.
 */

#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/poll.h>
#include <linux/uaccess.h>
#include <linux/skbuff.h>
#include <linux/sched.h>

#include "esp.h"
#include "utils.h"
#include "esp_api.h"

#define ESP_BLE_PROV_DEV_NAME	"esp-ble"
#define ESP_BLE_PROV_MAX_WRITE	512
/* Bound the backlog: a phone that spams while nothing reads must not be able
 * to exhaust memory on an 8MB board. */
#define ESP_BLE_PROV_MAX_QUEUE	32

static struct esp_adapter *ble_adapter;
static struct sk_buff_head rx_q;
static wait_queue_head_t rx_wait;
static atomic_t is_open = ATOMIC_INIT(0);

/* --- called from the driver RX path (firmware -> us) --------------------- */
void esp_ble_prov_rx(struct sk_buff *skb)
{
	if (!skb)
		return;

	/* Nobody listening, or backlog full: drop rather than grow. */
	if (!atomic_read(&is_open) ||
	    skb_queue_len(&rx_q) >= ESP_BLE_PROV_MAX_QUEUE) {
		dev_kfree_skb_any(skb);
		return;
	}

	skb_queue_tail(&rx_q, skb);
	wake_up_interruptible(&rx_wait);
}

/* --- file operations ----------------------------------------------------- */
static int esp_ble_prov_open(struct inode *inode, struct file *file)
{
	/* Single reader: this is a provisioning console, not a shared bus. */
	if (atomic_xchg(&is_open, 1))
		return -EBUSY;

	skb_queue_purge(&rx_q);
	return 0;
}

static int esp_ble_prov_release(struct inode *inode, struct file *file)
{
	atomic_set(&is_open, 0);
	skb_queue_purge(&rx_q);
	return 0;
}

static ssize_t esp_ble_prov_read(struct file *file, char __user *buf,
				 size_t count, loff_t *ppos)
{
	struct sk_buff *skb;
	size_t len;
	int ret;

	skb = skb_dequeue(&rx_q);
	while (!skb) {
		if (file->f_flags & O_NONBLOCK)
			return -EAGAIN;

		ret = wait_event_interruptible(rx_wait,
					       !skb_queue_empty(&rx_q));
		if (ret)
			return ret;

		skb = skb_dequeue(&rx_q);
	}

	len = min(count, (size_t)skb->len);
	if (copy_to_user(buf, skb->data, len)) {
		dev_kfree_skb_any(skb);
		return -EFAULT;
	}

	/* Short read: keep the remainder queued instead of losing it. */
	if (len < skb->len) {
		skb_pull(skb, len);
		skb_queue_head(&rx_q, skb);
	} else {
		dev_kfree_skb_any(skb);
	}

	return len;
}

static ssize_t esp_ble_prov_write(struct file *file, const char __user *buf,
				  size_t count, loff_t *ppos)
{
	struct esp_payload_header *hdr;
	struct sk_buff *skb;
	u16 pad_len, total_len;
	u8 *pos;
	int ret;

	if (!ble_adapter)
		return -ENODEV;
	if (!count)
		return 0;
	if (count > ESP_BLE_PROV_MAX_WRITE)
		count = ESP_BLE_PROV_MAX_WRITE;

	/* Same framing the other interfaces use: header first, payload
	 * aligned after it. */
	pad_len = sizeof(struct esp_payload_header);
	total_len = count + pad_len;
	pad_len += SKB_DATA_ADDR_ALIGNMENT - (total_len % SKB_DATA_ADDR_ALIGNMENT);

	skb = esp_alloc_skb(count + pad_len);
	if (!skb)
		return -ENOMEM;

	skb_put(skb, count + pad_len);
	pos = skb->data;

	hdr = (struct esp_payload_header *)pos;
	memset(hdr, 0, sizeof(*hdr));
	hdr->if_type = ESP_BLE_PROV_IF;
	hdr->if_num = 0;
	hdr->len = cpu_to_le16(count);
	hdr->offset = cpu_to_le16(pad_len);

	if (copy_from_user(pos + pad_len, buf, count)) {
		dev_kfree_skb_any(skb);
		return -EFAULT;
	}

	if (ble_adapter->capabilities & ESP_CHECKSUM_ENABLED)
		hdr->checksum = cpu_to_le16(compute_checksum(skb->data,
							     count + pad_len));

	ret = esp_send_packet(ble_adapter, skb);
	if (ret)
		return ret;

	return count;
}

static __poll_t esp_ble_prov_poll(struct file *file, poll_table *wait)
{
	__poll_t mask = EPOLLOUT | EPOLLWRNORM;

	poll_wait(file, &rx_wait, wait);
	if (!skb_queue_empty(&rx_q))
		mask |= EPOLLIN | EPOLLRDNORM;

	return mask;
}

static const struct file_operations esp_ble_prov_fops = {
	.owner		= THIS_MODULE,
	.open		= esp_ble_prov_open,
	.release	= esp_ble_prov_release,
	.read		= esp_ble_prov_read,
	.write		= esp_ble_prov_write,
	.poll		= esp_ble_prov_poll,
	.llseek		= no_llseek,
};

static struct miscdevice esp_ble_prov_misc = {
	.minor	= MISC_DYNAMIC_MINOR,
	.name	= ESP_BLE_PROV_DEV_NAME,
	.fops	= &esp_ble_prov_fops,
	.mode	= 0600,
};

/* --- setup / teardown ---------------------------------------------------- */
int esp_ble_prov_init(struct esp_adapter *adapter)
{
	int ret;

	ble_adapter = adapter;
	skb_queue_head_init(&rx_q);
	init_waitqueue_head(&rx_wait);

	ret = misc_register(&esp_ble_prov_misc);
	if (ret) {
		esp_err("Failed to register /dev/%s: %d\n",
			ESP_BLE_PROV_DEV_NAME, ret);
		ble_adapter = NULL;
		return ret;
	}

	esp_info("BLE provisioning pipe at /dev/%s\n", ESP_BLE_PROV_DEV_NAME);
	return 0;
}

void esp_ble_prov_deinit(void)
{
	if (!ble_adapter)
		return;

	misc_deregister(&esp_ble_prov_misc);
	skb_queue_purge(&rx_q);
	ble_adapter = NULL;
}
