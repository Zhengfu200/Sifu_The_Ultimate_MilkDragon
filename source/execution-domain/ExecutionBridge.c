#define WIN32_LEAN_AND_MEAN
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>

struct lua_State;
typedef void *Object;

enum { BROKEN = 7 };

// Addresses and layouts are for the Epic v_1.29_6.770 executable below.
static const GUID game_pdb = {
    0xfdd64e0f, 0xb9ed, 0x4479, {0x8f, 0xd8, 0xef, 0xe0, 0x03, 0x8b, 0x91, 0x9d}
};

static const uint8_t *game_image(void)
{
    const uint8_t *base = (const uint8_t *)GetModuleHandleW(L"Sifu-Win64-Shipping.exe");
    if (!base) return NULL;

    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return NULL;
    const IMAGE_NT_HEADERS64 *pe = (const IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (pe->Signature != IMAGE_NT_SIGNATURE || pe->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64)
        return NULL;

    const IMAGE_DATA_DIRECTORY dir = pe->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DEBUG];
    if (dir.Size < sizeof(IMAGE_DEBUG_DIRECTORY) ||
        dir.VirtualAddress > pe->OptionalHeader.SizeOfImage ||
        dir.Size > pe->OptionalHeader.SizeOfImage - dir.VirtualAddress)
        return NULL;

    const IMAGE_DEBUG_DIRECTORY *entries = (const IMAGE_DEBUG_DIRECTORY *)(base + dir.VirtualAddress);
    for (size_t i = 0; i < dir.Size / sizeof(*entries); ++i) {
        const DWORD offset = entries[i].AddressOfRawData;
        if (entries[i].Type != IMAGE_DEBUG_TYPE_CODEVIEW || entries[i].SizeOfData < 24 ||
            offset > pe->OptionalHeader.SizeOfImage - 24)
            continue;
        const uint8_t *record = base + offset;
        uint32_t age;
        memcpy(&age, record + 20, sizeof(age));
        if (age == 1 && !memcmp(record, "RSDS", 4) && !memcmp(record + 4, &game_pdb, 16))
            return base;
    }
    return NULL;
}

typedef void (*LuaConstructor)(void *, struct lua_State *);
typedef void (*LuaDestructor)(void *);
typedef int64_t (*LuaInteger)(const void *, int);
typedef void (*LuaPushInteger)(const void *, int64_t);

struct LuaApi {
    LuaConstructor construct;
    LuaDestructor destruct;
    LuaInteger integer;
    LuaPushInteger push_integer;
};

static bool get_lua_api(struct LuaApi *api)
{
    HMODULE loader = GetModuleHandleW(L"UE4SS.dll");
    if (!loader) return false;
    api->construct = (LuaConstructor)GetProcAddress(loader, "??0Lua@LuaMadeSimple@RC@@QEAA@PEAUlua_State@@@Z");
    api->destruct = (LuaDestructor)GetProcAddress(loader, "??1Lua@LuaMadeSimple@RC@@QEAA@XZ");
    api->integer = (LuaInteger)GetProcAddress(loader, "?get_integer@Lua@LuaMadeSimple@RC@@QEBA_JH@Z");
    api->push_integer = (LuaPushInteger)GetProcAddress(loader, "?set_integer@Lua@LuaMadeSimple@RC@@QEBAX_J@Z");
    return api->construct && api->destruct && api->integer && api->push_integer;
}

typedef Object (*GetComponent)(Object);
typedef Object (*GetState)(Object, uint8_t);
typedef bool (*GetLoop)(Object, const uint8_t *, void *, bool *);
typedef int32_t (*PushState)(Object,uint8_t,Object,float,float,float,int32_t,int32_t,uint8_t,void *);
typedef void (*PopState)(Object,uint8_t,int32_t);
typedef uint8_t (*LaunchOrder)(Object,const void *,const void *,const uint8_t *,int32_t,
    Object,uint8_t,float,Object,uint8_t,Object,const void *,bool);

