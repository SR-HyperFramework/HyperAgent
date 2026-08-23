@echo off
rem Build svchost_stub.c as a 32-bit (x86) EXE, matching the sample DLLs this
rem harness hosts. Requires MSVC Build Tools with the x86 target installed
rem (vcvarsamd64_x86.bat must exist under VC\Auxiliary\Build). Run once on the
rem host; copy the resulting svchost_stub32.exe into the guest and rename it
rem to svchost.exe before use (see SKILL.md "DLL and service-DLL samples").
setlocal
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsamd64_x86.bat
if not exist "%VCVARS%" (
  echo vcvarsamd64_x86.bat not found at expected path -- locate your MSVC Build Tools install and edit this script.
  exit /b 1
)
call "%VCVARS%"
cd /d "%~dp0"
cl.exe /nologo /O2 /D_CRT_SECURE_NO_WARNINGS svchost_stub.c /link /nologo /OUT:svchost_stub32.exe
echo BUILD_EXIT=%ERRORLEVEL%
