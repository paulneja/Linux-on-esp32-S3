/*
 * Copyright (c) 2023, Jisheng Zhang <jszhang@kernel.org>. All rights reserved.
 *
 * Use some code of mini-rv32ima.c from https://github.com/cnlohr/mini-rv32ima
 * Copyright 2022 Charles Lohr
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "port.h"
#include "cache.h"
#include "psram.h"
#include "net_console.h"
#include "virtio.h"
#include "s3_dtb.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"

/* The device tree lives just above the guest's advertised RAM (memory node is
 * 7.8125MB) in the top slack of our ~7.88MB PSRAM buffer, so the kernel reads it
 * via a1 but never allocates over it. Must match memory@80000000 in s3.dts. */
#define GUEST_RAM_SIZE   0x780000u
#define DTB_GUEST_OFFSET 0x770000u

/* Emulator debug spam off by default: it floods UART0 and contends the console
 * lock across cores, which starved CPU0 and tripped the interrupt watchdog. */
#ifndef UC_DEBUG
#define UC_DEBUG 0
#endif
#if UC_DEBUG
#define DBG(...) printf(__VA_ARGS__)
#else
#define DBG(...) do {} while (0)
#endif

static uint32_t ram_amt = 8 * 1024 * 1024;
static volatile uint32_t sbi_calls, sbi_putchar_calls, sbi_dbcn_calls;
static volatile uint32_t sbi_last_eid, sbi_last_fid;
static uint8_t uart_ier;
static volatile uint32_t uart_rbr_reads, uart_irq_asserts;

struct MiniRV32IMAState;
void DumpState(struct MiniRV32IMAState *core);
static uint32_t HandleControlStore(uint32_t addy, uint32_t val);
static uint32_t HandleControlLoad(uint32_t addy );
static void HandleSBI(void *state);
static void MiniSleep();

#define MINIRV32WARN(x...) printf(x);
#define MINI_RV32_RAM_SIZE ram_amt
#define MINIRV32_IMPLEMENTATION
#define MINIRV32_POSTEXEC(pc, ir, retval) do { (void)(pc); (void)(ir); (void)(retval); } while (0)

#define MINIRV32_HANDLE_MEM_STORE_CONTROL(addy, val) if (HandleControlStore(addy, val)) return val;
#define MINIRV32_HANDLE_MEM_LOAD_CONTROL(addy, rval) rval = HandleControlLoad(addy);
#define MINIRV32_HANDLE_SBI(state) HandleSBI(state)

/* Direct memory-mapped PSRAM access for guest RAM.
 *
 * The ESP32-S3 maps PSRAM into the address space (unlike the P4 this port came
 * from), so the software cache in cache.c is unnecessary here. More importantly,
 * the virtio devices (virtio.c) access guest RAM directly via psram_get_base();
 * routing the emulator through the software cache would make the two views
 * incoherent (stale virtqueue rings -> "id is not a head"). Both paths must use
 * the same direct access. memcpy handles the guest's unaligned accesses. */
#define MINIRV32_CUSTOM_MEMORY_BUS
static uint8_t *g_ram;   /* = psram_get_base(); set in app_main before the VM runs */

/* XIP flash window: the rootfs (romfs) partition is memory-mapped read-only
 * into the guest's physical address space here, so the guest can execute
 * (execute-in-place) directly from flash instead of copying to RAM. */
#define FLASH_XIP_BASE 0x40000000u
#define FLASH_XIP_SIZE (8u * 1024 * 1024)
static const uint8_t *g_flash;   /* = esp_partition_mmap(rootfs); set in app_main */

static inline uint32_t xip_load4(uint32_t a) { uint32_t v; memcpy(&v, g_flash + (a - FLASH_XIP_BASE), 4); return v; }
static inline uint16_t xip_load2(uint32_t a) { uint16_t v; memcpy(&v, g_flash + (a - FLASH_XIP_BASE), 2); return v; }
static inline uint8_t  xip_load1(uint32_t a) { return g_flash[a - FLASH_XIP_BASE]; }
static inline int in_flash(uint32_t a) { return a >= FLASH_XIP_BASE && a < FLASH_XIP_BASE + FLASH_XIP_SIZE; }

static inline void MINIRV32_STORE4(uint32_t ofs, uint32_t val) { memcpy(g_ram + ofs, &val, 4); }
static inline void MINIRV32_STORE2(uint32_t ofs, uint16_t val) { memcpy(g_ram + ofs, &val, 2); }
static inline void MINIRV32_STORE1(uint32_t ofs, uint8_t val)  { g_ram[ofs] = val; }

