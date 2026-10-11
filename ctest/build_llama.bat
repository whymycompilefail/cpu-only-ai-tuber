@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
rem Manual MSVC x64 environment - avoids vcvars64.bat (blocked reg.exe)
set MSVC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207
set SDK=C:\Program Files (x86)\Windows Kits\10
set SDKV=10.0.26100.0
set PATH=%MSVC%\bin\Hostx64\x64;%SDK%\bin\%SDKV%\x64;%ROOT%\.venv\Scripts;%PATH%
set INCLUDE=%SDK%\Include\%SDKV%\ucrt;%SDK%\Include\%SDKV%\um;%SDK%\Include\%SDKV%\shared;%SDK%\Include\%SDKV%\winrt;%SDK%\Include\%SDKV%\cppwinrt;%MSVC%\include
set LIB=%SDK%\Lib\%SDKV%\um\x64;%SDK%\Lib\%SDKV%\ucrt\x64;%MSVC%\lib\x64
set CMAKE_MT_PATH=%SDK%/bin/%SDKV%/x64/mt.exe
set CMAKE_RC_PATH=%SDK%/bin/%SDKV%/x64/rc.exe

rem --- 1) minimal sanity project ---
cd /d %ROOT%\ctest
if exist bn rmdir /s /q bn
cmake -S . -B bn -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_MT="%CMAKE_MT_PATH%" -DCMAKE_RC_COMPILER="%CMAKE_RC_PATH%" >nul 2>&1
if errorlevel 1 (echo MINIMAL_CONFIGURE_FAILED & exit /b 1)
cmake --build bn >nul 2>&1
if errorlevel 1 (echo MINIMAL_BUILD_FAILED & exit /b 1)
echo MINIMAL_OK

rem --- 2) llama.cpp configure + build ---
if exist %ROOT%\llama.cpp\build rmdir /s /q %ROOT%\llama.cpp\build
cmake -S %ROOT%\llama.cpp -B %ROOT%\llama.cpp\build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF -DCMAKE_MT="%CMAKE_MT_PATH%" -DCMAKE_RC_COMPILER="%CMAKE_RC_PATH%"
if errorlevel 1 (echo LLAMA_CONFIGURE_FAILED & exit /b 1)
cmake --build %ROOT%\llama.cpp\build -j 8
if errorlevel 1 (echo LLAMA_BUILD_FAILED & exit /b 1)
echo LLAMA_BUILD_OK
