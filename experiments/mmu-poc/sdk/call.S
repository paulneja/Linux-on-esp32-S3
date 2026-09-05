/* Bridge non-FDPIC CALL0 payload -> host FDPIC CALL0 function.
 * a2=api, a3=op, a4=x, a5=y, a6=z. Host expects a2..a5 and GOT in a11.
 * The host preserves CALL0 callee-saved a12..a15. a11 is caller-saved.
 */
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
