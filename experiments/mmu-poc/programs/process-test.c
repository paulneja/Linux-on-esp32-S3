#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern pid_t fork(void);
static volatile unsigned state = 123;
static unsigned tests;
static __attribute__((noinline, cold, noreturn)) void fail(unsigned line) {
    dprintf(2,"FAIL process-test.c:%u errno=%d\n",line,errno);_exit(1);
}
#define CHECK(x) do { if (!(x)) fail(__LINE__); } while (0)
static void pass(const char *s) { printf("PASS: %s\n",s); fflush(stdout); tests++; }
static pid_t spawn(void) { fflush(NULL); pid_t p=fork(); CHECK(p>=0); if(!p)alarm(15); return p; }
static void reap(pid_t p,int code) { int s; CHECK(waitpid(p,&s,0)==p); CHECK(WIFEXITED(s)&&WEXITSTATUS(s)==code); }
static void send_byte(int fd,char c) { CHECK(write(fd,&c,1)==1); }
static char receive(int fd) { char c; CHECK(read(fd,&c,1)==1); return c; }
static long field(const char *path,const char *name) {
    FILE *f=fopen(path,"r"); char line[128]; long n=-1;
    CHECK(f);
    while(fgets(line,sizeof line,f)) if(!strncmp(line,name,strlen(name))) {
        CHECK(sscanf(line+strlen(name),"%ld",&n)==1); break;
    }
    fclose(f); return n;
}
static long shadows(void) { return field("/proc/self/status","ForkShadow:"); }

