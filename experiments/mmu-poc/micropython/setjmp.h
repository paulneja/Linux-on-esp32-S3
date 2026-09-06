#ifndef MMU_GUEST_SETJMP_H
#define MMU_GUEST_SETJMP_H
typedef unsigned long jmp_buf[6];
int setjmp(jmp_buf) __attribute__((returns_twice));
void longjmp(jmp_buf, int) __attribute__((noreturn));
#endif
