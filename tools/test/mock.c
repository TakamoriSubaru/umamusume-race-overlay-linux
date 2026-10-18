#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#define EXP __attribute__((visibility("default")))
#define NOINL __attribute__((noinline))

typedef struct MClass MClass;
typedef struct { int type; MClass* klass; const char* tname; } MType;
typedef struct { void* fn; const char* name; int argc; MClass* klass; int flags; MType ret; MType pt[4]; const char* pn[4]; } MMethod;
typedef struct { const char* name; int offset; MType type; } MField;
struct MClass { const char* ns; const char* name; MMethod* methods[16]; int nm; MField fields[16]; int nf;
                int valuetype, isenum; int elem_size; MClass* elem; MClass* parent; MType basetype; };
typedef struct { const char* name; MClass* classes[16]; int nc; } MImage;
typedef struct { MImage* img; } MAsm;

static MImage img_core = {"mscorlib.dll"}, img_game = {"umamusume.dll"};
static MAsm asm_core = {&img_core}, asm_game = {&img_game};
static MAsm* asms[2] = {&asm_core, &asm_game};
static int booted = 0;

static MClass c_list; static char* g_list;
static MClass c_manager, c_horse, c_horse_arr, c_frame, c_frame_arr, c_loader, c_noise, c_obj, c_base;
static MMethod m_update, m_set, m_setb, m_noise1, m_noise2;
static char* g_mgr; static char* g_loader; static char* g_horses[3]; static char* g_harr; static char* g_farr;

#define T(e,n) (MType){e,0,n}
static void addf(MClass* c, const char* name, int off, MType t){ c->fields[c->nf].name=name; c->fields[c->nf].offset=off; c->fields[c->nf].type=t; c->nf++; }
static void addm(MClass* c, MMethod* m){ m->klass=c; c->methods[c->nm++]=m; }

NOINL void race_update(void* self){ __asm__ volatile(""); }
NOINL void loader_set(void* self, void* s, int x){ __asm__ volatile(""); }
NOINL void loader_setb(void* self, void* arr){ __asm__ volatile(""); }
NOINL void noise_a(void* self, int a){ __asm__ volatile(""); }
NOINL void noise_b(void* self){ __asm__ volatile(""); }

static char* new_obj(MClass* k, size_t size){ char* o = calloc(1,size); *(MClass**)o = k; return o; }
EXP void* mock_str(const char* s){
  int n = strlen(s); char* o = new_obj(&c_obj, 0x14 + n*2 + 2);
  *(int*)(o+0x10) = n; for(int i=0;i<n;i++) ((uint16_t*)(o+0x14))[i]=(uint8_t)s[i]; return o; }
EXP void* mock_bytes(const unsigned char* b, int n){
  char* o = new_obj(&c_obj, 0x20+n); *(uint64_t*)(o+0x18)=n; memcpy(o+0x20,b,n); return o; }

