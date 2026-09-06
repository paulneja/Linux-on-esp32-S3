    .text
    .align 4
    .global mmu_call
    .type mmu_call, @function
mmu_call:
    addi a1, a1, -16
    s32i a0, a1, 12
    l32i a9, a2, 8
    l32i a11, a2, 12
    mov a2, a3
    mov a3, a4
    mov a4, a5
    mov a5, a6
    callx0 a9
    l32i a0, a1, 12
    addi a1, a1, 16
    ret
    .size mmu_call, .-mmu_call
    .section .note.GNU-stack,"",@progbits
