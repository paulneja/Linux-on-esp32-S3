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

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static int trap_nesting_level = 0;
static uint32_t last_trap_pc[10] = {0};
static int trap_pc_idx = 0;
static uint32_t ram_amt = 8 * 1024 * 1024;

struct MiniRV32IMAState;
void DumpState(struct MiniRV32IMAState *core);
static uint32_t HandleException(uint32_t ir, uint32_t retval);
static uint32_t HandleControlStore(uint32_t addy, uint32_t val);
static uint32_t HandleControlLoad(uint32_t addy );
static void HandleOtherCSRWrite(uint8_t *image, uint16_t csrno, uint32_t value);
static int32_t HandleOtherCSRRead(uint8_t *image, uint16_t csrno);
static void MiniSleep();

#define MINIRV32WARN(x...) printf(x);
#define MINI_RV32_RAM_SIZE ram_amt
#define MINIRV32_IMPLEMENTATION
#define MINIRV32_POSTEXEC(pc, ir, retval) \
{ \
	if (retval > 0) { \
		/* Track trap nesting */ \
		trap_nesting_level++; \
		last_trap_pc[trap_pc_idx++ % 10] = pc; \
		\
		/* Detect runaway recursion */ \
		if (trap_nesting_level > 10) { \
			printf("\n[FATAL] Trap nesting level = %d\n", trap_nesting_level); \
			printf("Last 10 trap PCs: "); \
			for (int i = 0; i < 10; i++) { \
				printf("0x%08" PRIx32 " ", last_trap_pc[i]); \
			} \
			printf("\n"); \
			printf("This indicates recursive exception handling.\n"); \
			printf("Likely causes:\n"); \
			printf("1. Exception handler accessing invalid memory\n"); \
			printf("2. Exception handler using unimplemented instruction\n"); \
			printf("3. UART/console output failing in panic handler\n"); \
			DumpState(state); \
			trap_nesting_level = 0; \
			return 0x5555; \
		} \
		\
		static int trap_count = 0; \
		if (trap_count++ < 20) { \
			printf("[TRAP #%d nest=%d] code=%" PRIu32 " PC=0x%08" PRIx32 " sp=0x%08" PRIx32 "\n", \
			trap_count, trap_nesting_level, retval, pc, state->regs[2]); \
		} \
		\
		retval = HandleException(ir, retval); \
		trap_nesting_level--; \
	} \
}

#define MINIRV32_HANDLE_MEM_STORE_CONTROL(addy, val) if (HandleControlStore(addy, val)) return val;
#define MINIRV32_HANDLE_MEM_LOAD_CONTROL(addy, rval) rval = HandleControlLoad(addy);
#define MINIRV32_OTHERCSR_WRITE(csrno, value) HandleOtherCSRWrite(image, csrno, value);
#define MINIRV32_OTHERCSR_READ(csrno, value) value = HandleOtherCSRRead(image, csrno);

#define MINIRV32_CUSTOM_MEMORY_BUS
static void MINIRV32_STORE4(uint32_t ofs, uint32_t val)
{
	cache_write(ofs, &val, 4);
}

static void MINIRV32_STORE2(uint32_t ofs, uint16_t val)
{
	cache_write(ofs, &val, 2);
}

static void MINIRV32_STORE1(uint32_t ofs, uint8_t val)
{
	cache_write(ofs, &val, 1);
}

static uint32_t MINIRV32_LOAD4(uint32_t ofs)
{
	uint32_t val;
	cache_read(ofs, &val, 4);
	return val;
}

static uint16_t MINIRV32_LOAD2(uint32_t ofs)
{
	uint16_t val;
	cache_read(ofs, &val, 2);
	return val;
}

static uint8_t MINIRV32_LOAD1(uint32_t ofs)
{
	uint8_t val;
	cache_read(ofs, &val, 1);
	return val;
}

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

	if (load_images(ram_amt, NULL) < 0)
		return;

	core.pc = MINIRV32_RAM_IMAGE_OFFSET;
	core.regs[10] = 0x00;
	core.extraflags |= 3;

	uint64_t lastTime = GetTimeMicroseconds();
	int instrs_per_flip = 1024;
	printf("RV32IMA starting\n");
	printf("Initial PC: 0x%08" PRIx32 "\n", core.pc);

	int loop_count = 0;
	uint32_t last_pc = 0;
	uint32_t stuck_count = 0;
	uint32_t last_printed_pc = 0;
	int trace_enabled = 0;
	uint32_t wfi_pc = 0;
	bool in_wfi = false;

	while (1) {
		int ret;
		uint64_t *this_ccount = ((uint64_t*)&core.cyclel);
		uint64_t currentTime = GetTimeMicroseconds();
		uint32_t elapsedUs = (uint32_t)(currentTime - lastTime);

		if (elapsedUs > 100000) elapsedUs = 100000;
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
		last_pc = core.pc;

		if (core.pc != last_printed_pc && core.pc != wfi_pc &&
		    (core.pc < 0x80000000 || core.pc > 0x81000000)) {
			printf("Unusual PC: 0x%08" PRIx32 "\n", core.pc);
			last_printed_pc = core.pc;
		}

		loop_count++;

		if (trace_enabled > 0) {
			uint32_t ofs = core.pc - MINIRV32_RAM_IMAGE_OFFSET;
			if (ofs < ram_amt) {
				uint32_t instr = MINIRV32_LOAD4(ofs);
				printf("[TRACE] PC=0x%08" PRIx32 " instr=0x%08" PRIx32 " sp=0x%08" PRIx32 "\n",
					   core.pc, instr, core.regs[2]);
			}
			trace_enabled--;
		}

		ret = MiniRV32IMAStep(&core, NULL, 0, elapsedUs, instrs_per_flip);

		in_wfi = (ret == 1);

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

	printf("psram init\n");
	if (psram_init() < 0) {
		printf("failed to init psram\n");
		return;
	}

	/* Match the emulated RAM size to what we actually allocated. */
	ram_amt = psram_get_size();
	printf("Guest RAM size: %" PRIu32 " bytes (%.2f MB)\n",
		   ram_amt, ram_amt / (1024.0 * 1024.0));

	/* Run the emulator pinned to Core 1; WiFi/telnet stay on Core 0. */
	xTaskCreatePinnedToCore(emulator_task, "emu", 32768, NULL, 5, NULL, 1);
}