static inline uint32_t MINIRV32_LOAD4(uint32_t ofs) { uint32_t v; memcpy(&v, g_ram + ofs, 4); return v; }
static inline uint16_t MINIRV32_LOAD2(uint32_t ofs) { uint16_t v; memcpy(&v, g_ram + ofs, 2); return v; }
static inline uint8_t  MINIRV32_LOAD1(uint32_t ofs) { return g_ram[ofs]; }
static inline int32_t MINIRV32_LOAD1_SIGNED(uint32_t ofs) { return (int8_t)g_ram[ofs]; }
static inline int32_t MINIRV32_LOAD2_SIGNED(uint32_t ofs) { int16_t v; memcpy(&v, g_ram + ofs, 2); return v; }

#include "mini-rv32ima.h"

void DumpState(struct MiniRV32IMAState *core)
{
	unsigned int pc = core->pc;
	unsigned int *regs = (unsigned int *)core->regs;
	uint64_t thit, taccessed;

	cache_get_stat(&thit, &taccessed);
	printf("hit: %llu accessed: %llu\n", thit, taccessed);
	printf("PC: %08x ", pc);
	printf("Z:%08x ra:%08x sp:%08x gp:%08x tp:%08x t0:%08x t1:%08x t2:%08x s0:%08x s1:%08x a0:%08x a1:%08x a2:%08x a3:%08x a4:%08x a5:%08x ",
		   regs[0], regs[1], regs[2], regs[3], regs[4], regs[5], regs[6], regs[7],
		regs[8], regs[9], regs[10], regs[11], regs[12], regs[13], regs[14], regs[15] );
	printf("a6:%08x a7:%08x s2:%08x s3:%08x s4:%08x s5:%08x s6:%08x s7:%08x s8:%08x s9:%08x s10:%08x s11:%08x t3:%08x t4:%08x t5:%08x t6:%08x\n",
		   regs[16], regs[17], regs[18], regs[19], regs[20], regs[21], regs[22], regs[23],
		regs[24], regs[25], regs[26], regs[27], regs[28], regs[29], regs[30], regs[31] );
}

struct MiniRV32IMAState core;

