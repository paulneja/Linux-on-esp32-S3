#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
#include "proc-metrics.h"
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
    /* No file actions: with any, uClibc's spawn tries fork() and returns ENOSYS
       on NOMMU. USEVFORK keeps setpgid and the signal defaults on the vfork path. */
    posix_spawnattr_t attr;sigset_t dfl;
    sigemptyset(&dfl);sigaddset(&dfl,SIGINT);sigaddset(&dfl,SIGTERM);
    posix_spawnattr_init(&attr);
    posix_spawnattr_setflags(&attr,POSIX_SPAWN_USEVFORK|POSIX_SPAWN_SETPGROUP|POSIX_SPAWN_SETSIGDEF);
    posix_spawnattr_setpgroup(&attr,0);
    posix_spawnattr_setsigdefault(&attr,&dfl);
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
            long long required=(long long)reserve+need;
            for(unsigned i=0;i<next;i++)if(jobs[i].pid>0) {
                long used=process_field(jobs[i].pid,"PrivateRAM:");
                required+=used<0?need:used<need?need-used:0;
            }
            if(avail>=0 && (long long)avail>=required) {
                pid_t p;fflush(NULL);
                int rc=posix_spawnp(&p,jobs[next].argv[0],NULL,&attr,jobs[next].argv,environ);
                if(!rc) {
                    jobs[next].pid=p;jobs[next].started=monotonic_ms();active++;
                    printf("START job=%u pid=%ld active=%u available_kib=%ld required_kib=%lld\n",next+1,(long)p,active,avail,required);
                    next++;waiting=0;blocked_since=now;
                } else if(rc!=ENOMEM && rc!=EAGAIN) {
                    /* glibc reports a failed exec here; uClibc's child exits 127. */
                    errno=rc;perror("posix_spawnp");
                    printf("EXIT job=%u pid=0 code=%d elapsed_ms=0\n",next+1,rc==ENOENT?127:126);
                    failed=1;finished++;next++;
                }
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
