@echo off
setlocal enabledelayedexpansion
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file

rem ===========================================================================
rem Hand-rolled MSVC x64 environment. vcvars64.bat cannot be used here: it
rem depends on reg.exe, which the local security policy blocks.
rem
rem NOTE: this file must stay ASCII-only. A .bat written as UTF-8 with CJK
rem comments breaks on a GBK console: multi-byte UTF-8 sequences can contain
rem 0x5C / 0x28 / 0x29 bytes, and cmd parses those as \ ( ) syntax.
rem
rem No version numbers are hardcoded, so a VS 2022 -> 2026 upgrade (or
rem uninstalling the old one) needs no edit here:
rem   - install root: ask vswhere for the newest install (incl. Build Tools);
rem     if vswhere is absent, scan C:\Program Files\Microsoft Visual Studio\
rem     <year-or-18>\<edition> instead. VS 2026 uses "18", not a year.
rem   - toolset: newest VC\Tools\MSVC\14.* inside that install
rem   - SDK: newest Windows Kits\10\Include\10.0.* (its root is version-stable)
rem
rem Pin a specific toolset (for A/B tests):
rem   set MSVC_DIR=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207
rem   set SDK_VER=10.0.26100.0
rem ===========================================================================
set "VSRT=C:\Program Files\Microsoft Visual Studio"
set "SDK=C:\Program Files (x86)\Windows Kits\10"

rem --- 1) locate the MSVC toolset ---
if not defined MSVC_DIR (
    set "VSPATH="
    set "VSWHERE=C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if exist "!VSWHERE!" (
        for /f "usebackq delims=" %%P in (`"!VSWHERE!" -latest -products * -property installationPath`) do set "VSPATH=%%P"
    )
    set "BESTV=" & set "BESTP="
    if defined VSPATH (
        for /d %%C in ("!VSPATH!\VC\Tools\MSVC\14.*") do (
            set "N=%%~nxC"
            if "!N!" GTR "!BESTV!" (set "BESTV=!N!" & set "BESTP=%%~C")
        )
    ) else (
        rem no vswhere: take the globally newest toolset across all installs
        for /d %%A in ("%VSRT%\*") do (
            for /d %%B in ("%%A\*") do (
                for /d %%C in ("%%B\VC\Tools\MSVC\14.*") do (
                    set "N=%%~nxC"
                    if "!N!" GTR "!BESTV!" (set "BESTV=!N!" & set "BESTP=%%~C")
                )
            )
        )
    )
    set "MSVC_DIR=!BESTP!"
)
if not defined MSVC_DIR (
    echo NO_MSVC_TOOLSET
    echo   Install the "Desktop development with C++" workload, or set MSVC_DIR=...\VC\Tools\MSVC\14.xx.yyyyy
    exit /b 1
)

rem --- 2) locate the Windows SDK ---
if defined SDK_VER (set "SDKV=%SDK_VER%") else (set "SDKV=")
if not defined SDKV (
    set "BESTV="
    for /d %%D in ("%SDK%\Include\10.0.*") do (
        set "N=%%~nxD"
        if "!N!" GTR "!BESTV!" set "BESTV=!N!"
    )
    set "SDKV=!BESTV!"
)
if not defined SDKV (
    echo NO_WINDOWS_SDK
    echo   Nothing under !SDK!\Include\10.0.* ; or set SDK_VER=10.0.26100.0
    exit /b 1
)

rem --- 3) assemble the environment ---
set "PATH=%MSVC_DIR%\bin\Hostx64\x64;%SDK%\bin\%SDKV%\x64;%ROOT%\.venv\Scripts;%PATH%"
set "INCLUDE=%SDK%\Include\%SDKV%\ucrt;%SDK%\Include\%SDKV%\um;%SDK%\Include\%SDKV%\shared;%SDK%\Include\%SDKV%\winrt;%SDK%\Include\%SDKV%\cppwinrt;%MSVC_DIR%\include"
set "LIB=%SDK%\Lib\%SDKV%\um\x64;%SDK%\Lib\%SDKV%\ucrt\x64;%MSVC_DIR%\lib\x64"
rem Do NOT pass -DCMAKE_MT / -DCMAKE_RC_COMPILER: the SDK bin dir is already on
rem PATH, and passing it as a -D makes CMake treat \P in "C:\Program Files" as
rem an escape sequence -> "Invalid character escape '\P'".
echo MSVC_DIR=%MSVC_DIR%
echo SDK=%SDKV%

where cl >nul 2>&1 || (echo NO_CL_ON_PATH & exit /b 1)
for /f "tokens=*" %%V in ('cl 2^>^&1 ^| findstr /c:"19."') do set "CLVER=%%V"
echo CL=%CLVER%

rem --- 4) minimal sanity project: prove the toolchain can compile AND link
rem        before touching the big one ---
cd /d %ROOT%\ctest
if exist bn rmdir /s /q bn
cmake -S . -B bn -G Ninja -DCMAKE_BUILD_TYPE=Release >nul 2>&1
if errorlevel 1 (echo MINIMAL_CONFIGURE_FAILED & exit /b 1)
cmake --build bn >nul 2>&1
if errorlevel 1 (echo MINIMAL_BUILD_FAILED & exit /b 1)
echo MINIMAL_OK

rem --- 5) full llama.cpp rebuild ---
rem Source is not in this repo: the single source of truth is
rem cpu-afterburner/llama.cpp (sources vendored; no upstream clone, no patch).
rem The build lands in that tree's build/ directory.
rem   bash cpu-afterburner/scripts/setup.sh     (equivalent entry, needs a dev prompt)
if not defined LLAMA_DIR set "LLAMA_DIR=%ROOT%\..\cpu-afterburner\llama.cpp"
if not exist "%LLAMA_DIR%\CMakeLists.txt" (echo NO_LLAMA_SOURCE & echo   expected at !ROOT!\..\cpu-afterburner\llama.cpp, or set LLAMA_DIR=... & exit /b 1)
echo LLAMA_DIR=%LLAMA_DIR%
if exist "%LLAMA_DIR%\build" rmdir /s /q "%LLAMA_DIR%\build"
cmake -S "%LLAMA_DIR%" -B "%LLAMA_DIR%\build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF
if errorlevel 1 (echo LLAMA_CONFIGURE_FAILED & exit /b 1)
cmake --build "%LLAMA_DIR%\build" -j 8
if errorlevel 1 (echo LLAMA_BUILD_FAILED & exit /b 1)
echo LLAMA_BUILD_OK
