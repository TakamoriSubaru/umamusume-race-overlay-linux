#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
static void (*boot)(void); static void (*set_race)(float,int,int); static void (*upd)(void);
static void* (*mstr)(const char*); static void* (*mbytes)(const unsigned char*,int);
static void (*cset)(void*,int); static void (*csetb)(void*); static void (*noise)(int);
static void run(float seconds, float speed_a, float speed_b, int frames){
  float t=0; for(int f=0;f<frames;f++){ t += (1.f/60.f)*(f<frames/2?speed_a:speed_b); set_race(t,f,1); upd(); noise(f); usleep(16666);} }
int main(void){
  usleep(1500000);                                                        /* game loads GameAssembly late */
  void* h=dlopen("/tmp/fr/GameAssembly.dll",RTLD_NOW|RTLD_GLOBAL); if(!h){puts(dlerror());return 1;}
  boot=dlsym(h,"mock_boot"); set_race=dlsym(h,"mock_set_race"); upd=dlsym(h,"mock_call_update");
  mstr=dlsym(h,"mock_str"); mbytes=dlsym(h,"mock_bytes"); cset=dlsym(h,"mock_call_set"); csetb=dlsym(h,"mock_call_setb"); noise=dlsym(h,"mock_call_noise");
  usleep(900000); boot();                                                 /* il2cpp initialises a bit later */
  while(access("/tmp/fr/go",F_OK)) usleep(50000);
  /* race 1: string scenario, 1x then 2x speed */
  char* big=malloc(30000); memcpy(big,"H4sIAAAA",8); for(int i=8;i<29999;i++) big[i]='A'+(i%26); big[29999]=0;
  cset(mstr(big),7); usleep(300000); run(0,1.f,2.f,150); usleep(2600000);
  /* race 2: a different scenario, time restarts at 0 */
  big[100]='Z'; cset(mstr(big),7); usleep(200000); run(0,1.f,1.f,60); usleep(2600000);
  /* race 3: byte[] scenario (needs configure()) */
  unsigned char* bb=malloc(5000); for(int i=0;i<5000;i++) bb[i]=i*7; bb[0]=0x1f; bb[1]=0x8b;
  csetb(mbytes(bb,5000)); usleep(200000); run(0,1.f,1.f,240); usleep(1500000);
  puts("host done"); return 0; }
