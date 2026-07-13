/*
 * Copyright (c) 2023, Jisheng Zhang <jszhang@kernel.org>. All rights reserved.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <string.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_attr.h"
#include "esp_flash.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_partition.h"
#include "hal/uart_ll.h"
#include "psram.h"
#include "virtio.h"

/* Console I/O goes over UART0, which on this board is wired to the CH343
 * USB-serial bridge (/dev/ttyACM0). Poll the UART0 RX FIFO directly. */
#define CONSOLE_UART_HW UART_LL_GET_HW(0)

uint64_t GetTimeMicroseconds()
{
	return esp_timer_get_time();
}

int ReadKBByte(void)
{
	uint8_t rxchar;

	if (uart_ll_get_rxfifo_len(CONSOLE_UART_HW) == 0)
		return -1;

	uart_ll_read_rxfifo(CONSOLE_UART_HW, &rxchar, 1);
	return rxchar;
}

int IsKBHit(void)
{
	return uart_ll_get_rxfifo_len(CONSOLE_UART_HW) > 0;
}

static uint8_t *psram_base = NULL;
static size_t psram_size = 0;

int psram_init(void)
{
	size_t available_psram;
	size_t alloc_size;

	available_psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);

	if (available_psram == 0) {
		printf("ERROR: No PSRAM available!\n");
		printf("Check menuconfig: Component config -> ESP PSRAM\n");
		return -1;
	}

	size_t largest = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
	printf("PSRAM free: %zu bytes (%.2f MB), largest block: %zu (%.2f MB)\n",
		   available_psram, available_psram / (1024.0 * 1024.0),
		   largest, largest / (1024.0 * 1024.0));

	/* The guest kernel's builtin DTB expects 8MB of RAM at 0x80000000.
	 * Try to grab the full 8MB; if the S3 can't provide it contiguously,
	 * step down in 64KB increments and take the biggest block we can.
	 */
	alloc_size = 8 * 1024 * 1024;
	while (alloc_size >= 4 * 1024 * 1024) {
		psram_base = (uint8_t *)heap_caps_malloc(alloc_size, MALLOC_CAP_SPIRAM);
		if (psram_base != NULL)
			break;
		alloc_size -= 64 * 1024;
	}

	if (psram_base == NULL) {
		printf("ERROR: Failed to allocate at least 4MB of PSRAM!\n");
		return -1;
	}

	psram_size = alloc_size;
	if (alloc_size < 8 * 1024 * 1024)
		printf("INFO: allocated %.2f MB PSRAM; guest DTB safely advertises 7.5MB.\n",
			   alloc_size / (1024.0 * 1024.0));
	printf("SUCCESS: PSRAM allocated at %p, size: %zu bytes (%.2f MB)\n",
		   psram_base, psram_size, psram_size / (1024.0 * 1024.0));

	printf("Initializing PSRAM to zero...\n");
	memset(psram_base, 0, psram_size);
	printf("PSRAM initialized successfully!\n");

	return 0;
}

int psram_read(uint32_t addr, void *buf, int len)
{
	if (psram_base == NULL) {
		printf("ERROR: psram_read called before psram_init!\n");
		return -1;
	}

	if (addr + len > psram_size) {
		printf("ERROR: psram_read out of bounds: addr=0x%lx, len=%d, size=%zu\n",
			   (unsigned long)addr, len, psram_size);
		return -1;
	}

	memcpy(buf, psram_base + addr, len);
	return len;
}

int psram_write(uint32_t addr, void *buf, int len)
{
	if (psram_base == NULL) {
		printf("ERROR: psram_write called before psram_init!\n");
		return -1;
	}

	if (addr + len > psram_size) {
		printf("ERROR: psram_write out of bounds: addr=0x%lx, len=%d, size=%zu\n",
			   (unsigned long)addr, len, psram_size);
		return -1;
	}

	memcpy(psram_base + addr, buf, len);
	return len;
}

void *psram_get_base(void)
{
	return psram_base;
}

size_t psram_get_size(void)
{
	return psram_size;
}

void verify_kernel_header(void)
{
	uint8_t header[64];

	printf("\n=== Verifying Kernel Header ===\n");
	psram_read(0, header, 64);

	printf("First 64 bytes of loaded kernel:\n");
	for (int i = 0; i < 64; i++) {
		printf("%02x ", header[i]);
		if ((i + 1) % 16 == 0) printf("\n");
	}
	printf("\n");

	// Check RISC-V magic
	if (header[0x30] == 'R' && header[0x31] == 'I' &&
		header[0x32] == 'S' && header[0x33] == 'C' &&
		header[0x34] == 'V') {
		printf("✓ RISCV magic found at offset 0x30\n");
		} else {
			printf("✗ RISCV magic NOT found! Expected at 0x30\n");
		}

		uint32_t first_instr = *(uint32_t*)header;
	printf("First instruction: 0x%08lx\n", (unsigned long)first_instr);
	printf("Expected: 0x05c0006f (j 0x5c)\n\n");
}