EXP void mock_boot(void){
  c_base = (MClass){"Gallop","RaceViewBase"};
  addf(&c_base,"_currentTime",0x10,T(0x0c,"System.Single"));      /* declared in the PARENT class */
  c_manager = (MClass){"Gallop","RaceManager"}; c_manager.parent=&c_base;
  addf(&c_manager,"_isRacing",0x14,T(0x02,"System.Boolean"));
  addf(&c_manager,"_horseInfos",0x18,T(0x1d,"Gallop.HorseRaceInfo[]"));
  addf(&c_manager,"_frameHorses",0x20,T(0x1d,"Gallop.FrameHorse[]"));
  addf(&c_manager,"<RaceId>k__BackingField",0x28,T(0x08,"System.Int32"));
  m_update=(MMethod){(void*)race_update,"Update",0}; m_update.ret=T(1,"System.Void"); addm(&c_manager,&m_update);

  c_horse = (MClass){"Gallop","HorseRaceInfo"};
  addf(&c_horse,"_frameOrder",0x10,T(0x08,"System.Int32"));
  addf(&c_horse,"_distance",0x14,T(0x0c,"System.Single"));
  addf(&c_horse,"_lanePosition",0x18,T(0x07,"System.UInt16"));
  addf(&c_horse,"_runningStyle",0x1c,T(0x08,"System.Int32"));
  addf(&c_horse,"_speed",0x20,T(0x0c,"System.Single"));
  addf(&c_horse,"_hp",0x24,T(0x0c,"System.Single"));
  addf(&c_horse,"_charaId",0x28,T(0x08,"System.Int32"));
  addf(&c_horse,"_trainerName",0x30,T(0x0e,"System.String"));
  addf(&c_horse,"_charaName",0x38,T(0x0e,"System.String"));
  addf(&c_horse,"_aiState",0x40,T(0x08,"System.Int32"));
  c_horse_arr = (MClass){"","HorseRaceInfo[]"}; c_horse_arr.elem=&c_horse; c_horse_arr.elem_size=8;

  c_frame = (MClass){"Gallop","FrameHorse"}; c_frame.valuetype=1;
  addf(&c_frame,"Distance",0x10,T(0x0c,"System.Single"));
  addf(&c_frame,"LanePosition",0x14,T(0x07,"System.UInt16"));
  addf(&c_frame,"Speed",0x16,T(0x07,"System.UInt16"));
  addf(&c_frame,"Hp",0x18,T(0x0c,"System.Single"));
  c_frame_arr = (MClass){"","FrameHorse[]"}; c_frame_arr.elem=&c_frame; c_frame_arr.elem_size=12;
  c_manager.fields[1].type.klass=&c_horse_arr; c_manager.fields[2].type.klass=&c_frame_arr;

  c_loader = (MClass){"Gallop","RaceScenarioLoader"};
  m_set=(MMethod){(void*)loader_set,"SetScenario",2}; m_set.ret=T(1,"System.Void");
  m_set.pt[0]=T(0x0e,"System.String"); m_set.pn[0]="scenarioB64"; m_set.pt[1]=T(0x08,"System.Int32"); m_set.pn[1]="mode"; addm(&c_loader,&m_set);
  m_setb=(MMethod){(void*)loader_setb,"SetBytes",1}; m_setb.ret=T(1,"System.Void");
  m_setb.pt[0]=T(0x1d,"System.Byte[]"); m_setb.pn[0]="data"; addm(&c_loader,&m_setb);

  c_noise = (MClass){"Gallop","RaceUiHelper"};
  m_noise1=(MMethod){(void*)noise_a,"Refresh",1}; m_noise1.ret=T(1,"System.Void"); m_noise1.pt[0]=T(0x08,"System.Int32"); m_noise1.pn[0]="n"; addm(&c_noise,&m_noise1);
  m_noise2=(MMethod){(void*)noise_b,"Reset",0}; m_noise2.ret=T(1,"System.Void"); addm(&c_noise,&m_noise2);
  c_obj = (MClass){"System","String"};

  img_core.classes[img_core.nc++]=&c_obj;
  MClass* gc[] = {&c_noise,&c_base,&c_manager,&c_horse,&c_frame,&c_loader};
  for(int i=0;i<6;i++) img_game.classes[img_game.nc++]=gc[i];

  c_list=(MClass){"System.Collections.Generic","List`1"};
  addf(&c_list,"_items",0x10,T(0x1d,"Gallop.HorseRaceInfo[]")); c_list.fields[0].type.klass=&c_horse_arr;
  addf(&c_list,"_size",0x18,T(0x08,"System.Int32"));
  addf(&c_manager,"_horseList",0x30,T(0x15,"System.Collections.Generic.List<Gallop.HorseRaceInfo>")); c_manager.fields[c_manager.nf-1].type.klass=&c_list;
  img_core.classes[img_core.nc++]=&c_list;
  g_mgr = new_obj(&c_manager, 0x40); g_loader = new_obj(&c_loader, 0x10);
  g_harr = new_obj(&c_horse_arr, 0x20+3*8); *(uint64_t*)(g_harr+0x18)=3;
  g_farr = new_obj(&c_frame_arr, 0x20+3*12); *(uint64_t*)(g_farr+0x18)=3;
  const char* names[3]={"Special Week","Vodka","Tokai Teio"}; const char* tr[3]={"Alice","Bob","Cy"};
  for(int i=0;i<3;i++){ g_horses[i]=new_obj(&c_horse,0x48);
    *(int*)(g_horses[i]+0x10)=i+1; *(int*)(g_horses[i]+0x1c)=2; *(int*)(g_horses[i]+0x28)=1001+i;
    *(void**)(g_horses[i]+0x30)=mock_str(tr[i]); *(void**)(g_horses[i]+0x38)=mock_str(names[i]);
    ((void**)(g_harr+0x20))[i]=g_horses[i]; }
  g_list=new_obj(&c_list,0x20); *(void**)(g_list+0x10)=g_harr; *(int*)(g_list+0x18)=3; *(void**)(g_mgr+0x30)=g_list;
  *(void**)(g_mgr+0x18)=g_harr; *(void**)(g_mgr+0x20)=g_farr; *(int*)(g_mgr+0x28)=10101;
  booted=1;
}
EXP void* mock_manager(void){ return g_mgr; }
EXP void* mock_loader(void){ return g_loader; }
EXP void mock_set_race(float t, int step, int n_valid){
  *(float*)(g_mgr+0x10)=t; *(char*)(g_mgr+0x14)=1;
  for(int i=0;i<3;i++){ char* h=g_horses[i];
    *(float*)(h+0x14)=t*(15.f+i); *(unsigned short*)(h+0x18)=100+i*10; *(float*)(h+0x20)=17.f+i; *(float*)(h+0x24)=1500.f-step; *(int*)(h+0x40)=i%2;
    char* f=g_farr+0x20+i*12; *(float*)f=t*(15.f+i); *(unsigned short*)(f+4)=100+i*10; *(unsigned short*)(f+6)=1700+i; *(float*)(f+8)=1500.f-step; }
}
EXP void mock_call_update(void){ ((void(*)(void*))m_update.fn)(g_mgr); }
EXP void mock_call_set(void* s,int x){ ((void(*)(void*,void*,int))m_set.fn)(g_loader,s,x); }
EXP void mock_call_setb(void* a){ ((void(*)(void*,void*))m_setb.fn)(g_loader,a); }
EXP void mock_call_noise(int n){ ((void(*)(void*,int))m_noise1.fn)(0,n); }

