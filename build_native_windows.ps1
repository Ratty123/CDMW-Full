param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw "vswhere.exe was not found. Install Visual Studio Build Tools 2022 with MSVC and CMake components."
}

$vsRoot = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if (-not $vsRoot) {
    throw "Visual Studio Build Tools with MSVC x64 tools were not found."
}

$vcvars = Join-Path $vsRoot "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path -LiteralPath $vcvars)) {
    throw "vcvars64.bat was not found under '$vsRoot'."
}

$cmake = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if (-not (Test-Path -LiteralPath $cmake)) {
    $cmake = "cmake"
}

function Invoke-NativeBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [string]$ExeRelativePath
    )

    $buildDir = Join-Path $ProjectDir "build"
    if ($Clean -and (Test-Path -LiteralPath $buildDir)) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

    $configure = "`"$vcvars`" && `"$cmake`" -S `"$ProjectDir`" -B `"$buildDir`" -G `"Visual Studio 17 2022`" -A x64"
    $build = "`"$vcvars`" && `"$cmake`" --build `"$buildDir`" --config $Configuration"
    cmd.exe /d /s /c $configure
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configure failed for $ProjectDir with exit code $LASTEXITCODE."
    }
    cmd.exe /d /s /c $build
    if ($LASTEXITCODE -ne 0) {
        throw "Native build failed for $ProjectDir with exit code $LASTEXITCODE."
    }

    $exePath = Join-Path $ProjectDir $ExeRelativePath
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Native build completed but expected binary is missing: $exePath"
    }
    Write-Host "Built native binary: $exePath"
}

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cd_texture_dx") `
    -ExeRelativePath ("build\$Configuration\cd-texture-dx.exe")

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cdmw_d3d11_preview") `
    -ExeRelativePath ("build\$Configuration\cdmw-d3d11-preview.exe")
