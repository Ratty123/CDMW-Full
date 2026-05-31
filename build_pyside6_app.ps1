param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onefile",
    [ValidateSet("release", "fast", "debug")]
    [string]$BuildProfile = "release",
    [switch]$SkipNativeBuild,
    [switch]$DescribeOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$appName = "CrimsonDesertModWorkbench"
$legacyAppNames = @("DDSRebuildApp")

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$stableDistDir = Join-Path $scriptDir "dist"
$stableBuildDir = Join-Path $scriptDir "build"
$buildFlavor = "$Mode-$BuildProfile"
$pyInstallerDistDir = Join-Path $stableBuildDir "pyinstaller-dist-$buildFlavor"
$pyInstallerWorkDir = Join-Path $stableBuildDir "pyinstaller-work-$buildFlavor"
$specPath = Join-Path $scriptDir "CrimsonDesertModWorkbench.spec"
$vgmstreamRuntimeDir = Join-Path $scriptDir ".tools\vgmstream"
$vgmstreamDownloadUrl = "https://github.com/bnnm/vgmstream-builds/raw/master/bin/vgmstream-latest-test-u.zip"

function Remove-PathWithRetries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,
        [switch]$Recurse,
        [int]$RetryCount = 8,
        [int]$DelayMilliseconds = 400
    )

    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return
    }

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            if ($Recurse) {
                Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
            }
            return
        } catch {
            if ($attempt -ge $RetryCount) {
                throw "Failed to remove '$LiteralPath' after $RetryCount attempt(s): $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }
}

function Move-PathWithRetries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,
        [int]$RetryCount = 8,
        [int]$DelayMilliseconds = 400
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Source path does not exist: $SourcePath"
    }

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            Move-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -ge $RetryCount) {
                throw "Failed to move '$SourcePath' to '$DestinationPath' after $RetryCount attempt(s): $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }
}

function Stop-AppProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$NamePrefixes
    )

    $targets = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $processName = $_.ProcessName
        foreach ($prefix in $NamePrefixes) {
            if ($processName -like "$prefix*") {
                return $true
            }
        }
        return $false
    } | Sort-Object Id -Unique)

    if (-not $targets) {
        return
    }

    Write-Host "Stopping running build targets..."
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not stop process $($proc.ProcessName) [$($proc.Id)]: $($_.Exception.Message)"
        }
    }

    foreach ($proc in $targets) {
        try {
            Wait-Process -Id $proc.Id -Timeout 10 -ErrorAction Stop
        } catch {
            if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
                throw "Process '$($proc.ProcessName)' [$($proc.Id)] is still running after stop was requested."
            }
        }
    }
}

function Ensure-VgmstreamRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeDir
    )

    $cliPath = Join-Path $RuntimeDir "vgmstream-cli.exe"
    if (Test-Path -LiteralPath $cliPath) {
        return $RuntimeDir
    }

    $zipPath = Join-Path $env:TEMP "vgmstream-latest-test-u.zip"
    $extractDir = Join-Path $stableBuildDir "vgmstream-extract"

    Write-Host "Downloading vgmstream runtime..."
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    Remove-PathWithRetries -LiteralPath $extractDir -Recurse
    Invoke-WebRequest -Uri $vgmstreamDownloadUrl -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $runtimeFiles = Get-ChildItem -LiteralPath $extractDir -File | Where-Object {
        $_.Name -eq "vgmstream-cli.exe" -or $_.Extension -ieq ".dll" -or $_.Name -eq "COPYING"
    }
    if (-not $runtimeFiles) {
        throw "Downloaded vgmstream archive did not contain the expected runtime files."
    }

    foreach ($file in $runtimeFiles) {
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $RuntimeDir $file.Name) -Force
    }

    if (-not (Test-Path -LiteralPath $cliPath)) {
        throw "vgmstream runtime download completed, but vgmstream-cli.exe is still missing."
    }

    return $RuntimeDir
}

function Test-OnefileArchiveIntegrity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$ExePath
    )

    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "Cannot validate onefile archive because the EXE does not exist: $ExePath"
    }

$validationScript = @'
from pathlib import Path
import sys

from PyInstaller.archive.readers import CArchiveReader

