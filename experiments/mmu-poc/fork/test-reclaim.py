#!/usr/bin/env python3
"""Compile the real bank functions with an UP allocator/scheduler test shim."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
source = (root / 'out/linux-fork/mm/nommu-bank.inc').read_text()
source = source.split('int nommu_bank_dup_mmap(', 1)[0]
source = source.replace('#include <linux/sched/signal.h>\n', '')
source = source.replace('#include <linux/moduleparam.h>\n', '')
shim = r'''
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#define module_param_named(name,value,type,perm) \
 static void * const test_param_##name __attribute__((unused)) = &(value)
#define MODULE_PARM_DESC(name,desc)
#define PAGE_SHIFT 12
#define PAGE_SIZE 4096
#define GFP_KERNEL 0
#define __GFP_NORETRY 0
#define __GFP_NOWARN 0
#define struct_size(p,member,n) (sizeof(*(p))+sizeof((p)->member[0])*(n))
#define kzalloc(n,f) calloc(1,n)
#define kfree free
#define free_page(p) free((void *)(p))
typedef long atomic_long_t;
#define ATOMIC_LONG_INIT(n) (n)
#define atomic_long_sub(n,p) (*(p)-=(n))
#define atomic_long_add(n,p) (*(p)+=(n))
#define atomic_long_inc(p) (++*(p))
static unsigned irq_depth;
#define local_irq_save(f) do { (f)=irq_depth++; } while (0)
#define local_irq_restore(f) do { irq_depth=(f); } while (0)
struct list_head { struct list_head *next,*prev; };
#define INIT_LIST_HEAD(h) ((h)->next=(h)->prev=(h))
#define list_empty(h) ((h)->next==(h))
static void list_add_tail(struct list_head *e,struct list_head *h) {
 e->next=h;e->prev=h->prev;h->prev->next=e;h->prev=e;
}
static void list_del_init(struct list_head *e) {
 e->prev->next=e->next;e->next->prev=e->prev;INIT_LIST_HEAD(e);
}
#define entry(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define list_next_entry(p,m) entry((p)->m.next,__typeof__(*(p)),m)
#define list_for_each_entry(p,h,m) \
 for(p=entry((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=list_next_entry(p,m))
struct nommu_bank;
struct vm_region { unsigned long vm_start,vm_top;struct nommu_bank *bank_owner; };
struct mm_struct { struct {struct list_head nommu_banks;} context; };
struct vm_area_struct { struct nommu_bank *nommu_bank;struct vm_region *vm_region;struct mm_struct *vm_mm; };
static int fail_after=-1;
static void (*allocation_hook)(void);
static unsigned long __get_free_page(int ignored) {
 (void)ignored;assert(!irq_depth);
 if(allocation_hook) {void (*fn)(void)=allocation_hook;allocation_hook=NULL;fn();}
 if(fail_after==0)return 0;
 if(fail_after>0)--fail_after;
 return (unsigned long)calloc(1,PAGE_SIZE);
}
'''
tests = r'''
static struct vm_area_struct *departing;
static void exit_during_alloc(void) { bank_detach(departing); }
static void init(struct vm_area_struct *v,struct mm_struct *m,struct vm_region *r) {
 INIT_LIST_HEAD(&m->context.nommu_banks);*v=(struct vm_area_struct){NULL,r,m};
}
int main(void) {
 struct mm_struct ma,mb,mc;
 struct vm_area_struct a,b,c;
 unsigned *memory=calloc(2,PAGE_SIZE);
 struct vm_region r={(unsigned long)memory,(unsigned long)memory+2*PAGE_SIZE,NULL};
 init(&a,&ma,&r);init(&b,&mb,&r);init(&c,&mc,&r);
 *memory=111;
 assert(bank_clone(&b,&a)==0);assert(nommu_bank_shadow_pages==4);
 nommu_bank_switch(&mb);*memory=222;
 bank_detach(&b);
 assert(*memory==111 && a.nommu_bank->count==0 && nommu_bank_pages(&ma)==0);
 assert(nommu_bank_shadow_pages==0 && nommu_bank_recovered_pages==2);
 puts("PASS: departing resident restores survivor and frees both backups");
 for(int i=0;i<100;i++) {
  assert(bank_clone(&b,&a)==0);nommu_bank_switch(&mb);*memory=222;
  assert(bank_clone(&c,&b)==0);nommu_bank_switch(&mc);*memory=333;
  bank_detach(&b);assert(nommu_bank_shadow_pages==4);
  nommu_bank_switch(&ma);assert(*memory==111);
  nommu_bank_switch(&mc);assert(*memory==333);
  bank_detach(&a);assert(*memory==333 && nommu_bank_shadow_pages==0);
  bank_detach(&c);init(&a,&ma,&r);init(&b,&mb,&r);init(&c,&mc,&r);*memory=111;
 }
 puts("PASS: nested ownership and 100 teardown/refork cycles");
 for(int i=0;i<4;i++) {
  fail_after=i;assert(bank_clone(&b,&a)==-ENOMEM);fail_after=-1;
  assert(nommu_bank_shadow_pages==0 && *memory==111);
 }
 puts("PASS: every page allocation failure unwinds without lost state");
 assert(bank_clone(&b,&a)==0);departing=&b;allocation_hook=exit_during_alloc;
 assert(bank_clone(&c,&a)==0);assert(nommu_bank_shadow_pages==4);
 nommu_bank_switch(&mc);assert(*memory==111);*memory=444;
 bank_detach(&c);assert(*memory==111 && nommu_bank_shadow_pages==0);
 bank_detach(&a);free(memory);
 puts("PASS: sibling exits while clone allocation sleeps; backups recreated");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='bank-test-') as tmp:
    executable = str(Path(tmp) / 'test')
    subprocess.run(['cc', '-std=gnu17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', '-x', 'c', '-', '-o', executable],
                   input=shim + source + tests, text=True, check=True)
    subprocess.run([executable], check=True,
                   env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