static void run_emulator(void)
{
	printf("\nLoading kernel from flash...\n");

restart:
	memset(&core, 0, sizeof(core));

	if (load_images(ram_amt, NULL) < 0)
		return;

	/* Load the external device tree and point a1 at it. */
	psram_write(DTB_GUEST_OFFSET, (void *)s3_dtb, s3_dtb_len);

	core.pc = MINIRV32_RAM_IMAGE_OFFSET;
	core.regs[10] = 0x00;                                   /* a0 = hart id */
	core.regs[11] = MINIRV32_RAM_IMAGE_OFFSET + DTB_GUEST_OFFSET; /* a1 = dtb */
	core.extraflags = 1;                                  /* enter Linux in S-mode */
	core.mstatus = 0;

	uint64_t lastTime = GetTimeMicroseconds();
	/* Interrupts are sampled at quantum boundaries.  A large block lets a
	 * userspace poll syscall enter and leave the kernel between samples, so an
	 * asserted UART SEIP can starve forever. */
	int instrs_per_flip = 256;
	printf("RV32IMA starting\n");
	printf("Initial PC: 0x%08" PRIx32 "\n", core.pc);

	uint32_t last_printed_pc = 0;
	int trace_enabled = 0;
	uint32_t wfi_pc = 0;
	uint32_t yield_ctr = 0;
	uint32_t time_remainder = 0;
	uint64_t next_heartbeat = lastTime + 10000000;

	while (1) {
		int ret;
		uint64_t *this_ccount = ((uint64_t*)&core.cyclel);
		uint64_t currentTime = GetTimeMicroseconds();
		uint32_t elapsedUs = (uint32_t)(currentTime - lastTime);

		/* The guest executes far slower than real time.  Letting its 1 MHz
		 * timebase follow wall clock causes a permanent 100 Hz timer-interrupt
		 * storm (the handler takes longer than one wall-clock tick).  Bound
		 * virtual time per 1024-instruction quantum so useful guest work can
		 * run between ticks.  While in WFI the short sleep loop still advances
		 * time and wakes at the programmed deadline. */
		/* MiniRV32 advances its 1 MHz timebase once per emulated batch.  On
		 * this ESP32-S3 the accumulated raw deltas make guest time run about
		 * four times faster than wall time.  Scale them explicitly and retain
		 * fractional microseconds so short batches are not lost. */
		uint32_t scaled_time = elapsedUs + time_remainder;
		elapsedUs = scaled_time / 8;
		time_remainder = scaled_time % 8;
		if (elapsedUs > 8) elapsedUs = 8;
		lastTime = currentTime;

		/*
		* // Detect stuck PC
		* if (core.pc == last_pc) {
		*	stuck_count++;
		*
		*	if (stuck_count == 1000 && wfi_pc != core.pc) {
		*		printf("\n!!! PC STUCK at 0x%08" PRIx32 " for %" PRIu32 " iterations !!!\n",
		*			   core.pc, stuck_count);
		*		printf("This is NOT the WFI idle loop (WFI is at 0x%08" PRIx32 ")\n", wfi_pc);
		*		printf("Enabling instruction trace for next 20 steps...\n");
		*		trace_enabled = 20;
		*	}
		*	if (stuck_count == 5000 && wfi_pc != core.pc) {
		*		printf("\n!!! STILL STUCK after 5000 iterations !!!\n");
		*		uint32_t stuck_instr = MINIRV32_LOAD4(core.pc - MINIRV32_RAM_IMAGE_OFFSET);
		*		printf("Instruction at stuck PC: 0x%08" PRIx32 "\n", stuck_instr);
		*		printf("This might be a real hang, not just WFI\n");
		*		DumpState(&core);
		*		return;
		*	}
		*} else {
		*	if (stuck_count > 100 && in_wfi) {
		*		wfi_pc = last_pc;
		*		if (loop_count % 10000 == 0) {
		*			printf("WFI idle loop detected at 0x%08" PRIx32 " (normal)\n", wfi_pc);
		*		}
		*	}
		*	stuck_count = 0;
		*}
		*
		*/
		if (core.pc != last_printed_pc && core.pc != wfi_pc &&
		    (core.pc < 0x80000000 || core.pc > 0x81000000)) {
			DBG("Unusual PC: 0x%08" PRIx32 "\n", core.pc);
			last_printed_pc = core.pc;
		}

		if (trace_enabled > 0) {
			uint32_t ofs = core.pc - MINIRV32_RAM_IMAGE_OFFSET;
			if (ofs < ram_amt) {
				DBG("[TRACE] PC=0x%08" PRIx32 " instr=0x%08" PRIx32 " sp=0x%08" PRIx32 "\n",
					   core.pc, MINIRV32_LOAD4(ofs), core.regs[2]);
			}
			trace_enabled--;
		}

		/* Service virtio devices and assert/clear the external interrupt.
		 * A pending IRQ must also wake the CPU out of WFI (extraflags bit2),
		 * mirroring how the timer interrupt wakes it. */
		bool uart_rx_irq = (uart_ier & 1) && console_kbhit();
		bool uart_tx_irq = (uart_ier & 2) != 0; /* THRE: transmitter always ready */
		if (uart_rx_irq) uart_irq_asserts++;
		virtio_uart_irq(uart_rx_irq || uart_tx_irq);
		if (virtio_poll()) {
			core.sip |= MIP_SEIP;
			core.extraflags &= ~4;
		} else {
			core.sip &= ~MIP_SEIP;
		}

		ret = MiniRV32IMAStep(&core, NULL, 0, elapsedUs, instrs_per_flip);

		if (currentTime >= next_heartbeat) {
			printf("[VM] pc=%08" PRIx32 " priv=%" PRIu32 " satp=%08" PRIx32
			       " scause=%08" PRIx32 " sepc=%08" PRIx32 " stval=%08" PRIx32
			       " sip=%08" PRIx32 " sie=%08" PRIx32 " wfi=%u"
			       " cyc=%08" PRIx32 "%08" PRIx32 " a0=%08" PRIx32
			       " ra=%08" PRIx32 " sp=%08" PRIx32
			       " sbi=%" PRIu32 " putc=%" PRIu32 " dbcn=%" PRIu32
			       " last=%08" PRIx32 "/%" PRIu32
			       " ier=%02x khit=%d rbr=%" PRIu32 " uirq=%" PRIu32 "\n",
			       core.pc, core.extraflags & 3, core.satp, core.scause,
			       core.sepc, core.stval, core.sip, core.sie,
			       !!(core.extraflags & 4), core.cycleh, core.cyclel,
			       core.regs[10], core.regs[1], core.regs[2], sbi_calls,
			       sbi_putchar_calls, sbi_dbcn_calls, sbi_last_eid,
			       sbi_last_fid, uart_ier, console_kbhit(), uart_rbr_reads,
			       uart_irq_asserts);
			next_heartbeat = currentTime + 10000000;
		}

		/* Periodically yield so CPU0/housekeeping and the FreeRTOS tick get
		 * time even while the guest is busy (prevents interrupt-watchdog
		 * starvation now that the guest no longer sits in WFI as often). */
		if ((++yield_ctr & 0x3FFF) == 0)
			vTaskDelay(1);

		switch (ret) {
			case 0:
				break;
			case 1:
				MiniSleep();
				*this_ccount += instrs_per_flip;
				break;
			case 3:
				break;
			case 0x7777:
				goto restart;
			case 0x5555:
				printf("POWEROFF@0x%" PRIu32 "%"PRIu32"\n", core.cycleh, core.cyclel);
				DumpState(&core);
				return;
			default:
				printf("Unknown failure: ret=%d\n", ret);
				DumpState(&core);
				return;
		}
	}


	DumpState(&core);
}

