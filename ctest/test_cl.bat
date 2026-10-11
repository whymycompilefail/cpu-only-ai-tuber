@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
where cl || (echo NO_CL & exit /b 1)
cl 2>&1 | findstr /C:"Version"
echo CL_TEST_DONE