static void MiniSleep(void)
{
	usleep(10);
}

static int exception_count = 0;

static uint32_t HandleException(uint32_t ir, uint32_t code)
{
	exception_count++;

	const char *exception_names[] = {
		"Instr misaligned", "Instr fault", "Illegal instr", "Breakpoint",
		"Load misaligned", "Load fault", "Store misaligned", "Store fault",
		"Ecall U-mode", "Ecall S-mode", "Reserved", "Ecall M-mode",
		"Instr page fault", "Load page fault", "Reserved", "Store page fault"
	};

	uint32_t cause = code - 1;
	const char *cause_str = (cause < 16) ? exception_names[cause] : "Unknown";

	if (exception_count <= 15) {
		printf("[EXCEPTION #%d] %s (cause=%" PRIu32 ")\n", exception_count, cause_str, cause);
		printf("  PC=0x%08" PRIx32 " mepc=0x%08" PRIx32 " mcause=0x%08" PRIx32 " mtval=0x%08" PRIx32 "\n",
			   core.pc, core.mepc, core.mcause, core.mtval);
		printf("  sp=0x%08" PRIx32 " ra=0x%08" PRIx32 "\n", core.regs[2], core.regs[1]);

		if (cause == 3) {
			printf("  BREAKPOINT/BUG detected - kernel panic likely\n");
			printf("  Check a0-a2 for panic args: a0=0x%08" PRIx32 " a1=0x%08" PRIx32 " a2=0x%08" PRIx32 "\n",
				   core.regs[10], core.regs[11], core.regs[12]);
		}
	}

	return code;
}
static uint8_t uart_scratch = 0;
static uint8_t uart_ier = 0;
static uint16_t uart_divisor = 0;
static uint8_t uart_lcr = 0;
static uint8_t uart_mcr = 0;
static uint8_t uart_fcr = 0;

static uint32_t HandleControlStore(uint32_t addy, uint32_t val)
{
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
    switch (addy) {
        case 0x10000000:
            if (uart_lcr & 0x80) return uart_divisor & 0xFF;
            return console_kbhit() ? console_getc() : 0;
        case 0x10000001:
            if (uart_lcr & 0x80) return (uart_divisor >> 8) & 0xFF;
            return uart_ier;
        case 0x10000002:
            /* IIR: when RX data is available, report "Received Data Available"
             * (0xC4 = FIFO bits | 0b010<<1, int pending) so the polled 8250
             * ISR actually reads RBR. Otherwise 0xC1 = no interrupt pending. */
            return console_kbhit() ? 0xC4 : 0xC1;
        case 0x10000003: return uart_lcr;
        case 0x10000004: return uart_mcr;
        case 0x10000005: return 0x60 | (console_kbhit() ? 1 : 0);
        case 0x10000006: return 0x00;
        case 0x10000007: return uart_scratch;
    }
    return 0;
}
static void HandleOtherCSRWrite(uint8_t *image, uint16_t csrno, uint32_t value)
{
	uint32_t ptrstart, ptrend;

	if (csrno != 0x136 && csrno != 0x137 && csrno != 0x138 &&
		csrno != 0x139 && csrno != 0x3a0 && csrno != 0x3b0 && csrno != 0xf14) {
		static int csr_write_count = 0;
	if (csr_write_count++ < 20) {
		printf("[CSR_WRITE] csr=0x%03x value=0x%08" PRIx32 "\n", csrno, value);
	}
		}

		switch (csrno) {
			case 0x136:
				printf("%d", (int)value);
				fflush(stdout);
				break;
			case 0x137:
				printf("%08" PRIx32, value);
				fflush(stdout);
				break;
			case 0x138:
				ptrstart = value - MINIRV32_RAM_IMAGE_OFFSET;
				ptrend = ptrstart;
				if (ptrstart >= ram_amt)
					printf("DEBUG PASSED INVALID PTR (%"PRIu32")\n", value);
			while (ptrend < ram_amt) {
				uint8_t c = MINIRV32_LOAD1(ptrend);
				if (c == 0)
					break;
				fwrite(&c, 1, 1, stdout);
				ptrend++;
			}
			break;
			case 0x139:
				putchar(value);
				fflush(stdout);
				break;
			default:
				break;
		}
}

static int32_t HandleOtherCSRRead(uint8_t *image, uint16_t csrno)
{
	int32_t result = 0;

	if (csrno == 0x140) {
		if (!console_kbhit())
			result = -1;
		else
			result = console_getc();
	}

	if (csrno != 0x140 && csrno != 0xC00 && csrno != 0x3a0 &&
		csrno != 0x3b0 && csrno != 0xf14 && result == 0) {
		static int csr_warn_count = 0;
	if (csr_warn_count++ < 20) {
		printf("[CSR_READ] Unhandled csr=0x%03x -> 0x%08" PRIx32 "\n",
			   csrno, (uint32_t)result);
	}
		}

		return result;
}
