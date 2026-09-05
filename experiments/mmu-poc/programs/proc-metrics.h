#ifndef PROC_METRICS_H
#define PROC_METRICS_H
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <sys/types.h>
static long proc_field(const char *path,const char *key) {
    FILE *f=fopen(path,"r"); char line[192]; long value=-1;
    if(!f)return -1;
    while(fgets(line,sizeof line,f)) if(!strncmp(line,key,strlen(key))) {
        if(sscanf(line+strlen(key),"%ld",&value)!=1)value=-1;
        break;
    }
    fclose(f);return value;
}
static long process_field(pid_t pid,const char *key) {
    char path[64];snprintf(path,sizeof path,"/proc/%ld/status",(long)pid);
    return proc_field(path,key);
}
static long long monotonic_ms(void) {
    struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);
    return (long long)ts.tv_sec*1000+ts.tv_nsec/1000000;
}
#endif
