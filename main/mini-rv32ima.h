// mini-rv32ima with Sv32 MMU + S/U privilege + emulated-SBI (TinyEMU-style).
// Derived from Charles Lohr's mini-rv32ima.h (BSD/MIT/CC0). MMU/priv/SBI
// additions 2026. The guest kernel runs in SUPERVISOR mode; the emulator plays
// the role of M-mode firmware and services SBI ecalls in C.
//
// Memory model:
//   * Guest physical RAM lives at MINIRV32_RAM_IMAGE_OFFSET (0x80000000).
//   * All effective addresses from fetch/load/store go through Sv32 translation
//     when satp.MODE=1 (else bare/identity).
//   * After translation, a physical address either hits RAM or an MMIO range
//     (MINIRV32_MMIO_RANGE) which is dispatched to the control handlers.
//
// Driver must provide (in addition to the classic mini-rv32ima macros):
//   MINIRV32_HANDLE_SBI( state )  -- service an ECALL from S-mode; read/modify
//                                    state->regs[10..17] (a0..a7). The core
//                                    advances pc past the ecall afterwards.

#ifndef _MINI_RV32IMA_MMU_H
#define _MINI_RV32IMA_MMU_H

#ifndef MINIRV32WARN
	#define MINIRV32WARN( x... );
#endif
#ifndef MINIRV32_DECORATE
	#define MINIRV32_DECORATE static
#endif
#ifndef MINIRV32_RAM_IMAGE_OFFSET
	#define MINIRV32_RAM_IMAGE_OFFSET  0x80000000
#endif
#ifndef MINIRV32_MMIO_RANGE
	#define MINIRV32_MMIO_RANGE(n)  (0x0C000000 <= (n) && (n) < 0x12000000)
#endif
#ifndef MINIRV32_POSTEXEC
	#define MINIRV32_POSTEXEC(...);
#endif
#ifndef MINIRV32_HANDLE_MEM_STORE_CONTROL
	#define MINIRV32_HANDLE_MEM_STORE_CONTROL(...);
#endif
#ifndef MINIRV32_HANDLE_MEM_LOAD_CONTROL
	#define MINIRV32_HANDLE_MEM_LOAD_CONTROL(...);
#endif
#ifndef MINIRV32_HANDLE_SBI
	#define MINIRV32_HANDLE_SBI(...);
#endif

// Physical RAM access (offset = paddr - RAM_IMAGE_OFFSET). May be overridden.
#ifndef MINIRV32_CUSTOM_MEMORY_BUS
	#define MINIRV32_STORE4( ofs, val ) *(uint32_t*)(image + ofs) = val
	#define MINIRV32_STORE2( ofs, val ) *(uint16_t*)(image + ofs) = val
	#define MINIRV32_STORE1( ofs, val ) *(uint8_t*)(image + ofs) = val
	#define MINIRV32_LOAD4( ofs ) *(uint32_t*)(image + ofs)
	#define MINIRV32_LOAD2( ofs ) *(uint16_t*)(image + ofs)
	#define MINIRV32_LOAD1( ofs ) *(uint8_t*)(image + ofs)
	#define MINIRV32_LOAD2_SIGNED( ofs ) *(int16_t*)(image + ofs)
	#define MINIRV32_LOAD1_SIGNED( ofs ) *(int8_t*)(image + ofs)
#endif

// mstatus bit positions we care about (S-mode subset).
#define MSTATUS_SIE   (1u<<1)
#define MSTATUS_SPIE  (1u<<5)
#define MSTATUS_SPP   (1u<<8)
#define MSTATUS_SUM   (1u<<18)
#define MSTATUS_MXR   (1u<<19)
// sstatus is a masked view of mstatus.
#define SSTATUS_MASK  (MSTATUS_SIE|MSTATUS_SPIE|MSTATUS_SPP|MSTATUS_SUM|MSTATUS_MXR| \
                       (3u<<13) /*FS*/ | (3u<<15) /*XS*/ )

// Interrupt / mip-mie bit positions (S-mode).
#define MIP_SSIP (1u<<1)
#define MIP_STIP (1u<<5)
#define MIP_SEIP (1u<<9)

