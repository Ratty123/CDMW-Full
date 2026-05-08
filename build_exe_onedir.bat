@echo off
setlocal

cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo PowerShell was not found on PATH.
    echo.
    pause
    exit /b 1
)

echo Building Crimson Desert Mod Workbench in folder/onedir mode...
echo This creates a release folder instead of a single self-extracting EXE.
echo.

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_pyside6_app.ps1" -Mode onedir
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo Folder build failed with exit code %EXITCODE%.
    echo.
    pause
    exit /b %EXITCODE%
)

echo Folder build finished successfully.
echo Output should be under:
echo   %~dp0dist\CrimsonDesertModWorkbench-*-windows
echo.
pause
exit /b 0
