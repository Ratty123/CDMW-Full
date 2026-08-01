<#
.SYNOPSIS
    Build the Qt Quick RHI viewport plugin against the Qt that PySide6 ships.

.DESCRIPTION
    The Mesh Editor viewport is moving from an embedded child window to a node
    inside Qt Quick's scene graph. That node is a C++ QQuickRhiItem, and it
    calls QRhi, which lives in Qt's GuiPrivate module. Private modules carry no
    binary compatibility promise, so the plugin is only valid against the exact
    Qt build that loads it -- the one inside the installed PySide6 wheel.

    This script keeps those two in step: it asks PySide6 which Qt it has,
    vendors that exact version if it is missing, and configures CMake with a
    guard that fails the build if the two ever disagree.

.PARAMETER Reconfigure
    Discard the CMake cache and configure from scratch.

.PARAMETER SkipVendor
    Assume the Qt SDK is already vendored, and fail if it is not.
#>
[CmdletBinding()]
param(
    [switch]$Reconfigure,
    [switch]$SkipVendor
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PluginDir = Join-Path $RepoRoot "native\cdmw_qt_rhi"
$BuildDir = Join-Path $PluginDir "build"

if (-not (Test-Path $Python)) {
    throw "No interpreter at $Python; the plugin has to match that venv's PySide6."
}

$QtVersion = (& $Python -c "from PySide6 import QtCore; print(QtCore.qVersion())").Trim()
if (-not $QtVersion) { throw "PySide6 did not report a Qt version." }
Write-Host "PySide6 ships Qt $QtVersion"

if (-not $SkipVendor) {
    & $Python (Join-Path $PSScriptRoot "vendor_qt_sdk.py") --qt-version $QtVersion
    if ($LASTEXITCODE -ne 0) { throw "Vendoring Qt $QtVersion failed." }
}

$QtPrefix = (& $Python (Join-Path $PSScriptRoot "vendor_qt_sdk.py") --qt-version $QtVersion --print-prefix).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $QtPrefix)) {
    throw "No vendored Qt $QtVersion. Run scripts\vendor_qt_sdk.py."
}
Write-Host "Qt SDK      $QtPrefix"

# The MSVC environment has to be the one Qt was built with.
$vsRoot = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022"
$vcvars = Get-ChildItem -Path $vsRoot -Recurse -Filter "vcvars64.bat" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $vcvars) {
    throw "vcvars64.bat not found under $vsRoot; install the MSVC 2022 C++ build tools."
}

if ($Reconfigure -and (Test-Path $BuildDir)) {
    Remove-Item -Recurse -Force $BuildDir
}

$prefixArg = $QtPrefix -replace '\\', '/'
$configure = "cmake -S . -B build -G Ninja " +
    "-DCMAKE_PREFIX_PATH=`"$prefixArg`" " +
    "-DCMAKE_BUILD_TYPE=Release " +
    "-DCDMW_EXPECTED_QT_VERSION=$QtVersion"

# stderr is merged inside cmd: CMake writes ordinary progress and warnings
# there, and PowerShell would otherwise treat each line as a native command
# failure. The exit code is the thing that decides success.
& cmd /c "`"$vcvars`" >nul 2>&1 && cd /d `"$PluginDir`" && $configure 2>&1 && cmake --build build 2>&1"
if ($LASTEXITCODE -ne 0) { throw "Plugin build failed." }

$module = Join-Path $BuildDir "qml\CdmwQtRhi\cdmwqtrhi.dll"
if (-not (Test-Path $module)) { throw "Build reported success but $module is missing." }
Write-Host ""
Write-Host "Built $module"
Write-Host "QML import path: $(Join-Path $BuildDir 'qml')"
