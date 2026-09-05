    .text
    .align 4
    .global setjmp
    .type setjmp,@function
setjmp:
    s32i a0, a2, 0
    s32i a1, a2, 4
    s32i a12, a2, 8
    s32i a13, a2, 12
    s32i a14, a2, 16
    s32i a15, a2, 20
    movi a2, 0
    ret
    .size setjmp, .-setjmp
    .align 4
    .global longjmp
    .type longjmp,@function
longjmp:
    mov a9, a2
    mov a2, a3
    bnez a2, 1f
    movi a2, 1
1:
    l32i a12, a9, 8
    l32i a13, a9, 12
    l32i a14, a9, 16
    l32i a15, a9, 20
    l32i a0, a9, 0
    l32i a1, a9, 4
    ret
    .size longjmp, .-longjmp
    .section .note.GNU-stack,"",@progbits