exe_path = Path(sys.argv[1])
archive = CArchiveReader(str(exe_path))
names = sorted(name for name in archive.toc if name)
if not names:
    raise RuntimeError("Embedded onefile archive was empty.")

validated = 0
total = len(names)
binary_suffixes = (".dll", ".pyd", ".exe")
for index, name in enumerate(names, start=1):
    data = archive.extract(name)
    if data is None:
        raise RuntimeError(f"{name} extracted as None")
    if len(data) == 0 and name.lower().endswith(binary_suffixes):
        raise RuntimeError(f"{name} extracted as empty data")
    validated += 1
    if index % 250 == 0 or index == total:
        print(f"Validated {index}/{total} embedded archive members...")

print(f"Validated all {validated} embedded archive members.")
'@

    $validationOutput = $validationScript | & $PythonExe - $ExePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = ($validationOutput | Out-String).Trim()
        if (-not $details) {
            $details = "No validation details were returned."
        }
        throw "Onefile archive validation failed for '$ExePath'. $details"
    }

    if ($validationOutput) {
        Write-Host ($validationOutput | Out-String).Trim()
    }
}

function Invoke-PyInstallerBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$BuildMode,
        [Parameter(Mandatory = $true)]
        [string]$Profile
    )

    $previousMode = [Environment]::GetEnvironmentVariable("CDMW_PYINSTALLER_MODE", "Process")
    $previousProfile = [Environment]::GetEnvironmentVariable("CDMW_PYINSTALLER_PROFILE", "Process")
    try {
        [Environment]::SetEnvironmentVariable("CDMW_PYINSTALLER_MODE", $BuildMode, "Process")
        [Environment]::SetEnvironmentVariable("CDMW_PYINSTALLER_PROFILE", $Profile, "Process")
        & $PythonExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }
    } finally {
        [Environment]::SetEnvironmentVariable("CDMW_PYINSTALLER_MODE", $previousMode, "Process")
        [Environment]::SetEnvironmentVariable("CDMW_PYINSTALLER_PROFILE", $previousProfile, "Process")
    }
}

function Get-BuildProfileDescription {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Profile
    )

    switch ($Profile) {
        "release" { return "clean, windowed, validates onefile archives; use for publishing" }
        "fast" { return "incremental, reuses PyInstaller work cache, skips onefile archive validation; use for local iteration" }
        "debug" { return "clean, console-enabled, verbose PyInstaller logging, validates onefile archives; use for troubleshooting" }
        default { throw "Unsupported build profile: $Profile" }
    }
}

function Write-BuildProgress {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 100)]
        [int]$Percent,
        [Parameter(Mandatory = $true)]
        [string]$Stage
    )

    Write-Host "::progress::$Percent::$Stage"
}

function Test-NativeOutputsPresent {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration
    )

    $required = @(
        "native\cd_texture_dx\build\$Configuration\cd-texture-dx.exe",
        "native\cdmw_preview_core\build\$Configuration\cdmw-preview-core.exe",
        "native\cdmw_d3d11_preview\build\$Configuration\cdmw-d3d11-preview.exe",
        "native\cdmw_archive_accelerator\build\$Configuration\cdmw-archive-accelerator.exe"
    )

    foreach ($relativePath in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $scriptDir $relativePath))) {
            return $false
        }
    }
    return $true
}

function Assert-CleanPythonSitePackages {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe
    )

    if (-not ((Split-Path -Leaf $PythonExe) -like "python*")) {
        return
    }

    $sitePackages = Join-Path $scriptDir ".venv\Lib\site-packages"
    if (-not (Test-Path -LiteralPath $sitePackages)) {
        return
    }

    $copyArtifacts = @(Get-ChildItem -LiteralPath $sitePackages -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "* - Copy*"
    } | Select-Object -First 8)
    if (-not $copyArtifacts) {
        return
    }

    $examples = ($copyArtifacts | ForEach-Object { "  $($_.FullName)" }) -join [Environment]::NewLine
    throw "Refusing to package with copied dependency artifacts under .venv\Lib\site-packages. Remove or recreate the virtualenv before building. Examples:$([Environment]::NewLine)$examples"
}

