/* Ark-T.exe — lançador do Ark-T no Windows.
 *
 * Fica na raiz da instalação, ao lado de runtime\. Monta o ambiente do
 * GTK (DLLs, typelibs, ícones, esquemas) e abre runtime\python\pythonw.exe
 * com "-m arkt", repassando os argumentos. Compilado com mingw-w64.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

static wchar_t raiz[MAX_PATH];

static void junta(wchar_t *dst, size_t n, const wchar_t *sub)
{
    swprintf(dst, n, L"%ls\\%ls", raiz, sub);
}

static void definir(const wchar_t *nome, const wchar_t *sub)
{
    wchar_t v[MAX_PATH * 2];
    junta(v, MAX_PATH * 2, sub);
    SetEnvironmentVariableW(nome, v);
}

static int erro(const wchar_t *msg)
{
    MessageBoxW(NULL, msg, L"Ark-T", MB_ICONERROR | MB_OK);
    return 1;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE ant, PWSTR args, int mostrar)
{
    (void)inst; (void)ant; (void)mostrar;
    if (!GetModuleFileNameW(NULL, raiz, MAX_PATH))
        return erro(L"Não foi possível localizar a instalação.");
    wchar_t *barra = wcsrchr(raiz, L'\\');
    if (barra) *barra = 0;

    /* PATH: DLLs do GTK primeiro */
    wchar_t gtkbin[MAX_PATH];
    junta(gtkbin, MAX_PATH, L"runtime\\gtk\\bin");
    DWORD n = GetEnvironmentVariableW(L"PATH", NULL, 0);
    wchar_t *path = (wchar_t *)malloc((n + MAX_PATH + 4) * sizeof(wchar_t));
    if (!path) return 1;
    path[0] = 0;
    wcscpy(path, gtkbin);
    if (n) {
        wcscat(path, L";");
        GetEnvironmentVariableW(L"PATH", path + wcslen(path), n);
    }
    SetEnvironmentVariableW(L"PATH", path);
    free(path);

    definir(L"GI_TYPELIB_PATH", L"runtime\\gtk\\lib\\girepository-1.0");
    definir(L"XDG_DATA_DIRS", L"runtime\\gtk\\share");
    definir(L"GSETTINGS_SCHEMA_DIR", L"runtime\\gtk\\share\\glib-2.0\\schemas");
    definir(L"GDK_PIXBUF_MODULEDIR", L"runtime\\gtk\\lib\\gdk-pixbuf-2.0\\2.10.0\\loaders");
    definir(L"ARKT_RUNTIME", L"runtime");
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");

    wchar_t py[MAX_PATH];
    junta(py, MAX_PATH, L"runtime\\python\\pythonw.exe");
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES)
        return erro(L"Arquivo runtime\\python\\pythonw.exe não encontrado.\nReinstale o Ark-T.");

    size_t tam = wcslen(py) + wcslen(args ? args : L"") + 32;
    wchar_t *cmd = (wchar_t *)malloc(tam * sizeof(wchar_t));
    if (!cmd) return 1;
    swprintf(cmd, tam, L"\"%ls\" -m arkt %ls", py, args ? args : L"");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        free(cmd);
        return erro(L"Não foi possível iniciar o Python do Ark-T.");
    }
    free(cmd);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
