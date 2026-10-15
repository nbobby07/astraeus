/* SPDX-License-Identifier: CC0-1.0. Owned, freely distributable Win32 fixture. */
#include <windows.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    HWND window = CreateWindowExA(0, "STATIC", "Astraeus Proton smoke",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 320, 160, NULL, NULL, GetModuleHandleA(NULL), NULL);
    if (!window) { fprintf(stderr, "CreateWindowExA failed: %lu\n", GetLastError()); return 1; }
    UpdateWindow(window);
    Sleep(1000);
    if (!DestroyWindow(window)) return 1;
    printf("PHASE4_WINDOWS_OK %s\n", argv[1]);
    return 0;
}