static void emulator_task(void *arg)
{
	(void)arg;
	run_emulator();
	vTaskDelete(NULL);
}

void app_main(void)
{
	setvbuf(stdout, NULL, _IONBF, 0);

	/* Bring up WiFi AP + telnet server first (Core 0). */
	net_console_init();
	wifi_ap_start();
	telnet_start();
	nat_start();

	printf("psram init\n");
	if (psram_init() < 0) {
		printf("failed to init psram\n");
		return;
	}

	/* Keep the guest memory map deterministic. The DTB occupies the final
	 * reserved 64KB inside advertised RAM so it remains mapped across Sv32. */
	if (psram_get_size() < DTB_GUEST_OFFSET + s3_dtb_len) {
		printf("ERROR: PSRAM block too small for 7.5MB guest + DTB\n");
		return;
	}
	/* Linux manages GUEST_RAM_SIZE as described by s3.dts; ram_amt remains
	 * the full physical backing-store bound for safe host-side accesses. */
	ram_amt = psram_get_size();
	g_ram = (uint8_t *)psram_get_base();     /* direct guest-RAM base for the VM */
	printf("Guest advertised RAM: %u bytes (7.50 MB); physical backing: %" PRIu32 " bytes\n",
		   GUEST_RAM_SIZE, ram_amt);

	virtio_init();

	/* Run the emulator pinned to Core 1; WiFi/telnet stay on Core 0. */
	xTaskCreatePinnedToCore(emulator_task, "emu", 32768, NULL, 5, NULL, 1);
}

static void MiniSleep(void)
{
	usleep(10);
}

#define SBI_SUCCESS       0
#define SBI_ERR_NOT_SUPP  (-2)