// Access kinds for translation.
#define ACC_LOAD  0
#define ACC_STORE 1
#define ACC_FETCH 2

struct MiniRV32IMAState
{
	uint32_t regs[32];

	uint32_t pc;
	uint32_t mstatus;      // holds SIE/SPIE/SPP/SUM/MXR (+FS so the FPU-less kernel is happy)
	uint32_t cyclel;
	uint32_t cycleh;

	uint32_t timerl;       // "mtime"  (microsecond-ish counter)
	uint32_t timerh;
	uint32_t timermatchl;  // "stimecmp" via SBI set_timer
	uint32_t timermatchh;

	// Supervisor trap CSRs.
	uint32_t sscratch;
	uint32_t stvec;
	uint32_t sepc;
	uint32_t scause;
	uint32_t stval;

	uint32_t sie;          // S interrupt-enable (SSIE/STIE/SEIE)
	uint32_t sip;          // S interrupt-pending (SSIP/STIP/SEIP)
	uint32_t satp;

	// Bits 0..1 = privilege (S=1, U=0).  Bit 2 = WFI.  Bits 3+ = LR/SC slot.
	uint32_t extraflags;
};

#ifndef MINIRV32_STEPPROTO
MINIRV32_DECORATE int32_t MiniRV32IMAStep( struct MiniRV32IMAState * state, uint8_t * image, uint32_t vProcAddress, uint32_t elapsedUs, int count );
#endif

#ifdef MINIRV32_IMPLEMENTATION

#ifndef MINIRV32_CUSTOM_INTERNALS
#define CSR( x ) state->x
#define SETCSR( x, val ) { state->x = val; }
#define REG( x ) state->regs[x]
#define REGSET( x, val ) { state->regs[x] = val; }
#endif

// -------------------------------------------------------------------------
// Sv32 page-table walk.  Returns 0 on success (sets *pa_out), else a non-zero
// trap value (already "code+1": 13=instr, 14=load, 16=store page fault).
// -------------------------------------------------------------------------
static inline uint32_t mrv_pagefault_code( int access )
{
	if( access == ACC_FETCH ) return 12u + 1u;
	if( access == ACC_STORE ) return 15u + 1u;
	return 13u + 1u; // load
}

static uint32_t mrv_translate( struct MiniRV32IMAState * state, uint8_t * image,
                               uint32_t va, int access, uint32_t * pa_out )
{
	uint32_t satp = CSR( satp );
	if( ( satp >> 31 ) == 0 ) { *pa_out = va; return 0; } // Bare mode.

	uint32_t priv = CSR( extraflags ) & 3;           // 1=S, 0=U
	uint32_t sum  = CSR( mstatus ) & MSTATUS_SUM;
	uint32_t mxr  = CSR( mstatus ) & MSTATUS_MXR;

	uint32_t a = ( satp & 0x3fffff ) << 12;           // root page table phys addr
	uint32_t pte = 0, pte_pa = 0;
	int level;
	for( level = 1; level >= 0; level-- )
	{
		uint32_t vpn = ( level == 1 ) ? ( ( va >> 22 ) & 0x3ff )
		                              : ( ( va >> 12 ) & 0x3ff );
		pte_pa = a + vpn * 4;
		uint32_t off = pte_pa - MINIRV32_RAM_IMAGE_OFFSET;
		if( off >= MINI_RV32_RAM_SIZE - 3 ) return mrv_pagefault_code( access );
		pte = MINIRV32_LOAD4( off );

		if( !( pte & 1 ) || ( ( pte & 0x6 ) == 0x4 ) ) // !V, or W without R
			return mrv_pagefault_code( access );

		if( pte & 0xa ) break;                          // R or X set -> leaf
		a = ( ( pte >> 10 ) & 0x3fffff ) << 12;         // descend
		if( level == 0 ) return mrv_pagefault_code( access );
	}

	uint32_t x = pte & 0x8, w = pte & 0x4, r = pte & 0x2, u = pte & 0x10;

	// Permission checks.
	if( access == ACC_FETCH )      { if( !x ) return mrv_pagefault_code( access ); }
	else if( access == ACC_STORE ) { if( !w ) return mrv_pagefault_code( access ); }
	else /* load */                { if( !( r || ( mxr && x ) ) ) return mrv_pagefault_code( access ); }

	if( priv == 0 ) { if( !u ) return mrv_pagefault_code( access ); }   // U-mode needs U
	else {                                                              // S-mode
		if( u ) {
			if( access == ACC_FETCH ) return mrv_pagefault_code( access ); // S never execs U
			if( !sum ) return mrv_pagefault_code( access );                // needs SUM for data
		}
	}

	// Set A (and D on store) directly in the PTE (avoid A/D faults).
	uint32_t newpte = pte | 0x40;                       // A
	if( access == ACC_STORE ) newpte |= 0x80;           // D
	if( newpte != pte )
		MINIRV32_STORE4( pte_pa - MINIRV32_RAM_IMAGE_OFFSET, newpte );

	uint32_t ppn;
	if( level == 1 ) {                                   // 4MiB superpage
		if( ( pte >> 10 ) & 0x3ff ) return mrv_pagefault_code( access ); // misaligned
		ppn = ( ( ( pte >> 20 ) & 0xfff ) << 10 ) | ( ( va >> 12 ) & 0x3ff );
	} else {
		ppn = ( pte >> 10 ) & 0x3fffff;
	}
	*pa_out = ( ppn << 12 ) | ( va & 0xfff );
	return 0;
}

