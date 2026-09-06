#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
#include "proc-metrics.h"
extern pid_t fork(void);
struct job {char **argv;pid_t pid;long long started;};
static volatile sig_atomic_t cancelled;
static void stop(int sig) {cancelled=sig;}
static long number(const char *s) {
    char *end;errno=0;long n=strtol(s,&end,10);
    if(errno || *end || !*s || n<0 || n>2147483647L) {fprintf(stderr,"Invalid number: %s\n",s);exit(2);}return n;
}
int main(int argc,char **argv) {
    long parallel=2,need=256,reserve=512,wait_seconds=30,timeout=60;
    int opt;while((opt=getopt(argc,argv,"+j:m:r:w:t:"))!=-1) {
        switch(opt) {
        case 'j':parallel=number(optarg);break;case 'm':need=number(optarg);break;
        case 'r':reserve=number(optarg);break;case 'w':wait_seconds=number(optarg);break;
        case 't':timeout=number(optarg);break;default:return 2;
        }
    }
    if(optind==argc || parallel<1 || parallel>32 || wait_seconds<1 || timeout<1) {
        fprintf(stderr,"Usage: jobq [-j workers] [-m need_KiB] [-r reserve_KiB] [-w admission_seconds] [-t job_seconds] -- cmd args ::: cmd args\n");return 2;
    }
    struct job jobs[64]={0};unsigned count=1,next=0,finished=0,active=0;int failed=0,waiting=0;
    jobs[0].argv=argv+optind;
    for(int i=optind;i<argc;i++)if(!strcmp(argv[i],":::")) {
        if(count==64 || i==optind || i==argc-1 || !strcmp(argv[i+1],":::"))return 2;
        argv[i]=NULL;jobs[count++].argv=argv+i+1;
    }
    signal(SIGINT,stop);signal(SIGTERM,stop);
    long long blocked_since=monotonic_ms();
    while(finished<count) {
        long long now=monotonic_ms();
        for(unsigned i=0;i<next;i++)if(jobs[i].pid>0) {
            if(cancelled || now-jobs[i].started>timeout*1000LL)kill(-jobs[i].pid,SIGKILL);
            int status;pid_t w=waitpid(jobs[i].pid,&status,WNOHANG|WUNTRACED);
            if(w==jobs[i].pid && WIFSTOPPED(status)) {
                fprintf(stderr,"STOPPED job=%u signal=%d; queue jobs must be noninteractive\n",i+1,WSTOPSIG(status));
                kill(-jobs[i].pid,SIGKILL);failed=1;continue;
            }
            if(w==jobs[i].pid) {
                int code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
                printf("EXIT job=%u pid=%ld code=%d elapsed_ms=%lld\n",i+1,(long)w,code,now-jobs[i].started);
                if(code)failed=1;
                jobs[i].pid=0;active--;finished++;blocked_since=now;
            } else if(w<0 && errno!=EINTR) {perror("waitpid");failed=1;cancelled=SIGTERM;}
        }
        if(cancelled && next<count) {finished+=count-next;next=count;failed=1;}
        if(next<count && active<(unsigned)parallel) {
            long avail=proc_field("/proc/meminfo","MemAvailable:");
            long own=process_field(getpid(),"PrivateRAM:");if(own<0)own=256;
            long long required=(long long)reserve+need+2LL*own;
            for(unsigned i=0;i<next;i++)if(jobs[i].pid>0) {
                long used=process_field(jobs[i].pid,"PrivateRAM:");
                required+=used<0?need:used<need?need-used:0;
            }
            if(avail>=0 && (long long)avail>=required) {
                fflush(NULL);pid_t p=fork();
                if(!p) {
                    setpgid(0,0);signal(SIGINT,SIG_DFL);signal(SIGTERM,SIG_DFL);
                    execvp(jobs[next].argv[0],jobs[next].argv);_exit(errno==ENOENT?127:126);
                }
                if(p>0) {
                    setpgid(p,p);jobs[next].pid=p;jobs[next].started=monotonic_ms();active++;
                    printf("START job=%u pid=%ld active=%u available_kib=%ld required_kib=%lld\n",next+1,(long)p,active,avail,required);
                    next++;waiting=0;blocked_since=now;
                } else if(errno!=ENOMEM && errno!=EAGAIN) {perror("fork");failed=1;finished++;next++;}
            } else if(!waiting) {
                printf("WAIT job=%u available_kib=%ld required_kib=%lld\n",next+1,avail,required);waiting=1;
            }
            if(next<count && now-blocked_since>wait_seconds*1000LL) {
                fprintf(stderr,"ADMISSION_TIMEOUT job=%u; not started\n",next+1);
                failed=1;finished++;next++;blocked_since=now;waiting=0;
            }
        }
        fflush(stdout);if(finished<count)usleep(20000);
    }
    return cancelled?128+cancelled:failed?1:0;
}
