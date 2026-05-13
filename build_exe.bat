@echo off
setlocal

cd /d "%~dp0"

set "MODE=%~1"
if /i "%MODE%"=="" set "MODE=onefile"
set "PROFILE=%~2"
if /i "%PROFILE%"=="" set "PROFILE=release"

if /i not "%MODE%"=="onefile" if /i not "%MODE%"=="onedir" (
    echo Invalid build mode "%MODE%".
    echo Use: build_exe.bat [onefile^|onedir] [release^|fast^|debug]
    echo.
    pause
    exit /b 1
)

if /i not "%PROFILE%"=="release" if /i not "%PROFILE%"=="fast" if /i not "%PROFILE%"=="debug" (
    echo Invalid build profile "%PROFILE%".
    echo Use: build_exe.bat [onefile^|onedir] [release^|fast^|debug]
    echo.
    pause
    exit /b 1
)

echo Building Crimson Desert Mod Workbench in %MODE%/%PROFILE% mode...
echo.

call "%~dp0build.bat" %MODE% %PROFILE%
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo Build failed with exit code %EXITCODE%.
    echo.
    pause
    exit /b %EXITCODE%
)

echo Build finished successfully.
echo.
pause
exit /b 0