/* ---------------- the il2cpp C api (only what hook_race.js uses) ---------------- */
EXP void* il2cpp_domain_get(void){ static int d; return booted ? (void*)&d : NULL; }
EXP void* il2cpp_thread_attach(void* d){ return d; }
EXP void* il2cpp_domain_get_assemblies(void* d, size_t* n){ *n=2; return asms; }
EXP void* il2cpp_assembly_get_image(void* a){ return ((MAsm*)a)->img; }
EXP const char* il2cpp_image_get_name(void* i){ return ((MImage*)i)->name; }
EXP size_t il2cpp_image_get_class_count(void* i){ return ((MImage*)i)->nc; }
EXP void* il2cpp_image_get_class(void* i, unsigned idx){ return ((MImage*)i)->classes[idx]; }
EXP void* il2cpp_class_from_name(void* i, const char* ns, const char* n){
  MImage* im=i; for(int k=0;k<im->nc;k++) if(!strcmp(im->classes[k]->ns,ns)&&!strcmp(im->classes[k]->name,n)) return im->classes[k]; return NULL; }
EXP const char* il2cpp_class_get_name(void* k){ return ((MClass*)k)->name; }
EXP const char* il2cpp_class_get_namespace(void* k){ return ((MClass*)k)->ns; }
EXP void* il2cpp_class_get_parent(void* k){ return ((MClass*)k)->parent; }
EXP void* il2cpp_class_get_methods(void* k, void** it){ MClass* c=k; size_t i=(size_t)*it; if(i>=c->nm) return NULL; *it=(void*)(i+1); return c->methods[i]; }
EXP void* il2cpp_class_get_method_from_name(void* k, const char* n, int argc){
  for(MClass* c=k;c;c=c->parent) for(int i=0;i<c->nm;i++) if(!strcmp(c->methods[i]->name,n)&&c->methods[i]->argc==argc) return c->methods[i]; return NULL; }