#ifndef MINIRV32_STEPPROTO
MINIRV32_DECORATE int32_t MiniRV32IMAStep( struct MiniRV32IMAState * state, uint8_t * image, uint32_t vProcAddress, uint32_t elapsedUs, int count )
#else
MINIRV32_STEPPROTO
#endif
{
	uint32_t new_timer = CSR( timerl ) + elapsedUs;
	if( new_timer < CSR( timerl ) ) CSR( timerh )++;
	CSR( timerl ) = new_timer;

	// S-mode timer (SBI set_timer -> timermatch). Fire STIP when reached.
	if( ( CSR( timerh ) > CSR( timermatchh ) || ( CSR( timerh ) == CSR( timermatchh ) && CSR( timerl ) > CSR( timermatchl ) ) )
	    && ( CSR( timermatchh ) || CSR( timermatchl ) ) )
	{
		CSR( extraflags ) &= ~4; // wake from WFI
		CSR( sip ) |= MIP_STIP;
	}
	else
		CSR( sip ) &= ~MIP_STIP;

	// Decide whether to take an S-mode interrupt this quantum.
	uint32_t trap = 0;
	uint32_t rval = 0;
	uint32_t pc = CSR( pc );
	uint32_t cycle = CSR( cyclel );
	uint32_t priv = CSR( extraflags ) & 3;

	uint32_t pending = CSR( sip ) & CSR( sie );
	uint32_t irq_enabled = ( priv < 1 ) || ( ( priv == 1 ) && ( CSR( mstatus ) & MSTATUS_SIE ) );
	if( pending && irq_enabled )
	{
		if( pending & MIP_SEIP )      trap = 0x80000009;
		else if( pending & MIP_STIP ) trap = 0x80000005;
		else if( pending & MIP_SSIP ) trap = 0x80000001;
		if( trap ) pc -= 4; // undo the +4 the trap epilogue re-adds for interrupts
	}

	// If WFI and nothing pending, idle.
	if( !trap && ( CSR( extraflags ) & 4 ) )
		return 1;

	CSR( extraflags ) &= ~4; // We are awake now (either an IRQ fired or not in WFI).

	if( !trap )
	for( int icount = 0; icount < count; icount++ )
	{
		uint32_t ir = 0;
		rval = 0;
		cycle++;

		// ---- instruction fetch (translated) ----
		if( pc & 3 ) { trap = 1 + 0; break; } // misaligned (no C ext)
		uint32_t ppc;
		uint32_t ft = mrv_translate( state, image, pc, ACC_FETCH, &ppc );
		if( ft ) { trap = ft; rval = pc; break; }
		uint32_t pofs = ppc - MINIRV32_RAM_IMAGE_OFFSET;
		if( pofs >= MINI_RV32_RAM_SIZE ) { trap = 1 + 1; rval = pc; break; } // fetch access fault
		ir = MINIRV32_LOAD4( pofs );

		uint32_t rdid = (ir >> 7) & 0x1f;

		switch( ir & 0x7f )
		{
			case 0x37: rval = ( ir & 0xfffff000 ); break; // LUI
			case 0x17: rval = pc + ( ir & 0xfffff000 ); break; // AUIPC
			case 0x6F: // JAL
			{
				int32_t reladdy = ((ir & 0x80000000)>>11) | ((ir & 0x7fe00000)>>20) | ((ir & 0x00100000)>>9) | ((ir&0x000ff000));
				if( reladdy & 0x00100000 ) reladdy |= 0xffe00000;
				rval = pc + 4;
				pc = pc + reladdy - 4;
				break;
			}
			case 0x67: // JALR
			{
				uint32_t imm = ir >> 20;
				int32_t imm_se = imm | (( imm & 0x800 )?0xfffff000:0);
				rval = pc + 4;
				pc = ( (REG( (ir >> 15) & 0x1f ) + imm_se) & ~1) - 4;
				break;
			}
			case 0x63: // Branch
			{
				uint32_t immm4 = ((ir & 0xf00)>>7) | ((ir & 0x7e000000)>>20) | ((ir & 0x80) << 4) | ((ir >> 31)<<12);
				if( immm4 & 0x1000 ) immm4 |= 0xffffe000;
				int32_t rs1 = REG((ir >> 15) & 0x1f);
				int32_t rs2 = REG((ir >> 20) & 0x1f);
				immm4 = pc + immm4 - 4;
				rdid = 0;
				switch( ( ir >> 12 ) & 0x7 )
				{
					case 0: if( rs1 == rs2 ) pc = immm4; break;
					case 1: if( rs1 != rs2 ) pc = immm4; break;
					case 4: if( rs1 < rs2 ) pc = immm4; break;
					case 5: if( rs1 >= rs2 ) pc = immm4; break;
					case 6: if( (uint32_t)rs1 < (uint32_t)rs2 ) pc = immm4; break;
					case 7: if( (uint32_t)rs1 >= (uint32_t)rs2 ) pc = immm4; break;
					default: trap = (2+1);
				}
				break;
			}
			case 0x03: // Load
			{
				uint32_t rs1 = REG((ir >> 15) & 0x1f);
				uint32_t imm = ir >> 20;
				int32_t imm_se = imm | (( imm & 0x800 )?0xfffff000:0);
				uint32_t va = rs1 + imm_se;
				uint32_t pa;
				uint32_t f = mrv_translate( state, image, va, ACC_LOAD, &pa );
				if( f ) { trap = f; rval = va; break; }
				uint32_t roff = pa - MINIRV32_RAM_IMAGE_OFFSET;
				if( roff >= MINI_RV32_RAM_SIZE-3 )
				{
					if( MINIRV32_MMIO_RANGE( pa ) )
					{
						MINIRV32_HANDLE_MEM_LOAD_CONTROL( pa, rval );
					}
					else { trap = (5+1); rval = va; }
				}
				else
				{
					switch( ( ir >> 12 ) & 0x7 )
					{
						case 0: rval = MINIRV32_LOAD1_SIGNED( roff ); break;
						case 1: rval = MINIRV32_LOAD2_SIGNED( roff ); break;
						case 2: rval = MINIRV32_LOAD4( roff ); break;
						case 4: rval = MINIRV32_LOAD1( roff ); break;
						case 5: rval = MINIRV32_LOAD2( roff ); break;
						default: trap = (2+1);
					}
				}
				break;
			}
			case 0x23: // Store
			{
				uint32_t rs1 = REG((ir >> 15) & 0x1f);
				uint32_t rs2 = REG((ir >> 20) & 0x1f);
				uint32_t addy = ( ( ir >> 7 ) & 0x1f ) | ( ( ir & 0xfe000000 ) >> 20 );
				if( addy & 0x800 ) addy |= 0xfffff000;
				uint32_t va = addy + rs1;
				rdid = 0;
				uint32_t pa;
				uint32_t f = mrv_translate( state, image, va, ACC_STORE, &pa );
				if( f ) { trap = f; rval = va; break; }
				uint32_t roff = pa - MINIRV32_RAM_IMAGE_OFFSET;
				if( roff >= MINI_RV32_RAM_SIZE-3 )
				{
					if( MINIRV32_MMIO_RANGE( pa ) )
					{
						MINIRV32_HANDLE_MEM_STORE_CONTROL( pa, rs2 );
					}
					else { trap = (7+1); rval = va; }
				}
				else
				{
					switch( ( ir >> 12 ) & 0x7 )
					{
						case 0: MINIRV32_STORE1( roff, rs2 ); break;
						case 1: MINIRV32_STORE2( roff, rs2 ); break;
						case 2: MINIRV32_STORE4( roff, rs2 ); break;
						default: trap = (2+1);
					}
				}
				break;
			}
			case 0x13: // Op-immediate
			case 0x33: // Op
			{
				uint32_t imm = ir >> 20;
				imm = imm | (( imm & 0x800 )?0xfffff000:0);
				uint32_t rs1 = REG((ir >> 15) & 0x1f);
				uint32_t is_reg = !!( ir & 0x20 );
				uint32_t rs2 = is_reg ? REG(imm & 0x1f) : imm;

				if( is_reg && ( ir & 0x02000000 ) )
				{
					switch( (ir>>12)&7 )
					{
						case 0: rval = rs1 * rs2; break;
						case 1: rval = ((int64_t)((int32_t)rs1) * (int64_t)((int32_t)rs2)) >> 32; break;
						case 2: rval = ((int64_t)((int32_t)rs1) * (uint64_t)rs2) >> 32; break;
						case 3: rval = ((uint64_t)rs1 * (uint64_t)rs2) >> 32; break;
						case 4: if( rs2 == 0 ) rval = -1; else rval = ((int32_t)rs1 == INT32_MIN && (int32_t)rs2 == -1) ? rs1 : ((int32_t)rs1 / (int32_t)rs2); break;
						case 5: if( rs2 == 0 ) rval = 0xffffffff; else rval = rs1 / rs2; break;
						case 6: if( rs2 == 0 ) rval = rs1; else rval = ((int32_t)rs1 == INT32_MIN && (int32_t)rs2 == -1) ? 0 : ((uint32_t)((int32_t)rs1 % (int32_t)rs2)); break;
						case 7: if( rs2 == 0 ) rval = rs1; else rval = rs1 % rs2; break;
					}
				}
				else
				{
					switch( (ir>>12)&7 )
					{
						case 0: rval = (is_reg && (ir & 0x40000000) ) ? ( rs1 - rs2 ) : ( rs1 + rs2 ); break;
						case 1: rval = rs1 << (rs2 & 0x1F); break;
						case 2: rval = (int32_t)rs1 < (int32_t)rs2; break;
						case 3: rval = rs1 < rs2; break;
						case 4: rval = rs1 ^ rs2; break;
						case 5: rval = (ir & 0x40000000 ) ? ( ((int32_t)rs1) >> (rs2 & 0x1F) ) : ( rs1 >> (rs2 & 0x1F) ); break;
						case 6: rval = rs1 | rs2; break;
						case 7: rval = rs1 & rs2; break;
					}
				}
				break;
			}
			case 0x0f: // FENCE / FENCE.I
				rdid = 0;
				break;
			case 0x73: // SYSTEM / Zicsr
			{
				uint32_t csrno = ir >> 20;
				uint32_t microop = ( ir >> 12 ) & 0x7;
				if( ( microop & 3 ) ) // Zicsr
				{
					int rs1imm = (ir >> 15) & 0x1f;
					uint32_t rs1 = REG(rs1imm);
					uint32_t writeval = rs1;

					switch( csrno )
					{
					case 0x100: rval = CSR( mstatus ) & SSTATUS_MASK; break; // sstatus
					case 0x104: rval = CSR( sie ); break;                    // sie
					case 0x105: rval = CSR( stvec ); break;                  // stvec
					case 0x106: rval = 0; break;                             // scounteren
					case 0x140: rval = CSR( sscratch ); break;               // sscratch
					case 0x141: rval = CSR( sepc ); break;                   // sepc
					case 0x142: rval = CSR( scause ); break;                 // scause
					case 0x143: rval = CSR( stval ); break;                  // stval
					case 0x144: rval = CSR( sip ); break;                    // sip
					case 0x180: rval = CSR( satp ); break;                   // satp
					case 0xC00: rval = cycle; break;                         // cycle
					case 0xC01: rval = CSR( timerl ); break;                 // time
					case 0xC80: rval = CSR( cycleh ); break;                 // cycleh
					case 0xC81: rval = CSR( timerh ); break;                 // timeh
					default: rval = 0; break;
					}

					switch( microop )
					{
						case 1: writeval = rs1; break;
						case 2: writeval = rval | rs1; break;
						case 3: writeval = rval & ~rs1; break;
						case 5: writeval = rs1imm; break;
						case 6: writeval = rval | rs1imm; break;
						case 7: writeval = rval & ~rs1imm; break;
					}

					switch( csrno )
					{
					case 0x100: // sstatus (write only S-visible bits)
						SETCSR( mstatus, ( CSR( mstatus ) & ~SSTATUS_MASK ) | ( writeval & SSTATUS_MASK ) );
						break;
					case 0x104: SETCSR( sie, writeval ); break;
					case 0x105: SETCSR( stvec, writeval ); break;
					case 0x106: break; // scounteren
					case 0x140: SETCSR( sscratch, writeval ); break;
					case 0x141: SETCSR( sepc, writeval ); break;
					case 0x142: SETCSR( scause, writeval ); break;
					case 0x143: SETCSR( stval, writeval ); break;
					case 0x144: // sip: only SSIP is writable by S-mode
						SETCSR( sip, ( CSR( sip ) & ~MIP_SSIP ) | ( writeval & MIP_SSIP ) );
						break;
					case 0x180: SETCSR( satp, writeval ); break; // (TLB-less: nothing to flush)
					default: break;
					}
				}
				else if( microop == 0x0 ) // privileged SYSTEM
				{
					rdid = 0;
					if( ( csrno & 0xff ) == 0x02 && ( csrno >> 8 ) == 0x1 ) // SRET (0x10200000>>20 = 0x102)
					{
						uint32_t s = CSR( mstatus );
						uint32_t spp  = ( s & MSTATUS_SPP ) ? 1 : 0;
						uint32_t spie = ( s & MSTATUS_SPIE ) ? 1 : 0;
						s = ( s & ~MSTATUS_SIE ) | ( spie ? MSTATUS_SIE : 0 ); // SIE = SPIE
						s |= MSTATUS_SPIE;                                     // SPIE = 1
						s &= ~MSTATUS_SPP;                                     // SPP = U
						SETCSR( mstatus, s );
						CSR( extraflags ) = ( CSR( extraflags ) & ~3u ) | spp; // priv = SPP
						pc = CSR( sepc ) - 4;
					}
					else switch( csrno )
					{
					case 0x000: // ECALL
						if( ( CSR( extraflags ) & 3 ) == 1 ) // from S-mode -> SBI
						{
							MINIRV32_HANDLE_SBI( state );
							// pc advances by 4 below (normal flow).
						}
						else // from U-mode -> trap to S (scause 8)
							trap = (8+1);
						break;
					case 0x001: trap = (3+1); break; // EBREAK
					case 0x102: break; // (already handled SRET above; unreachable)
					case 0x105: // WFI
						CSR( extraflags ) |= 4;
						break;
					case 0x120: // SFENCE.VMA (csrno for sfence is func7=0x09; handled below)
						break;
					default:
						// SFENCE.VMA has funct7=0001001, rs2/rs1 in fields -> csrno top bits.
						if( ( ( ir >> 25 ) & 0x7f ) == 0x09 ) { /* TLB-less: no-op */ }
						else trap = (2+1);
						break;
					}
				}
				else
					trap = (2+1);
				break;
			}
			case 0x2f: // RV32A
			{
				uint32_t rs1v = REG((ir >> 15) & 0x1f);
				uint32_t rs2 = REG((ir >> 20) & 0x1f);
				uint32_t irmid = ( ir>>27 ) & 0x1f;
				int is_lr = ( irmid == 2 );
				uint32_t pa;
				uint32_t f = mrv_translate( state, image, rs1v, is_lr ? ACC_LOAD : ACC_STORE, &pa );
				if( f ) { trap = f; rval = rs1v; break; }
				uint32_t roff = pa - MINIRV32_RAM_IMAGE_OFFSET;
				if( roff >= MINI_RV32_RAM_SIZE-3 )
				{
					trap = (7+1); rval = rs1v;
				}
				else
				{
					rval = MINIRV32_LOAD4( roff );
					uint32_t dowrite = 1;
					switch( irmid )
					{
						case 2: dowrite = 0; CSR( extraflags ) = (CSR( extraflags ) & 0x07) | (rs1v<<3); break; // LR
						case 3: // SC
							rval = ( CSR( extraflags ) >> 3 != ( rs1v & 0x1fffffff ) );
							dowrite = !rval;
							break;
						case 1: break;                 // AMOSWAP
						case 0: rs2 += rval; break;    // AMOADD
						case 4: rs2 ^= rval; break;    // AMOXOR
						case 12: rs2 &= rval; break;   // AMOAND
						case 8: rs2 |= rval; break;    // AMOOR
						case 16: rs2 = ((int32_t)rs2<(int32_t)rval)?rs2:rval; break; // AMOMIN
						case 20: rs2 = ((int32_t)rs2>(int32_t)rval)?rs2:rval; break; // AMOMAX
						case 24: rs2 = (rs2<rval)?rs2:rval; break; // AMOMINU
						case 28: rs2 = (rs2>rval)?rs2:rval; break; // AMOMAXU
						default: trap = (2+1); dowrite = 0; break;
					}
					if( dowrite ) MINIRV32_STORE4( roff, rs2 );
				}
				break;
			}
			default: trap = (2+1);
		}

		if( trap ) { MINIRV32_POSTEXEC( pc, ir, trap ); break; }

		if( rdid ) { REGSET( rdid, rval ); }

		MINIRV32_POSTEXEC( pc, ir, trap );
		pc += 4;
	}

	// ---- take S-mode trap / interrupt ----
	if( trap )
	{
		uint32_t is_interrupt = trap & 0x80000000;
		uint32_t cause, tval;
		if( is_interrupt )
		{
			cause = trap;
			tval = 0;
			pc += 4; // return to the instruction we were about to run
		}
		else
		{
			cause = trap - 1;
			tval = rval;
		}

		SETCSR( scause, cause );
		SETCSR( stval, tval );
		SETCSR( sepc, pc );

		// sstatus: SPIE=SIE; SIE=0; SPP=current priv (S=1/U=0)
		uint32_t s = CSR( mstatus );
		uint32_t oldsie = ( s & MSTATUS_SIE ) ? 1 : 0;
		s = ( s & ~MSTATUS_SPIE ) | ( oldsie ? MSTATUS_SPIE : 0 );
		s &= ~MSTATUS_SIE;
		s = ( s & ~MSTATUS_SPP ) | ( ( CSR( extraflags ) & 1 ) ? MSTATUS_SPP : 0 );
		SETCSR( mstatus, s );

		CSR( extraflags ) = ( CSR( extraflags ) & ~3u ) | 1u; // enter S-mode
		pc = ( CSR( stvec ) & ~3u ) - 4;                       // direct mode
		trap = 0;
		pc += 4;
	}

	if( CSR( cyclel ) > cycle ) CSR( cycleh )++;
	SETCSR( cyclel, cycle );
	SETCSR( pc, pc );
	return 0;
}

#endif // MINIRV32_IMPLEMENTATION
#endif // _MINI_RV32IMA_MMU_H

