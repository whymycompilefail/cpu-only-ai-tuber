@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
set PATH=%ROOT%\.venv\Scripts;%PATH%
cd /d %ROOT%\ctest
if exist bn rmdir /s /q bn
cmake -S . -B bn -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_MT="C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/mt.exe" -DCMAKE_RC_COMPILER="C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/rc.exe"
echo CONFIGURE_EXIT=%ERRORLEVEL%
cmake --build bn
echo BUILD_EXIT=%ERRORLEVEL%
