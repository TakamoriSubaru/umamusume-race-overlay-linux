#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>
static void (*boot)(void); static void (*set_race)(float,int,int); static void (*upd)(void);
static void (*corrupt)(int); static void (*upd_with)(void*); static void* (*junk)(void);
static void frames(int n, float t0){ for(int f=0;f<n;f++){ set_race(t0+f/60.f,f,1); upd(); usleep(16666);} }
int main(void){
  void* h=dlopen("/tmp/fr/GameAssembly.dll",RTLD_NOW|RTLD_GLOBAL); if(!h){puts(dlerror());return 1;}
  boot=dlsym(h,"mock_boot"); set_race=dlsym(h,"mock_set_race"); upd=dlsym(h,"mock_call_update");
  corrupt=dlsym(h,"mock_corrupt"); upd_with=dlsym(h,"mock_update_with"); junk=dlsym(h,"mock_junk");
  boot(); while(access("/tmp/fr/go2",F_OK)) usleep(50000);
  /* A + B: two races back to back, time restarts at 0 with NO pause in between */
  frames(60,0.f); frames(60,0.f);
  /* C: things that go wrong while a race loads / unloads. The game must survive all of them. */
  upd_with(NULL); upd_with((void*)0x1000); upd_with((void*)0xdeadbeefUL); upd_with(junk());   /* bogus `this` */
  corrupt(1); frames(8,1.f);   /* horses pointer unmapped      */
  corrupt(2); frames(8,1.f);   /* horses pointer not a List    */
  corrupt(3); frames(8,1.f);   /* List._items garbage          */
  corrupt(4); frames(8,1.f);   /* time = NaN                   */
  corrupt(5); frames(8,1.f);   /* time = 1e9 (uninitialised)   */
  corrupt(0); frames(30,2.f);  /* everything fine again -> clocks must continue */
  usleep(1800000); puts("host2 survived"); return 0; }
