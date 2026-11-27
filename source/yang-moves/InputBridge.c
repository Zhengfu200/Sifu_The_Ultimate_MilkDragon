#define WIN32_LEAN_AND_MEAN
#include <wchar.h>
#include <windows.h>
#include <windowsx.h>

struct lua_State;

__declspec(dllexport) int QueueLightAttack(struct lua_State *state)
{
    (void)state;
    HWND window = GetForegroundWindow();
    DWORD owner = 0;
    wchar_t class_name[32];
    POINT point;
    if (!window || !GetWindowThreadProcessId(window, &owner) || owner != GetCurrentProcessId() ||
        !GetClassNameW(window, class_name, ARRAYSIZE(class_name)) ||
        wcscmp(class_name, L"UnrealWindow") != 0 ||
        (GetAsyncKeyState(VK_LBUTTON) & 0x8000) ||
        !GetCursorPos(&point) || !ScreenToClient(window, &point))
    {
        return 0;
    }

    LPARAM position = MAKELPARAM(point.x, point.y);
    if (PostMessageW(window, WM_LBUTTONDOWN, MK_LBUTTON, position))
        PostMessageW(window, WM_LBUTTONUP, 0, position);
    return 0;
}
