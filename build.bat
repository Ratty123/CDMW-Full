@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if /i "%~1"=="help" goto :help
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
if /i "%~1"=="/?" goto :help
if /i "%~1"=="gui" goto :gui

if "%~1"=="" goto :gui

if not "%~3"=="" (
    echo Unexpected extra argument "%~3".
    echo Use: build.bat [onefile^|onedir] [release^|fast^|debug]
    exit /b 1
)

set "MODE=%~1"
set "PROFILE=%~2"
if "%PROFILE%"=="" set "PROFILE=release"

call :valid
if errorlevel 1 exit /b 1

call :run
exit /b %ERRORLEVEL%

:gui
set "PY_GUI=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY_GUI%" set "PY_GUI=%~dp0.venv\Scripts\python.exe"
if exist "%PY_GUI%" (
    start "" "%PY_GUI%" "%~dp0build_gui.py"
    exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0build_gui.py"
    exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    start "" python "%~dp0build_gui.py"
    exit /b 0
)
echo Python was not found. Install Python or run from the project virtual environment.
exit /b 1

:menu
set "MODE="
set "PROFILE="
set "PACKAGE_CHOICE="
set "PROFILE_CHOICE="
set "CONFIRM="
cls
echo Crimson Desert Mod Workbench Builder
echo.
echo Choose a package type:
echo   1. Onefile - one portable EXE; slower to build/start; best for sharing.
echo   2. Onedir  - release folder; faster to build/start; best for testing.
echo   Q. Quit
echo.
set /p "PACKAGE_CHOICE=Package type [1/2/Q]: "
if /i "%PACKAGE_CHOICE%"=="Q" exit /b 0
if "%PACKAGE_CHOICE%"=="1" set "MODE=onefile"
if "%PACKAGE_CHOICE%"=="2" set "MODE=onedir"
if not defined MODE (
    echo.
    echo Invalid package type.
    echo.
    pause
    goto :menu
)

echo.
echo Choose a build profile:
echo   1. Release - clean, windowed, validated; use for publishing.
echo   2. Fast    - incremental PyInstaller build; native helpers still rebuild; skips onefile archive validation.
echo   3. Debug   - clean, console-enabled, verbose PyInstaller logs; use for troubleshooting.
echo   Q. Quit
echo.
set /p "PROFILE_CHOICE=Build profile [1/2/3/Q]: "
if /i "%PROFILE_CHOICE%"=="Q" exit /b 0
if "%PROFILE_CHOICE%"=="1" set "PROFILE=release"
if "%PROFILE_CHOICE%"=="2" set "PROFILE=fast"
if "%PROFILE_CHOICE%"=="3" set "PROFILE=debug"
if not defined PROFILE (
    echo.
    echo Invalid build profile.
    echo.
    pause
    goto :menu
)

call :valid
if errorlevel 1 (
    echo.
    pause
    goto :menu
)

echo.
echo Selected build:
echo   Package: %MODE%
echo   Profile: %PROFILE%
echo.
call :describe
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
set /p "CONFIRM=Run this build? [Y/N]: "
if /i not "%CONFIRM%"=="Y" exit /b 0

call :run
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
    echo Build failed with exit code %EXITCODE%.
) else (
    echo Build finished successfully.
)
echo.
pause
exit /b %EXITCODE%

:valid
if /i "%MODE%"=="onefile" set "MODE=onefile"
if /i "%MODE%"=="onedir" set "MODE=onedir"
if /i "%PROFILE%"=="release" set "PROFILE=release"
if /i "%PROFILE%"=="fast" set "PROFILE=fast"
if /i "%PROFILE%"=="debug" set "PROFILE=debug"

if /i not "%MODE%"=="onefile" if /i not "%MODE%"=="onedir" (
    echo Invalid package type "%MODE%".
    echo Use: build.bat [onefile^|onedir] [release^|fast^|debug]
    exit /b 1
)

if /i not "%PROFILE%"=="release" if /i not "%PROFILE%"=="fast" if /i not "%PROFILE%"=="debug" (
    echo Invalid build profile "%PROFILE%".
    echo Use: build.bat [onefile^|onedir] [release^|fast^|debug]
    exit /b 1
)

exit /b 0

:pscheck
where powershell >nul 2>nul
if errorlevel 1 (
    echo PowerShell was not found on PATH.
    exit /b 1
)
exit /b 0

:describe
call :pscheck
if errorlevel 1 exit /b 1
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_pyside6_app.ps1" -Mode %MODE% -BuildProfile %PROFILE% -DescribeOnly <nul
exit /b %ERRORLEVEL%

:run
call :pscheck
if errorlevel 1 exit /b 1
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_pyside6_app.ps1" -Mode %MODE% -BuildProfile %PROFILE% <nul
exit /b %ERRORLEVEL%

:help
echo Crimson Desert Mod Workbench Builder
echo.
echo Usage:
echo   build.bat
echo   build.bat gui
echo   build.bat help
echo   build.bat onefile release
echo   build.bat onefile fast
echo   build.bat onefile debug
echo   build.bat onedir release
echo   build.bat onedir fast
echo   build.bat onedir debug
echo.
echo Package types:
echo   onefile  Builds one portable EXE. Slower to build/start, best for sharing.
echo   onedir   Builds a folder. Faster to build/start, best for local testing.
echo.
echo Build profiles:
echo   release  Clean, windowed, validates onefile archives. Use for publishing.
echo   fast     Incremental PyInstaller build; native helpers still rebuild incrementally.
echo   debug    Clean, console-enabled, verbose PyInstaller logs. Use for troubleshooting.
echo.
echo Running build.bat without arguments opens the graphical builder.
echo.
echo Automation can call build_pyside6_app.ps1 directly:
echo   powershell -NoProfile -ExecutionPolicy Bypass -File build_pyside6_app.ps1 -Mode onefile -BuildProfile release
exit /b 0