function Write-BuildSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BuildMode,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    Write-Host "Build selection:"
    Write-Host "  Package: $BuildMode"
    Write-Host "  Profile: $Profile - $(Get-BuildProfileDescription -Profile $Profile)"
    Write-Host "  Spec: $specPath"
    Write-Host "  Work cache: $pyInstallerWorkDir"
    Write-Host "  Temporary output: $pyInstallerDistDir"
    Write-Host "  Final output: $OutputPath"
    Write-Host ""
}

$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "python"
}

if (-not (Test-Path -LiteralPath $specPath)) {
    throw "PyInstaller spec file not found: $specPath"
}

$appVersion = (& $pythonExe -c "from cdmw.constants import APP_VERSION; print(APP_VERSION)").Trim()
if (-not $appVersion) {
    throw "Could not determine app version from cdmw.constants.APP_VERSION"
}

if ($BuildProfile -eq "release") {
    $oneFileOutputName = "$appName-$appVersion-windows-portable.exe"
    $oneDirOutputName = "$appName-$appVersion-windows"
} else {
    $oneFileOutputName = "$appName-$appVersion-$BuildProfile-windows-portable.exe"
    $oneDirOutputName = "$appName-$appVersion-$BuildProfile-windows"
}

$finalOutputPath = if ($Mode -eq "onefile") {
    Join-Path $stableDistDir $oneFileOutputName
} else {
    Join-Path $stableDistDir $oneDirOutputName
}

Write-BuildSummary -BuildMode $Mode -Profile $BuildProfile -OutputPath $finalOutputPath
Write-BuildProgress -Percent 2 -Stage "Build plan ready"

if ($DescribeOnly) {
    return
}

Write-BuildProgress -Percent 5 -Stage "Preparing output folders"
Stop-AppProcesses -NamePrefixes @($appName, $legacyAppNames)
New-Item -ItemType Directory -Path $stableDistDir -Force | Out-Null
New-Item -ItemType Directory -Path $stableBuildDir -Force | Out-Null

Write-BuildProgress -Percent 8 -Stage "Checking bundled runtimes"
$resolvedVgmstreamRuntimeDir = Ensure-VgmstreamRuntime -RuntimeDir $vgmstreamRuntimeDir
if (-not (Test-Path -LiteralPath (Join-Path $resolvedVgmstreamRuntimeDir "vgmstream-cli.exe"))) {
    throw "vgmstream runtime is incomplete: $resolvedVgmstreamRuntimeDir"
}
Assert-CleanPythonSitePackages -PythonExe $pythonExe

if (-not $SkipNativeBuild) {
    $nativeConfig = if ($BuildProfile -eq "debug") { "Debug" } else { "Release" }
    if ($BuildProfile -eq "fast" -and (Test-NativeOutputsPresent -Configuration $nativeConfig)) {
        Write-BuildProgress -Percent 16 -Stage "Native helpers already built"
        Write-Host "Skipping native helper build for fast profile; existing $nativeConfig binaries found."
    } else {
        Write-BuildProgress -Percent 12 -Stage "Building native helpers"
        Write-Host "Building native texture and D3D11 preview helpers ($nativeConfig)..."
        $nativeBuildArgs = @{ Configuration = $nativeConfig }
        if ($BuildProfile -ne "fast") {
            $nativeBuildArgs.Clean = $true
        }
        & (Join-Path $scriptDir "build_native_windows.ps1") @nativeBuildArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Native helper build failed with exit code $LASTEXITCODE."
        }
        Write-BuildProgress -Percent 20 -Stage "Native helpers ready"
    }
} else {
    Write-Warning "Skipping native helper build. Release packaging still requires existing native binaries."
    Write-BuildProgress -Percent 16 -Stage "Native helper build skipped"
}

$pyInstallerArgs = @(
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--distpath",
    $pyInstallerDistDir,
    "--workpath",
    $pyInstallerWorkDir,
    "--log-level",
    $(if ($BuildProfile -eq "debug") { "DEBUG" } else { "INFO" }),
    $specPath
)

if ($BuildProfile -ne "fast") {
    $pyInstallerArgs = $pyInstallerArgs[0..1] + @("--clean") + $pyInstallerArgs[2..($pyInstallerArgs.Count - 1)]
}

