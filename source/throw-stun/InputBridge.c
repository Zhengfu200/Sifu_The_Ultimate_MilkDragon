#define WIN32_LEAN_AND_MEAN
#include <wchar.h>
#include <windows.h>

struct lua_State;
static BOOL pressed;

__declspec(dllexport) int PressAttack(struct lua_State *state)
{
    (void)state;
    HWND window = GetForegroundWindow();
    DWORD owner = 0;
    wchar_t class_name[32];
    if (pressed || !window ||
        !GetWindowThreadProcessId(window, &owner) || owner != GetCurrentProcessId() ||
        !GetClassNameW(window, class_name, ARRAYSIZE(class_name)) ||
        wcscmp(class_name, L"UnrealWindow") != 0 ||
        (GetAsyncKeyState(VK_LBUTTON) & 0x8000))
        return 0;

    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    pressed = SendInput(1, &input, sizeof(input)) == 1;
    return 0;
}

__declspec(dllexport) int ReleaseAttack(struct lua_State *state)
{
    (void)state;
    if (pressed) {
        INPUT input = {0};
        input.type = INPUT_MOUSE;
        input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
        if (SendInput(1, &input, sizeof(input)) == 1) pressed = FALSE;
    }
    return 0;
}
