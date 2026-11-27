#define WIN32_LEAN_AND_MEAN
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>

struct lua_State;
typedef void *Object;

enum { DIZZY_STATE = 4, DIZZY_IMPACT = 7 };

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
typedef Object (*GetWorld)(Object);
typedef bool (*CanBeHit)(Object, Object);
typedef uint8_t (*GetFaction)(Object);
typedef bool (*CanTargetFaction)(Object, uint8_t, uint8_t);
typedef Object (*GetState)(Object, uint8_t);
typedef bool (*GetLoop)(Object, const uint8_t *, void *, bool *);
typedef void (*GetRecovery)(Object, void *, const uint8_t *, uint8_t);
typedef int32_t (*PushState)(Object, uint8_t, Object, float, float, float, int32_t, int32_t, uint8_t, void *);
typedef uint8_t (*LaunchOrder)(Object, const void *, const void *, const uint8_t *, int32_t,
                              Object, uint8_t, float, Object, uint8_t, Object, const void *, bool);

enum { REFUSED = 0, APPLIED = 1, ALREADY_DIZZY = 2, INCOMPATIBLE = -1, NO_ANIMATION = -2 };

static bool same_world(const uint8_t *base, Object target, Object player)
{
    // Native AActor::GetWorld uses ULevel::OwningWorld for streaming levels.
    GetWorld get_world = (GetWorld)(base + 0x3284cd0);
    Object player_world = get_world(player);
    return player_world && get_world(target) == player_world;
}

static int apply_dizzy(const uint8_t *base, Object target, Object player, float seconds)
{
    if (!base) return INCOMPATIBLE;
    if (!target || !player || target == player || seconds < 0.2f || seconds > 10.0f)
        return REFUSED;
    if (!same_world(base, target, player)) return REFUSED;
    if (!((CanBeHit)(base + 0x1c837a0))(target, player)) return REFUSED;

    Object defense = ((GetComponent)(base + 0x19bbe90))(target);
    if (!defense) return REFUSED;
    if (((GetState)(base + 0x195c0a0))(defense, DIZZY_STATE)) return ALREADY_DIZZY;

    Object resistance = ((GetComponent)(base + 0x195ad90))(defense);
    if (!resistance) return NO_ANIMATION;

    const Object hit = *(Object *)((uint8_t *)target + 0x1328);
    if (!hit) return REFUSED;

    const uint8_t state = DIZZY_STATE;
    _Alignas(16) uint8_t loop[24] = {0};
    _Alignas(16) uint8_t recovery[24] = {0};
    _Alignas(16) uint8_t on_state_removed[64] = {0};
    bool mirrorable = false;
    if (!((GetLoop)(base + 0x19f6160))(resistance, &state, loop, &mirrorable))
        return NO_ANIMATION;
    ((GetRecovery)(base + 0x19f6950))(resistance, recovery, &state, 0);

    int32_t handle = ((PushState)(base + 0x1966d90))(
        defense, state, resistance, seconds, -1.0f, 0.0f, -1, 0, 0, on_state_removed);
    if (handle < 0) return REFUSED;

    ((LaunchOrder)(base + 0x1a64610))(
        hit, loop, recovery, &state, handle, player, DIZZY_IMPACT, 0.0f,
        resistance, 0, NULL, NULL, false);
    return APPLIED;
}

__declspec(dllexport) int ApplyDizzy(struct lua_State *state)
{
    struct LuaApi api;
    if (!get_lua_api(&api)) return 0;

    _Alignas(16) uint8_t lua[0xa8] = {0};
    api.construct(lua, state);
    const uint8_t *base = game_image();
    // LuaMadeSimple::get_integer removes the value it reads.
    const int64_t milliseconds = api.integer(lua, -1);
    const uintptr_t player = (uintptr_t)api.integer(lua, -1);
    const uintptr_t target = (uintptr_t)api.integer(lua, -1);
    const int result = (target || player)
        ? apply_dizzy(base, (Object)target, (Object)player, (float)milliseconds / 1000.0f)
        : (base ? APPLIED : INCOMPATIBLE);
    api.push_integer(lua, result);
    api.destruct(lua);
    return 1;
}

__declspec(dllexport) int IsEnemy(struct lua_State *state)
{
    struct LuaApi api;
    if (!get_lua_api(&api)) return 0;

    _Alignas(16) uint8_t lua[0xa8] = {0};
    api.construct(lua, state);
    const uint8_t *base = game_image();
    Object game_instance = (Object)(uintptr_t)api.integer(lua, -1);
    Object player = (Object)(uintptr_t)api.integer(lua, -1);
    Object target = (Object)(uintptr_t)api.integer(lua, -1);
    int result = 0;
    if (base && target && player && target != player && game_instance) {
        GetFaction get_faction = (GetFaction)(base + 0x19bc680);
        uint8_t target_faction = get_faction(target);
        uint8_t player_faction = get_faction(player);
        if (!same_world(base, target, player)) {
            result = 4;
        } else if (target_faction >= 6 || player_faction >= 6 || target_faction == player_faction) {
            result = 10000 + 100 * player_faction + target_faction;
        } else if (!((CanTargetFaction)(base + 0x1a1ca80))(game_instance, player_faction, target_faction)) {
            result = 20000 + 100 * player_faction + target_faction;
        } else {
            result = ((CanBeHit)(base + 0x1c837a0))(target, player) ? 1 : 3;
        }
    }
    api.push_integer(lua, result);
    api.destruct(lua);
    return 1;
}
