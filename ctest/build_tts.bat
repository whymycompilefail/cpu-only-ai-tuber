@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
rem Source is not in this repo: cpu-afterburner ships the patch.
if not defined LLAMA_DIR set "LLAMA_DIR=%ROOT%\..\llama-cpp"
if not exist "%LLAMA_DIR%\CMakeLists.txt" if exist "%ROOT%\llama.cpp\CMakeLists.txt" set "LLAMA_DIR=%ROOT%\llama.cpp"
cd /d "%LLAMA_DIR%"
cmake --build build --target llama-tts -j 12
echo BUILD_EXIT=%ERRORLEVEL%