EXP void* il2cpp_class_get_fields(void* k, void** it){ MClass* c=k; size_t i=(size_t)*it; if(i>=c->nf) return NULL; *it=(void*)(i+1); return &c->fields[i]; }
EXP void* il2cpp_class_get_field_from_name(void* k, const char* n){   /* real runtime also walks parents */
  for(MClass* c=k;c;c=c->parent) for(int i=0;i<c->nf;i++) if(!strcmp(c->fields[i].name,n)) return &c->fields[i]; return NULL; }
EXP void* il2cpp_class_from_type(void* t){ return ((MType*)t)->klass; }
EXP int il2cpp_class_is_valuetype(void* k){ return ((MClass*)k)->valuetype; }
EXP int il2cpp_class_is_enum(void* k){ return ((MClass*)k)->isenum; }
EXP void* il2cpp_class_enum_basetype(void* k){ return &((MClass*)k)->basetype; }
EXP void* il2cpp_class_get_element_class(void* k){ return ((MClass*)k)->elem; }
EXP int il2cpp_class_array_element_size(void* k){ return ((MClass*)k)->elem_size; }
EXP const char* il2cpp_method_get_name(void* m){ return ((MMethod*)m)->name; }
EXP unsigned il2cpp_method_get_param_count(void* m){ return ((MMethod*)m)->argc; }
EXP void* il2cpp_method_get_param(void* m, unsigned i){ return &((MMethod*)m)->pt[i]; }
EXP const char* il2cpp_method_get_param_name(void* m, unsigned i){ return ((MMethod*)m)->pn[i]; }
EXP void* il2cpp_method_get_return_type(void* m){ return &((MMethod*)m)->ret; }
EXP unsigned il2cpp_method_get_flags(void* m, unsigned* iflags){ return ((MMethod*)m)->flags; }
EXP const char* il2cpp_field_get_name(void* f){ return ((MField*)f)->name; }
EXP int il2cpp_field_get_offset(void* f){ return ((MField*)f)->offset; }
EXP void* il2cpp_field_get_type(void* f){ return &((MField*)f)->type; }
EXP int il2cpp_type_get_type(void* t){ return ((MType*)t)->type; }
EXP const char* il2cpp_type_get_name(void* t){ return ((MType*)t)->tname ? ((MType*)t)->tname : "?"; }

EXP void mock_corrupt(int mode){
  if(mode==0){ *(void**)(g_mgr+0x30)=g_list; *(void**)(g_mgr+0x18)=g_harr; }
  if(mode==1) *(void**)(g_mgr+0x30)=(void*)0xdeadbeefUL;                       /* unmapped pointer */
  if(mode==2){ void* junk=calloc(1,64); *(void**)junk=junk; *(void**)(g_mgr+0x30)=junk; }   /* mapped, but not a List */
  if(mode==3){ *(void**)(g_list+0x10)=(void*)0x41414141UL; }                    /* list whose _items is garbage */
  if(mode==4) *(float*)(g_mgr+0x10)=__builtin_nanf("");
  if(mode==5) *(float*)(g_mgr+0x10)=1e9f;
}
EXP void mock_update_with(void* self){ ((void(*)(void*))m_update.fn)(self); }
EXP void* mock_junk(void){ void* j=malloc(0x100); memset(j,0xAB,0x100); return j; }
