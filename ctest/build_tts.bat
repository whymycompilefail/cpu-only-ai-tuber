@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
rem Source lives in the cpu-afterburner repo (single source of truth).
if not defined LLAMA_DIR set "LLAMA_DIR=%ROOT%\..\cpu-afterburner\llama.cpp"
if not exist "%LLAMA_DIR%\CMakeLists.txt" (echo NO_LLAMA_SOURCE & echo   set LLAMA_DIR or clone cpu-afterburner & exit /b 1)
cd /d "%LLAMA_DIR%"
cmake --build build --target llama-tts -j 12
echo BUILD_EXIT=%ERRORLEVEL%
