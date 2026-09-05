/* Twelve independently owned 64 KiB pages; eight code and four data. */
ENTRY(mmu_main)
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
MEMORY {
    code (rx) : ORIGIN = 0x43000000, LENGTH = 512K
    data (rw) : ORIGIN = 0x3d080000, LENGTH = 256K
}
SECTIONS {
    .text : { *(.literal .literal.*) *(.text .text.*) } > code :code
    .data : { *(.rodata .rodata.*) *(.data .data.*) } > data :data
    .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) } > data :data
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
