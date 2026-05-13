@echo off
setlocal

cd /d "%~dp0"

echo Building Crimson Desert Mod Workbench in folder/onedir mode...
echo This creates a release folder instead of a single self-extracting EXE.
echo.

call "%~dp0build.bat" onedir release
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