if ($BuildProfile -ne "fast") {
    Write-BuildProgress -Percent 24 -Stage "Cleaning PyInstaller cache"
    Remove-PathWithRetries -LiteralPath (Join-Path $stableBuildDir $appName) -Recurse
    foreach ($legacyAppName in $legacyAppNames) {
        Remove-PathWithRetries -LiteralPath (Join-Path $stableBuildDir $legacyAppName) -Recurse
    }
    Remove-PathWithRetries -LiteralPath $pyInstallerWorkDir -Recurse
}
Remove-PathWithRetries -LiteralPath $pyInstallerDistDir -Recurse

Write-BuildProgress -Percent 28 -Stage "Starting PyInstaller"
Write-Host "Building $appName in $Mode/$BuildProfile mode..."
Invoke-PyInstallerBuild -PythonExe $pythonExe -Arguments $pyInstallerArgs -BuildMode $Mode -Profile $BuildProfile

if ($Mode -eq "onefile" -and $BuildProfile -ne "fast") {
    Write-BuildProgress -Percent 92 -Stage "Validating onefile archive"
    $candidateOnefileExe = Join-Path $pyInstallerDistDir "$appName.exe"
    try {
        Test-OnefileArchiveIntegrity -PythonExe $pythonExe -ExePath $candidateOnefileExe
    } catch {
        Write-Warning $_.Exception.Message
        Write-Warning "Retrying the onefile build once with a clean PyInstaller work/dist directory."
        Remove-PathWithRetries -LiteralPath $pyInstallerDistDir -Recurse
        Remove-PathWithRetries -LiteralPath $pyInstallerWorkDir -Recurse
        Invoke-PyInstallerBuild -PythonExe $pythonExe -Arguments $pyInstallerArgs -BuildMode $Mode -Profile $BuildProfile
        Test-OnefileArchiveIntegrity -PythonExe $pythonExe -ExePath $candidateOnefileExe
    }
} elseif ($Mode -eq "onefile") {
    Write-Host "Skipping onefile archive validation for fast profile."
    Write-BuildProgress -Percent 94 -Stage "Onefile validation skipped"
}

Write-BuildProgress -Percent 97 -Stage "Publishing build output"
if ($Mode -eq "onefile") {
    $builtExe = Join-Path $pyInstallerDistDir "$appName.exe"
    if (-not (Test-Path -LiteralPath $builtExe)) {
        throw "Expected build output not found: $builtExe"
    }
    Remove-PathWithRetries -LiteralPath (Join-Path $stableDistDir "$appName.exe")
    Remove-PathWithRetries -LiteralPath $finalOutputPath
    if ($BuildProfile -eq "release") {
        foreach ($legacyAppName in $legacyAppNames) {
            Remove-PathWithRetries -LiteralPath (Join-Path $stableDistDir "$legacyAppName.exe")
            Remove-PathWithRetries -LiteralPath (Join-Path $stableDistDir "$legacyAppName-$appVersion-windows-portable.exe")
        }
    }
    Move-PathWithRetries -SourcePath $builtExe -DestinationPath $finalOutputPath
} else {
    $builtDir = Join-Path $pyInstallerDistDir $appName
    if (-not (Test-Path -LiteralPath $builtDir)) {
        throw "Expected build output not found: $builtDir"
    }
    Remove-PathWithRetries -LiteralPath (Join-Path $stableDistDir $appName) -Recurse
    Remove-PathWithRetries -LiteralPath $finalOutputPath -Recurse
    if ($BuildProfile -eq "release") {
        foreach ($legacyAppName in $legacyAppNames) {
            Remove-PathWithRetries -LiteralPath (Join-Path $stableDistDir $legacyAppName) -Recurse
        }
    }
    Move-PathWithRetries -SourcePath $builtDir -DestinationPath $finalOutputPath
}

Write-BuildProgress -Percent 100 -Stage "Build complete"
Write-Host "Build complete."
if ($Mode -eq "onefile") {
    Write-Host "Output file: $finalOutputPath"
} else {
    Write-Host "Output folder: $finalOutputPath"
}