static void HandleSBI(void *opaque)
{
	struct MiniRV32IMAState *s = opaque;
	uint32_t eid = s->regs[17];
	uint32_t fid = s->regs[16];
	uint32_t a0 = s->regs[10];
	uint32_t a1 = s->regs[11];
	uint32_t err = SBI_SUCCESS;
	uint32_t val = 0;
	sbi_calls++;
	sbi_last_eid = eid;
	sbi_last_fid = fid;

	switch (eid) {
	case 0x00: /* legacy set_timer */
		s->timermatchl = a0; s->timermatchh = a1; s->sip &= ~MIP_STIP;
		break;
	case 0x01: /* legacy console_putchar */
		sbi_putchar_calls++;
		console_putc((char)a0);
		break;
	case 0x02: /* legacy console_getchar: return directly in a0 */
		s->regs[10] = console_kbhit() ? (uint32_t)console_getc() : UINT32_MAX;
		return;
	case 0x08: /* legacy shutdown */
		esp_restart();
		return;
	case 0x10: /* SBI base */
		switch (fid) {
		/* DBCN was ratified with SBI 2.0.  Linux deliberately ignores the
		 * extension when firmware reports an older specification. */
		case 0: val = 0x02000000; break;
		case 1: val = 1; break;
		case 2: val = 1; break;
		case 3:
			switch (a0) {
			case 0x54494d45: case 0x735049: case 0x52464e43:
			case 0x48534d53: case 0x53525354: case 0x4442434e:
			case 0x00: case 0x01: case 0x02: case 0x08:
				val = 1; break;
			default: val = 0; break;
			}
			break;
		case 4: case 5: case 6: val = 0; break;
		default: err = SBI_ERR_NOT_SUPP; break;
		}
		break;
	case 0x54494d45: /* TIME */
		if (fid == 0) {
			s->timermatchl = a0; s->timermatchh = a1; s->sip &= ~MIP_STIP;
		} else err = SBI_ERR_NOT_SUPP;
		break;
	case 0x4442434e: /* debug console */
		sbi_dbcn_calls++;
		if (fid == 0) {
			uint32_t count = a0;
			uint32_t pa = a1;
			uint32_t off = pa - MINIRV32_RAM_IMAGE_OFFSET;
			if (off < ram_amt) {
				if (count > ram_amt - off) count = ram_amt - off;
				for (uint32_t i = 0; i < count; i++) console_putc((char)MINIRV32_LOAD1(off + i));
				val = count;
			}
		} else if (fid == 1) {
			/* Non-blocking DBCN read into guest physical memory. */
			uint32_t count = a0;
			uint32_t pa = a1;
			uint32_t off = pa - MINIRV32_RAM_IMAGE_OFFSET;
			if (off < ram_amt) {
				if (count > ram_amt - off) count = ram_amt - off;
				while (val < count && console_kbhit())
					MINIRV32_STORE1(off + val++, (uint8_t)console_getc());
			}
		} else if (fid == 2) {
			console_putc((char)a0); val = 1;
		} else err = SBI_ERR_NOT_SUPP;
		break;
	case 0x735049:   /* IPI: single hart */
	case 0x52464e43: /* RFENCE: no TLB */
		break;
	case 0x48534d53: /* HSM */
		if (fid == 2) val = 0; else err = SBI_ERR_NOT_SUPP;
		break;
	case 0x53525354: /* system reset */
		esp_restart();
		return;
	default:
		err = SBI_ERR_NOT_SUPP;
		break;
	}

	s->regs[10] = err;
	s->regs[11] = val;
}
static uint8_t uart_scratch = 0;
static uint8_t uart_ier = 0;
static uint16_t uart_divisor = 0;
static uint8_t uart_lcr = 0;
static uint8_t uart_mcr = 0;
static uint8_t uart_fcr = 0;

static uint32_t HandleControlStore(uint32_t addy, uint32_t val)
{
    if (virtio_mmio_store(addy, val)) return 0;
    switch (addy) {
        case 0x10000000:
            if (uart_lcr & 0x80) uart_divisor = (uart_divisor & 0xFF00) | (val & 0xFF);
            else console_putc((char)val);
            break;
        case 0x10000001:
            if (uart_lcr & 0x80) uart_divisor = (uart_divisor & 0x00FF) | ((val & 0xFF) << 8);
            else uart_ier = val;
            break;
        case 0x10000002: uart_fcr = val; break;
        case 0x10000003: uart_lcr = val; break;
        case 0x10000004: uart_mcr = val; break;
        case 0x10000007: uart_scratch = val; break;
    }
    return 0;
}



static uint32_t HandleControlLoad(uint32_t addy)
{
    uint32_t vval;
    if (virtio_mmio_load(addy, &vval)) return vval;
    switch (addy) {
        case 0x10000000:
            if (uart_lcr & 0x80) return uart_divisor & 0xFF;
            if (console_kbhit()) { uart_rbr_reads++; return console_getc(); }
            return 0;
        case 0x10000001:
            if (uart_lcr & 0x80) return (uart_divisor >> 8) & 0xFF;
            return uart_ier;
        case 0x10000002:
            /* IIR: when RX data is available, report "Received Data Available"
             * (0xC4 = FIFO bits | 0b010<<1, int pending) so the polled 8250
             * ISR actually reads RBR. Otherwise 0xC1 = no interrupt pending. */
            if ((uart_ier & 1) && console_kbhit()) return 0xC4;
            if (uart_ier & 2) return 0xC2; /* THRE interrupt pending */
            return 0xC1;
        case 0x10000003: return uart_lcr;
        case 0x10000004: return uart_mcr;
        case 0x10000005: return 0x60 | (console_kbhit() ? 1 : 0);
        case 0x10000006: return 0x00;
        case 0x10000007: return uart_scratch;
    }
    return 0;
}