int main(int argc,char **argv) {
    int a[2],b[2],s,fd; pid_t p,q; char c;
    if(argc==5 && !strcmp(argv[1],"--fd-exec")) {
        errno=0; CHECK(fcntl(atoi(argv[2]),F_GETFD)==-1 && errno==EBADF);
        send_byte(atoi(argv[3]),'E'); CHECK(receive(atoi(argv[4]))=='G'); return 19;
    }
    alarm(60);
    long before=shadows();
    CHECK(pipe(a)==0 && pipe(b)==0);
    p=spawn();
    if(!p) { close(a[0]); close(b[1]); state=456; send_byte(a[1],'R'); CHECK(receive(b[0])=='G'); CHECK(state==456); _exit(0); }
    close(a[1]);close(b[0]);CHECK(receive(a[0])=='R');
    long during=shadows();
    send_byte(b[1],'G');reap(p,0);close(a[0]);close(b[1]);
    long after=shadows();CHECK(state==123);
    if(before>=0) { CHECK(before==0 && during>0 && after==0); }
    printf("RECLAIM parent_kib before=%ld live=%ld after=%ld\n",before,during,after);
    pass("last child exit releases parent backup (host: counter absent)");

    /* Descriptor table is private; open-file offset is shared, as POSIX requires. */
    char path[]="/tmp/process-test.XXXXXX";
    fd=mkstemp(path);CHECK(fd>=0);CHECK(unlink(path)==0);
    CHECK(write(fd,"abcdef",6)==6 && lseek(fd,0,SEEK_SET)==0);
    p=spawn();
    if(!p) { CHECK(receive(fd)=='a');CHECK(fcntl(fd,F_SETFD,FD_CLOEXEC)==0);_exit(0); }
    reap(p,0);CHECK(receive(fd)=='b');CHECK(!(fcntl(fd,F_GETFD)&FD_CLOEXEC));close(fd);
    pass("inherited FD: shared offset, independent descriptor flags");

    CHECK(pipe(a)==0 && pipe(b)==0);fd=open("/dev/null",O_RDONLY|O_CLOEXEC);CHECK(fd>=0);
    p=spawn();
    if(!p) {
        char x[16],y[16],z[16];close(a[0]);close(b[1]);
        snprintf(x,sizeof x,"%d",fd);snprintf(y,sizeof y,"%d",a[1]);snprintf(z,sizeof z,"%d",b[0]);
        execlp(argv[0],argv[0],"--fd-exec",x,y,z,(char *)NULL);_exit(127);
    }
    close(a[1]);close(b[0]);CHECK(receive(a[0])=='E');
    if(before>=0)CHECK(shadows()==0);
    send_byte(b[1],'G');reap(p,19);close(fd);close(a[0]);close(b[1]);
    pass("exec closes CLOEXEC only; releases parent's backup before child exit");

    CHECK(pipe(a)==0);p=spawn();
    if(!p) {
        close(a[0]);CHECK(dup2(a[1],STDOUT_FILENO)==STDOUT_FILENO);close(a[1]);
        execl("/bin/echo","echo","redirect-ok",(char *)NULL);_exit(127);
    }
    close(a[1]);char out[32]={0};CHECK(read(a[0],out,sizeof out-1)==12);
    CHECK(!strcmp(out,"redirect-ok\n"));close(a[0]);reap(p,0);
    pass("dup2 redirection survives exec");

    p=spawn();if(!p) { state=999;execl("/does-not-exist","missing",(char *)NULL);CHECK(errno==ENOENT && state==999);_exit(31); }
    reap(p,31);CHECK(state==123);if(before>=0)CHECK(shadows()==0);
    pass("failed exec preserves child and parent state, exit status and teardown");

    CHECK(pipe(a)==0);close(a[0]);p=spawn();
    if(!p) { signal(SIGPIPE,SIG_DFL);write(a[1],"x",1);_exit(99); }
    CHECK(waitpid(p,&s,0)==p && WIFSIGNALED(s) && WTERMSIG(s)==SIGPIPE);
    p=spawn();if(!p) { CHECK(signal(SIGPIPE,SIG_IGN)!=SIG_ERR);errno=0;CHECK(write(a[1],"x",1)==-1 && errno==EPIPE);_exit(0); }
    reap(p,0);close(a[1]);pass("SIGPIPE default termination and ignored/EPIPE");

    FILE *stream=popen("printf popen-ok","r");CHECK(stream);
    memset(out,0,sizeof out);CHECK(fread(out,1,8,stream)==8);CHECK(!strcmp(out,"popen-ok"));
    s=pclose(stream);CHECK(WIFEXITED(s)&&WEXITSTATUS(s)==0);
    stream=popen("exit 17","r");CHECK(stream);s=pclose(stream);CHECK(WIFEXITED(s)&&WEXITSTATUS(s)==17);
    stream=popen("read v; test \"$v\" = popen-write-ok","w");CHECK(stream);
    CHECK(fputs("popen-write-ok\n",stream)>=0);s=pclose(stream);CHECK(WIFEXITED(s)&&WEXITSTATUS(s)==0);
    pass("libc popen/pclose read/write and status (libc may use vfork)");

    CHECK(pipe(a)==0 && pipe(b)==0);p=spawn();
    if(!p) {
        close(a[0]);close(b[1]);state=456;
        unsigned char *mem=mmap(NULL,65536,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        CHECK(mem!=MAP_FAILED);memset(mem,0xa5,65536);send_byte(a[1],'R');CHECK(receive(b[0])=='G');
        for(unsigned i=0;i<65536;i++)CHECK(mem[i]==0xa5);
        CHECK(state==456);CHECK(munmap(mem,65536)==0);_exit(0);
    }
    close(a[1]);close(b[0]);CHECK(receive(a[0])=='R');
    unsigned char *mem=malloc(32768);CHECK(mem);memset(mem,0x5a,32768);
    send_byte(b[1],'G');reap(p,0);for(unsigned i=0;i<32768;i++)CHECK(mem[i]==0x5a);
    free(mem);close(a[0]);close(b[1]);CHECK(state==123);
    pass("parent malloc and child mmap after fork: independent contents, free/unmap");

    CHECK(pipe(a)==0 && pipe(b)==0);p=spawn();
    if(!p) {
        close(a[0]);state=456;q=spawn();
        if(!q) {
            pid_t old=getppid();close(b[0]);send_byte(a[1],'R');send_byte(b[1],'R');close(b[1]);
            for(unsigned i=0;i<200 && getppid()==old;i++)usleep(10000);
            CHECK(getppid()!=old && state==456);state=789;send_byte(a[1],'O');_exit(0);
        }
        close(b[1]);CHECK(receive(b[0])=='R');close(b[0]);_exit(0);
    }
    close(b[0]);close(b[1]);close(a[1]);CHECK(receive(a[0])=='R');reap(p,0);CHECK(receive(a[0])=='O');
    CHECK(read(a[0],&c,1)==0);close(a[0]);CHECK(state==123);
    pass("orphan reparenting and surviving inherited state");
    for(unsigned i=0;i<24;i++) { p=spawn();if(!p){state=i;_exit(0);}reap(p,0);CHECK(state==123);if(before>=0)CHECK(shadows()==0); }
    pass("24 repeated forks return own shadow pages to zero");
    alarm(0);printf("PASS: process suite %u/10\n",tests);return tests==10?0:1;
}
