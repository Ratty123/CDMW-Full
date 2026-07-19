@echo off
setlocal
title CDMW Archive Lite - Fresh EXE Build

cd /d "%~dp0"

echo Building a fresh CDMW Archive Lite standalone executable...
echo This can take a few minutes.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_archive_lite.ps1"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
echo.

if not "%BUILD_EXIT_CODE%"=="0" goto build_failed

echo BUILD COMPLETED SUCCESSFULLY.
echo The fresh executable is in:
echo   %~dp0artifacts
echo.
pause
exit /b 0

:build_failed
echo BUILD FAILED with exit code %BUILD_EXIT_CODE%.
echo Scroll up to see the first reported error.
echo.
pause
exit /b %BUILD_EXIT_CODE%