// A streaming level's outer UWorld is not necessarily its live OwningWorld.
// Use AActor::GetWorld, which resolves ULevel::OwningWorld, for scene membership.
__declspec(dllexport) int SameWorld(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object player=(Object)(uintptr_t)api.integer(lua,-1);
    Object target=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && target && player) {
        typedef Object (*World)(Object);
        World world=(World)(base+0x3284cd0);
        Object current=world(player);
        result=current && world(target)==current ? 1 : 0;
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}

__declspec(dllexport) int Inspect(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object target=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && target) {
        Object defense=((GetComponent)(base+0x19bbe90))(target);
        typedef bool (*Broken)(Object);
        typedef uint8_t (*Highest)(Object);
        if(defense) {
            result=((Broken)(base+0x1950ab0))(defense) ? 1 : 0;
            result|=(int)((Highest)(base+0x195c370))(defense)<<8;
            if(*(float *)((uint8_t *)defense+0x160)<=0.001f)result|=2;
        }
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}

// PDB-matched FFightingStateElement array. Lookup by our handle, never by index.
static uint8_t *owned_state(Object defense,int32_t handle)
{
    uint8_t *data=*(uint8_t **)((uint8_t *)defense+0x440);
    int32_t count=*(int32_t *)((uint8_t *)defense+0x448);
    if (!data || count<0 || count>256) return NULL;
    for (int i=0;i<count;i++) {
        uint8_t *s=data+i*0x90;
        if (s[0x2c]==BROKEN && *(int32_t *)(s+0x30)==handle) return s;
    }
    return NULL;
}

static int acquire(const uint8_t *base,Object target,Object player,Object hit,Object archetype)
{
    typedef Object (*World)(Object);
    if (!base) return -10;
    if (!target || !player || target==player) return -11;
    World world=(World)(base+0x3284cd0);
    if (world(target)!=world(player)) return -11;
    // AI archetypes carry the authoritative Boss flag. Unknown archetypes fail closed.
    if (!archetype || *((uint8_t *)archetype+0x34)) return -12;
    Object defense=((GetComponent)(base+0x19bbe90))(target);
    if (!defense || !hit) return -11;
    Object resistance=((GetComponent)(base+0x195ad90))(defense);
    if (!resistance) return -13;
    uint8_t state=BROKEN;
    _Alignas(16) uint8_t loop[24]={0}, recovery[24]={0}, callback[64]={0};
    bool mirrorable=false;
    if (!((GetLoop)(base+0x19f6160))(resistance,&state,loop,&mirrorable) || !*(Object *)loop) return -13;
    int32_t handle=((PushState)(base+0x1966d90))(
        defense,state,resistance,-1.0f,-1.0f,0.0f,-1,0,0,callback);
    if (handle<0) return -14;
    // A normal StructureBroken order (0x21), never a fake input or health reduction.
    uint8_t result=((LaunchOrder)(base+0x1a64610))(
        hit,loop,recovery,&state,handle,player,10,0.0f,resistance,0,NULL,NULL,false);
    if (result==0) {
        ((PopState)(base+0x1966130))(defense,BROKEN,handle);
        return -15;
    }
    return handle;
}

// All exports are called only on EngineTick with UE4SS-validated live UObjects.
__declspec(dllexport) int Acquire(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api)) return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object archetype=(Object)(uintptr_t)api.integer(lua,-1);
    Object hit=(Object)(uintptr_t)api.integer(lua,-1);
    Object player=(Object)(uintptr_t)api.integer(lua,-1);
    Object target=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();
    api.push_integer(lua,(!target && !player) ? (base ? 1 : -10) : acquire(base,target,player,hit,archetype));
    api.destruct(lua);return 1;
}

static int update_owned(const uint8_t *base,Object target,int32_t handle,bool release)
{
    if (!base || !target || handle<0) return 0;
    Object defense=((GetComponent)(base+0x19bbe90))(target);
    if(!defense) return 0;
    uint8_t *s=owned_state(defense,handle);
    if(!s) return 0;
    if(release) ((PopState)(base+0x1966130))(defense,BROKEN,handle);
    else {s[0xc]=1;*(int32_t *)(s+0x18)=-1;}
    return 1;
}

