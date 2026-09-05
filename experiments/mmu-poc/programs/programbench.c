#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include "proc-metrics.h"
extern pid_t fork(void);
static volatile sig_atomic_t interrupted;
static void stop(int sig) { interrupted=sig; }
int main(int argc,char **argv) {
    int opt,timeout=30,status=0;pid_t p;long samples=0;
    while((opt=getopt(argc,argv,"+t:"))!=-1) {
        if(opt!='t' || (timeout=atoi(optarg))<1 || timeout>3600)return 2;
    }
    if(optind==argc) {fprintf(stderr,"Usage: programbench [-t seconds] -- program [args...]\n");return 2;}
    signal(SIGINT,stop);signal(SIGTERM,stop);
    long avail0=proc_field("/proc/meminfo","MemAvailable:");
    long shadow0=proc_field("/proc/meminfo","ForkShadow:");
    long recovered0=proc_field("/proc/meminfo","ForkRecovered:");
    long long start=monotonic_ms();
    fflush(NULL);p=fork();
    if(p<0) {perror("fork");return 1;}
    if(!p) {
        setpgid(0,0);
        if(ptrace(PTRACE_TRACEME,0,NULL,NULL)<0)_exit(125);
        execvp(argv[optind],argv+optind);_exit(errno==ENOENT?127:126);
    }
    setpgid(p,p);
    for(;;) {
        pid_t w=waitpid(p,&status,WNOHANG);
        if(w==p)break;
        if(w<0 && errno!=EINTR) {perror("waitpid");return 1;}
        if(interrupted || monotonic_ms()-start>timeout*1000LL) {kill(-p,SIGKILL);waitpid(p,&status,0);return 124;}
        usleep(1000);
    }
    if(!WIFSTOPPED(status) || WSTOPSIG(status)!=SIGTRAP) {
        fprintf(stderr,"No exec-stop: status=%d (125=ptrace unsupported, 126/127=exec failure)\n",status);
        if(WIFSTOPPED(status)) {kill(-p,SIGKILL);waitpid(p,&status,0);}
        return 1;
    }
    long initial=process_field(p,"PrivateRAM:"),peak=initial;
    long own_shadow=process_field(p,"ForkShadow:");
    long avail_min=proc_field("/proc/meminfo","MemAvailable:"),shadow_peak=shadow0;
    char path[64];struct stat st;snprintf(path,sizeof path,"/proc/%ld/exe",(long)p);
    long elf_bytes=stat(path,&st)==0?(long)st.st_size:-1;
    long long exec_stop=monotonic_ms();
    if(ptrace(PTRACE_DETACH,p,NULL,NULL)<0) {perror("detach");kill(-p,SIGKILL);waitpid(p,&status,0);return 1;}
    int timed_out=0;
    for(;;) {
        long n=process_field(p,"PrivateRAM:");if(n>peak)peak=n;
        n=process_field(p,"ForkShadow:");if(n>own_shadow)own_shadow=n;
        n=proc_field("/proc/meminfo","MemAvailable:");if(n>=0 && n<avail_min)avail_min=n;
        n=proc_field("/proc/meminfo","ForkShadow:");if(n>shadow_peak)shadow_peak=n;
        samples++;
        pid_t w=waitpid(p,&status,WNOHANG);
        if(w==p)break;
        if(w<0 && errno!=EINTR) {perror("waitpid");return 1;}
        if(interrupted || monotonic_ms()-start>timeout*1000LL) {kill(-p,SIGKILL);waitpid(p,&status,0);timed_out=1;break;}
        usleep(10000);
    }
    long recovered1=proc_field("/proc/meminfo","ForkRecovered:");
    int code=timed_out?124:WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
    printf("BENCH elf_bytes=%ld exec_private_kib=%ld sampled_peak_private_kib=%ld "
           "sampled_own_shadow_kib=%ld global_shadow_delta_kib=%ld global_recovered_kib=%ld "
           "available_before_kib=%ld sampled_available_min_kib=%ld launch_ms=%lld "
           "instrumented_run_ms=%lld samples=%ld exit=%d\n",
           elf_bytes,initial,peak,own_shadow,shadow0<0?-1:shadow_peak-shadow0,
           recovered0<0?-1:recovered1-recovered0,avail0,avail_min,exec_stop-start,
           monotonic_ms()-exec_stop,samples,code);
    return code;
}