int load_images(int ram_size, int *kern_len)
{
	const esp_partition_t *kernel_partition;
	esp_err_t err;
	uint32_t addr;
	char dmabuf[64];
	size_t partition_size;

	printf("\n=== Loading Kernel from Flash ===\n");

	kernel_partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
												ESP_PARTITION_SUBTYPE_ANY,
											 "kernel");
	if (kernel_partition == NULL) {
		printf("ERROR: 'kernel' partition not found!\n");
		printf("Make sure partition table has 'kernel' partition\n");
		return -1;
	}

	partition_size = kernel_partition->size;
	printf("Found kernel partition:\n");
	printf("  Label: %s\n", kernel_partition->label);
	printf("  Address: 0x%lx\n", (unsigned long)kernel_partition->address);
	printf("  Size: %zu bytes (%.2f MB)\n", partition_size,
		   partition_size / (1024.0 * 1024.0));

	if (partition_size > ram_size) {
		printf("WARNING: Partition size (%zu) > RAM size (%d)\n",
			   partition_size, ram_size);
		printf("Will only load first %d bytes\n", ram_size);
		partition_size = ram_size;
	}

	if (partition_size > psram_get_size()) {
		printf("WARNING: Partition size (%zu) > PSRAM size (%zu)\n",
			   partition_size, psram_get_size());
		partition_size = psram_get_size();
	}

	if (kern_len)
		*kern_len = partition_size;

	printf("\nLoading kernel from flash to PSRAM...\n");
	printf("This will take a moment...\n");

	addr = 0;
	size_t remaining = partition_size;

	while (remaining >= 64) {
		err = esp_partition_read(kernel_partition, addr, dmabuf, 64);
		if (err != ESP_OK) {
			printf("\nERROR: Failed to read from flash at offset %lu: %s\n",
				   (unsigned long)addr, esp_err_to_name(err));
			return -1;
		}

		psram_write(addr, dmabuf, 64);
		addr += 64;
		remaining -= 64;

		if ((addr % (64 * 1024)) == 0) {
			printf(".");
			fflush(stdout);
		}
	}

	if (remaining > 0) {
		err = esp_partition_read(kernel_partition, addr, dmabuf, remaining);
		if (err != ESP_OK) {
			printf("\nERROR: Failed to read remaining bytes: %s\n",
				   esp_err_to_name(err));
			return -1;
		}
		psram_write(addr, dmabuf, remaining);
	}

	printf("\n✓ Kernel loaded successfully from flash!\n");
	printf("Total loaded: %zu bytes (%.2f MB)\n",
		   partition_size, partition_size / (1024.0 * 1024.0));

	verify_kernel_header();

	return 0;
}

/* ---- virtio-blk backing store: the "rootfs" flash partition ---- */

static const esp_partition_t *vblk_part = NULL;

static const esp_partition_t *vblk_get(void)
{
	if (!vblk_part)
		vblk_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
						     ESP_PARTITION_SUBTYPE_ANY, "rootfs");
	return vblk_part;
}

/* XIP: expose the rootfs partition as a memory-mapped read-only region so the
 * guest can execute BusyBox in-place and the romfs MTD driver can read it. */
const uint8_t *rootfs_mmap(void)
{
	const esp_partition_t *p = vblk_get();
	if (!p) {
		printf("rootfs_mmap: 'rootfs' partition not found\n");
		return NULL;
	}
	const void *ptr = NULL;
	esp_partition_mmap_handle_t handle;
	esp_err_t err = esp_partition_mmap(p, 0, p->size,
					   ESP_PARTITION_MMAP_DATA, &ptr, &handle);
	if (err != ESP_OK) {
		printf("rootfs_mmap: esp_partition_mmap failed: %d\n", (int)err);
		return NULL;
	}
	printf("rootfs XIP mapped: %u bytes at %p\n",
	       (unsigned)p->size, ptr);
	return (const uint8_t *)ptr;
}

uint64_t vblk_backend_sectors(void)
{
	const esp_partition_t *p = vblk_get();
	return p ? (uint64_t)(p->size / 512) : 0;
}

int vblk_backend_read(uint64_t sector, void *buf, uint32_t count)
{
	const esp_partition_t *p = vblk_get();
	if (!p) return -1;
	return esp_partition_read(p, (size_t)(sector * 512), buf, count * 512) == ESP_OK ? 0 : -1;
}

/* Write-through to flash with 4KB read-modify-erase-write (flash granularity).
 * Correctness first; only used once the rootfs is mounted read-write. */
int vblk_backend_write(uint64_t sector, const void *buf, uint32_t count)
{
	const esp_partition_t *p = vblk_get();
	if (!p) return -1;
	static uint8_t page[4096];
	for (uint32_t i = 0; i < count; i++) {
		uint32_t off = (uint32_t)((sector + i) * 512);
		uint32_t base = off & ~0xFFFu;
		if (esp_partition_read(p, base, page, sizeof(page)) != ESP_OK) return -1;
		memcpy(page + (off - base), (const uint8_t *)buf + i * 512, 512);
		if (esp_partition_erase_range(p, base, sizeof(page)) != ESP_OK) return -1;
		if (esp_partition_write(p, base, page, sizeof(page)) != ESP_OK) return -1;
	}
	return 0;
}
