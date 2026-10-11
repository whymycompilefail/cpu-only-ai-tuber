#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Manual MSVC x64 toolchain env for sandboxed bash (vcvars64.bat blocked: reg.exe).
# Source this before cmake/ninja commands.
export MSVC="/c/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207"
export WSDK="/c/Program Files (x86)/Windows Kits/10"
export SDKV="10.0.26100.0"
export PATH="$MSVC/bin/Hostx64/x64:$WSDK/bin/$SDKV/x64:$ROOT/.venv/Scripts:$PATH"
export INCLUDE='C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\winrt;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\cppwinrt;C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include'
export LIB='C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64;C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64'
export CMAKE_MT='C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/mt.exe'
export RC='C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/rc.exe'
