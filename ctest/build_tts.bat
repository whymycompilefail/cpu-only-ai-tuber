@echo off
for %%I in ("%~dp0..") do set "ROOT=%%~fI"   &:: repo root, derived from this file
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
cd /d %ROOT%\llama.cpp
cmake --build build --target llama-tts -j 12
echo BUILD_EXIT=%ERRORLEVEL%
