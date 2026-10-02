/* Minimal service-DLL host harness for dynamic analysis.
 *
 * x64dbg's built-in raw-DLL debugging feature (opening a .dll directly)
 * auto-generates its own generic loader stub ("DLLLoader<bits>_<hex>.exe").
 * That stub has been observed to block indefinitely inside a GetMessage-style
 * wait in its own message loop (RIP parked on a win32u.dll syscall stub,
 * thread state "running" not "paused") before ever calling LoadLibrary on the
 * target -- it appears to present interactive UI that never gets input under
 * headless automation. Debugging a raw DLL through that feature is not
 * reliable for this pipeline.
 *
 * This harness avoids that feature entirely: debug THIS compiled exe as a
 * normal EXE debuggee (the well-tested x64dbg path), pointed at the sample
 * DLL as argv[1]. Deploy it into the guest renamed to "svchost.exe" so
 * GetModuleFileName-based host-identity gates in service DLLs (checking for
 * "svchost.exe" in their own process path) pass without needing a real
 * Windows service/SCM registration, which would mutate guest state outside
 * the normal snapshot-revert boundary for no guaranteed benefit -- some
 * service DLLs gate only on the host process name (this harness satisfies
 * that), others additionally validate real SCM globals passed into
 * SvchostPushServiceGlobals (this harness cannot satisfy that; treat as a
 * known limitation and fall back to the breakpoint-patch technique in
 * SKILL.md's "Sandbox Bypass" section instead).
 *
 * If LoadLibraryExW itself fails here, the failure is in the OS loader, not
 * this harness -- record the exact GetLastError and move on; retrying will
 * not change the outcome. This was reproduced against sample
 * 00c5240f41d311ed58e92f805d915359e1d202e9ef9cf7f567519907868947c8 via
 * LoadLibraryExW, LoadLibraryA, and LoadLibraryExA(DONT_RESOLVE_DLL_REFERENCES)
 * -- all three failed with GetLastError=126 (ERROR_MOD_NOT_FOUND) despite the
 * file being byte-identical to the host copy (verified by hash) and having a
 * well-formed, unremarkable PE header/section table. Windows Defender was
 * confirmed disabled on the guest at the time. A control DLL
 * (C:\Windows\SysWOW64\shell32.dll) loaded successfully through the same
 * harness in the same guest session, so the block is specific to that file,
 * not a defect in this harness or the guest's general LoadLibrary path.
 * Cause not fully root-caused; treat recurrence of this exact symptom
 * (LoadLibraryExW fails with 126 on a hash-verified, structurally-normal PE)
 * as a stage-level `status: "blocked"` rather than retrying.
 *
 * Never run outside the isolated guest VM.
 */
#include <windows.h>
#include <stdio.h>

typedef void (WINAPI *PushGlobals_t)(void *);
typedef void (WINAPI *ServiceMainW_t)(DWORD, LPWSTR *);

static FILE *g_log = NULL;

static void logmsg(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    if (g_log) { vfprintf(g_log, fmt, ap); fprintf(g_log, "\n"); fflush(g_log); }
    va_end(ap);
}

static DWORD WINAPI call_service_main(LPVOID param) {
    HMODULE h = (HMODULE)param;
    __try {
        ServiceMainW_t smw = (ServiceMainW_t)GetProcAddress(h, "ServiceMain");
        if (smw) {
            logmsg("[stub] calling ServiceMain(1, [\"stub_service\"])");
            LPWSTR argv[1] = { L"stub_service" };
            smw(1, argv);
            logmsg("[stub] ServiceMain returned (unexpected for a resident service)");
        } else {
            logmsg("[stub] no ServiceMain export found");
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        logmsg("[stub] ServiceMain raised exception 0x%08lX", GetExceptionCode());
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <dll_path> [log_path] [keep_alive_seconds]\n", argv[0]);
        return 1;
    }
    const char *log_path = argc >= 3 ? argv[2] : "svchost_stub.log";
    int keep_alive = argc >= 4 ? atoi(argv[3]) : 120;
    g_log = fopen(log_path, "w");
    logmsg("[stub] pid=%lu loading %s", GetCurrentProcessId(), argv[1]);

    wchar_t wpath[MAX_PATH];
    MultiByteToWideChar(CP_ACP, 0, argv[1], -1, wpath, MAX_PATH);
    HMODULE h = LoadLibraryExW(wpath, NULL, 0);
    if (!h) {
        DWORD err = GetLastError();
        logmsg("[stub] LoadLibraryExW failed, GetLastError=%lu", err);
        HANDLE fh = CreateFileW(wpath, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (fh == INVALID_HANDLE_VALUE) {
            logmsg("[stub] CreateFileW also failed, GetLastError=%lu -> path/permission problem, not a loader-level block", GetLastError());
        } else {
            logmsg("[stub] CreateFileW ok, size=%lu -> file is readable; the block is in the PE loader, not file access", GetFileSize(fh, NULL));
            CloseHandle(fh);
        }
        return 2;
    }
    logmsg("[stub] LoadLibraryExW ok, base=%p", (void *)h);

    __try {
        PushGlobals_t push = (PushGlobals_t)GetProcAddress(h, "SvchostPushServiceGlobals");
        if (push) {
            logmsg("[stub] calling SvchostPushServiceGlobals(NULL)");
            push(NULL);
            logmsg("[stub] SvchostPushServiceGlobals returned");
        } else {
            logmsg("[stub] no SvchostPushServiceGlobals export found");
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        logmsg("[stub] SvchostPushServiceGlobals raised exception 0x%08lX", GetExceptionCode());
    }

    /* Run ServiceMain on its own thread so a blocking service loop does not
     * prevent this harness process (and an attached debugger) from staying
     * alive and observable. */
    if (!CreateThread(NULL, 0, call_service_main, (LPVOID)h, 0, NULL)) {
        logmsg("[stub] CreateThread for ServiceMain failed, GetLastError=%lu", GetLastError());
    }

    logmsg("[stub] entering keep-alive wait loop (%ds)", keep_alive);
    for (int i = 0; i < keep_alive; i++) {
        Sleep(1000);
    }
    logmsg("[stub] keep-alive loop finished, exiting");
    return 0;
}
