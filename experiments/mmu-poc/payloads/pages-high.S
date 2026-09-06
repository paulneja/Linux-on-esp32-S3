    .section .text.high,"ax",@progbits
    .space 65536, 0
    .align 4
    .global high_function
    .type high_function,@function
high_function:
    movi a3, 1000
    add a2, a2, a3
    ret
    .size high_function, .-high_function
    .section .note.GNU-stack,"",@progbits
