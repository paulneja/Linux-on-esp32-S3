#ifndef MMU_GUEST_SETJMP_H
#define MMU_GUEST_SETJMP_H
/* Guest CALL0 only: return PC, SP, callee-saved a12..a15. No signal state. */
typedef unsigned long jmp_buf[6];
int setjmp(jmp_buf) __attribute__((returns_twice));
void longjmp(jmp_buf, int) __attribute__((noreturn));
#endif
