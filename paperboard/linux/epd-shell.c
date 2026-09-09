// Small PTY relay: serial keyboard/output plus a copy to the Paperboard text device.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>
static struct termios saved;
static int raw;
static volatile sig_atomic_t stopped;
static void restore(void){if(raw)tcsetattr(STDIN_FILENO,TCSANOW,&saved);}
static void stop(int sig){stopped=sig;}
static int write_all(int fd,const void* data,size_t len) {
    const char* p=data;
    while(len) {
        ssize_t n=write(fd,p,len);
        if(n<0&&errno==EINTR&&!stopped)continue;
        if(n<=0)return -1;
        p+=n;len-=n;
    }
    return 0;
}
int main(int argc,char** argv) {
    int master,display,status=0;
    char slave[128];
    pid_t child;
    struct winsize size={.ws_row=34,.ws_col=75,.ws_xpixel=1200,.ws_ypixel=825};
    display=open("/dev/epd",O_WRONLY|O_CLOEXEC);
    if(display<0){perror("/dev/epd (Paperboard kernel/firmware required)");return 1;}
    master=posix_openpt(O_RDWR|O_NOCTTY|O_CLOEXEC);
    if(master<0||grantpt(master)||unlockpt(master)||ptsname_r(master,slave,sizeof(slave))) {
        perror("allocate PTY");return 1;
    }
    if(ioctl(master,TIOCSWINSZ,&size)){perror("PTY size");return 1;}
    // Only the documented basic ANSI subset is available; avoid advertising xterm.
    setenv("TERM","vt100",1);setenv("COLUMNS","75",1);setenv("LINES","34",1);
    if(tcgetattr(STDIN_FILENO,&saved)==0) {
        struct termios t=saved;cfmakeraw(&t);
        if(tcsetattr(STDIN_FILENO,TCSANOW,&t)){perror("serial raw mode");return 1;}
        raw=1;atexit(restore);
    }
    struct sigaction action={.sa_handler=stop};sigemptyset(&action.sa_mask);
    sigaction(SIGTERM,&action,NULL);sigaction(SIGHUP,&action,NULL);sigaction(SIGINT,&action,NULL);
    signal(SIGPIPE,SIG_IGN);
    // vfork is supported by NOMMU Linux. Child only prepares descriptors and execs.
    child=vfork();
    if(child==0) {
        if(setsid()<0)_exit(126);
        int fd=open(slave,O_RDWR);
        if(fd<0)_exit(126);
        if(ioctl(fd,TIOCSCTTY,0)<0)_exit(126);
        if(dup2(fd,0)<0||dup2(fd,1)<0||dup2(fd,2)<0)_exit(126);
        if(fd>2)close(fd);
        if(argc>1)execvp(argv[1],argv+1);
        else execl("/bin/sh","sh","-i",(char*)NULL);
        _exit(127);
    }
    if(child<0){perror("vfork");return 1;}
    if(write_all(display,"\033[2J\033[H",7)) {perror("clear display");stopped=1;}
    struct pollfd fds[2]={{STDIN_FILENO,POLLIN,0},{master,POLLIN,0}};
    while(!stopped) {
        char buf[512];
        int ret=poll(fds,2,-1);
        if(ret<0){if(errno==EINTR)continue;perror("poll");break;}
        if(fds[1].revents&(POLLIN|POLLHUP|POLLERR)) {
            ssize_t n=read(master,buf,sizeof(buf));
            if(n<=0)break;
            if(write_all(STDOUT_FILENO,buf,n)||write_all(display,buf,n))break;
        }
        if(fds[0].revents&(POLLIN|POLLHUP|POLLERR)) {
            ssize_t n=read(STDIN_FILENO,buf,sizeof(buf));
            if(n<=0)break;
            if(write_all(master,buf,n))break;
        }
    }
    close(master);close(display);restore();raw=0;
    // Closing the PTY hangs up the child. Also cover programs ignoring SIGHUP.
    kill(child,SIGHUP);
    while(waitpid(child,&status,0)<0)if(errno!=EINTR)return 1;
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
