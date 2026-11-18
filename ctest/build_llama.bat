@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
rem Manual MSVC x64 environment - avoids vcvars64.bat (blocked reg.exe)
set MSVC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207
set SDK=C:\Program Files (x86)\Windows Kits\10
set SDKV=10.0.26100.0
set PATH=%MSVC%\bin\Hostx64\x64;%SDK%\bin\%SDKV%\x64;%ROOT%\.venv\Scripts;%PATH%
set INCLUDE=%SDK%\Include\%SDKV%\ucrt;%SDK%\Include\%SDKV%\um;%SDK%\Include\%SDKV%\shared;%SDK%\Include\%SDKV%\winrt;%SDK%\Include\%SDKV%\cppwinrt;%MSVC%\include
set LIB=%SDK%\Lib\%SDKV%\um\x64;%SDK%\Lib\%SDKV%\ucrt\x64;%MSVC%\lib\x64
rem No CMAKE_MT/CMAKE_RC override: the SDK dir is on PATH below anyway, and
rem passing it as -D breaks CMake escape parsing ("\P" in "Program Files").

rem --- 1) minimal sanity project ---
cd /d %ROOT%\ctest
if exist bn rmdir /s /q bn
cmake -S . -B bn -G Ninja -DCMAKE_BUILD_TYPE=Release >nul 2>&1
if errorlevel 1 (echo MINIMAL_CONFIGURE_FAILED & exit /b 1)
cmake --build bn >nul 2>&1
if errorlevel 1 (echo MINIMAL_BUILD_FAILED & exit /b 1)
echo MINIMAL_OK

rem --- 2) llama.cpp configure + build ---
rem Source is NOT in this repo any more: it comes from cpu-afterburner (patch).
rem   git clone https://github.com/whymycompilefail/cpu-afterburner
rem   DEST=<path> bash cpu-afterburner/scripts/setup.sh
rem Lookup: LLAMA_DIR > <repo>\..\cpu-afterburner\llama.cpp (single source of truth)
if not defined LLAMA_DIR set "LLAMA_DIR=%ROOT%\..\cpu-afterburner\llama.cpp"
if not exist "%LLAMA_DIR%\CMakeLists.txt" if exist "%ROOT%\..\cpu-afterburner\llama.cpp\CMakeLists.txt" set "LLAMA_DIR=%ROOT%\..\cpu-afterburner\llama.cpp"
if not exist "%LLAMA_DIR%\CMakeLists.txt" (echo NO_LLAMA_SOURCE & echo   set LLAMA_DIR or run cpu-afterburner/scripts/setup.sh & exit /b 1)
echo LLAMA_DIR=%LLAMA_DIR%
if exist "%LLAMA_DIR%\build" rmdir /s /q "%LLAMA_DIR%\build"
cmake -S "%LLAMA_DIR%" -B "%LLAMA_DIR%\build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF
if errorlevel 1 (echo LLAMA_CONFIGURE_FAILED & exit /b 1)
cmake --build "%LLAMA_DIR%\build" -j 8
if errorlevel 1 (echo LLAMA_BUILD_FAILED & exit /b 1)
echo LLAMA_BUILD_OK