#define OWNED_EXPORT(NAME,RELEASE) \
__declspec(dllexport) int NAME(struct lua_State *state) { \
    struct LuaApi api;if(!get_lua_api(&api)) return 0; \
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state); \
    int32_t handle=(int32_t)api.integer(lua,-1); \
    Object target=(Object)(uintptr_t)api.integer(lua,-1); \
    api.push_integer(lua,update_owned(game_image(),target,handle,RELEASE)); \
    api.destruct(lua);return 1; }
OWNED_EXPORT(Sustain,false)
OWNED_EXPORT(Release,true)

__declspec(dllexport) int OrderState(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object target=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && target) {
        typedef bool (*Running)(Object,uint8_t,uint8_t,bool);
        Running running=(Running)(base+0x19a1f20);
        if(running(target,8,2,true))result|=1;
        if(running(target,9,2,true))result|=2;
        if(running(target,0x21,2,true))result|=4;
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}

// UCameraComponent's own AddOrUpdateBlendable algorithm (PDB-matched TArray stride 16).
// Keep a neutral zero-weight slot on exit: removing it would invalidate the game's
// cached Focus blendable index when Focus was appended after this effect.
__declspec(dllexport) int SetFilter(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    int weight=(int)api.integer(lua,-1);
    Object material=(Object)(uintptr_t)api.integer(lua,-1);
    Object camera=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && material && camera && weight>=0 && weight<=1000) {
        uint8_t *array=(uint8_t *)camera+0x7c8;
        int32_t *count=(int32_t *)(array+8),*capacity=(int32_t *)(array+12);
        uint8_t *data=*(uint8_t **)array;
        if(*count>=0 && *count<256 && *capacity>=*count) {
            int i=0;
            for(;i<*count;i++)if(*(Object *)(data+i*16+8)==material)break;
            if(i==*count) {
                ++*count;
                if(*count>*capacity)((void (*)(void *,int32_t))(base+0x86ca50))(array,i);
                data=*(uint8_t **)array;
                memset(data+i*16,0,16);
                *(Object *)(data+i*16+8)=material;
            }
            *(float *)(data+i*16)=(float)weight/1000.0f;result=1;
        }
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}

// Unbind only the native takedown phase transition, preserving the actor's other listeners.
// The Lua owner validates the concrete transition class and tracks phase identity.
__declspec(dllexport) int PauseTransition(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object ai=(Object)(uintptr_t)api.integer(lua,-1);
    Object transition=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && transition && ai && *(uint64_t *)((uint8_t *)transition+0x40)) {
        ((void (*)(Object,Object))(base+0x18bdf30))(transition,ai);
        *(uint64_t *)((uint8_t *)transition+0x40)=0;result=1;
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}

__declspec(dllexport) int ResumeTransition(struct lua_State *state)
{
    struct LuaApi api;if(!get_lua_api(&api))return 0;
    _Alignas(16) uint8_t lua[0xa8]={0};api.construct(lua,state);
    Object ai=(Object)(uintptr_t)api.integer(lua,-1);
    Object transition=(Object)(uintptr_t)api.integer(lua,-1);
    const uint8_t *base=game_image();int result=0;
    if(base && transition && ai && !*(uint64_t *)((uint8_t *)transition+0x40)) {
        int32_t parent=*(int32_t *)((uint8_t *)transition+0x38);
        int32_t next=*(int32_t *)((uint8_t *)transition+0x3c);
        if(parent==*(int32_t *)((uint8_t *)ai+0x568)) {
            ((void (*)(Object,Object,int32_t,int32_t))(base+0x18bed90))(transition,ai,parent,next);result=1;
        }
    }
    api.push_integer(lua,result);api.destruct(lua);return 1;
}


