param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onefile",
    [ValidateSet("release", "fast", "debug")]
    [string]$BuildProfile = "release",
    [switch]$SkipNativeBuild,
    [switch]$NativeHelpersOnly,
    [string]$DotNetGpuSmokeExecutable = "",
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
$releaseConstraintsPath = Join-Path $scriptDir "constraints-release.txt"
$releaseDependencyVerifier = Join-Path $scriptDir "scripts\verify_release_dependencies.py"
$providerMetadataGenerator = Join-Path $scriptDir "scripts\generate_window_feature_provider_members.py"
$packagedStartupVerifier = Join-Path $scriptDir "scripts\verify_packaged_startup.ps1"
$vgmstreamRuntimeDir = Join-Path $scriptDir ".tools\vgmstream"
$vgmstreamVersion = "r1980"
$vgmstreamBuildCommit = "21bfb6f0a513271f2e18a51322128756bb59f365"
$vgmstreamArchiveSha256 = "110f9087e60057c4af6cff84e26c214159c224792421affdddd3aaa2091f2641"
$vgmstreamDownloadUrl = "https://github.com/bnnm/vgmstream-builds/raw/$vgmstreamBuildCommit/bin/vgmstream-$vgmstreamVersion-test-u.zip"

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

function Get-VgmstreamRuntimeVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CliPath
    )

    if (-not (Test-Path -LiteralPath $CliPath)) {
        return ""
    }
    try {
        $versionJson = (& $CliPath -V 2>$null | Out-String).Trim()
        if (-not $versionJson) {
            return ""
        }
        return [string](($versionJson | ConvertFrom-Json).version)
    } catch {
        return ""
    }
}

function Test-VgmstreamRuntimePin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeDir
    )

    $cliPath = Join-Path $RuntimeDir "vgmstream-cli.exe"
    $manifestPath = Join-Path $RuntimeDir ".cdmw-dependency.json"
    if ((Get-VgmstreamRuntimeVersion -CliPath $cliPath) -ne $vgmstreamVersion) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        return $false
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (
            [string]$manifest.version -ne $vgmstreamVersion -or
            [string]$manifest.build_commit -ne $vgmstreamBuildCommit -or
            [string]$manifest.archive_sha256 -ne $vgmstreamArchiveSha256
        ) {
            return $false
        }
        $fileRows = @($manifest.files.PSObject.Properties)
        if (-not $fileRows) {
            return $false
        }
        foreach ($row in $fileRows) {
            $runtimeFile = Join-Path $RuntimeDir $row.Name
            if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
                return $false
            }
            $actualHash = (Get-FileHash -LiteralPath $runtimeFile -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne [string]$row.Value) {
                return $false
            }
        }
        return @(Get-ChildItem -LiteralPath $RuntimeDir -Filter "*.dll" -File).Count -gt 0
    } catch {
        return $false
    }
}

function Ensure-VgmstreamRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeDir
    )

    $cliPath = Join-Path $RuntimeDir "vgmstream-cli.exe"
    if (Test-VgmstreamRuntimePin -RuntimeDir $RuntimeDir) {
        return $RuntimeDir
    }

    $zipPath = Join-Path $env:TEMP "vgmstream-$vgmstreamVersion-test-u.zip"
    $extractDir = Join-Path $stableBuildDir "vgmstream-$vgmstreamVersion-extract"
    $preparedDir = Join-Path $stableBuildDir "vgmstream-$vgmstreamVersion-runtime"
    $backupDir = Join-Path $stableBuildDir "vgmstream-runtime-previous"

    Write-Host "Downloading pinned vgmstream runtime $vgmstreamVersion..."
    Remove-PathWithRetries -LiteralPath $zipPath
    Remove-PathWithRetries -LiteralPath $extractDir -Recurse
    Remove-PathWithRetries -LiteralPath $preparedDir -Recurse
    Remove-PathWithRetries -LiteralPath $backupDir -Recurse
    try {
        Invoke-WebRequest -Uri $vgmstreamDownloadUrl -OutFile $zipPath
        $downloadHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($downloadHash -ne $vgmstreamArchiveSha256) {
            throw "vgmstream archive SHA-256 mismatch. Expected $vgmstreamArchiveSha256, got $downloadHash."
        }
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
        New-Item -ItemType Directory -Path $preparedDir -Force | Out-Null
        $runtimeFiles = @(Get-ChildItem -LiteralPath $extractDir -File | Where-Object {
            $_.Name -eq "vgmstream-cli.exe" -or $_.Extension -ieq ".dll" -or $_.Name -eq "COPYING"
        })
        if (-not $runtimeFiles) {
            throw "Downloaded vgmstream archive did not contain the expected runtime files."
        }
        foreach ($file in $runtimeFiles) {
            Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $preparedDir $file.Name) -Force
        }
        $preparedCli = Join-Path $preparedDir "vgmstream-cli.exe"
        if ((Get-VgmstreamRuntimeVersion -CliPath $preparedCli) -ne $vgmstreamVersion) {
            throw "Downloaded vgmstream runtime does not report version $vgmstreamVersion."
        }
        $fileHashes = [ordered]@{}
        foreach ($file in Get-ChildItem -LiteralPath $preparedDir -File | Sort-Object Name) {
            $fileHashes[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        [ordered]@{
            schema = 1
            version = $vgmstreamVersion
            build_commit = $vgmstreamBuildCommit
            archive_sha256 = $vgmstreamArchiveSha256
            files = $fileHashes
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $preparedDir ".cdmw-dependency.json") -Encoding UTF8
        if (Test-Path -LiteralPath $RuntimeDir) {
            Move-PathWithRetries -SourcePath $RuntimeDir -DestinationPath $backupDir
        }
        try {
            Move-PathWithRetries -SourcePath $preparedDir -DestinationPath $RuntimeDir
        } catch {
            if ((Test-Path -LiteralPath $backupDir) -and -not (Test-Path -LiteralPath $RuntimeDir)) {
                Move-PathWithRetries -SourcePath $backupDir -DestinationPath $RuntimeDir
            }
            throw
        }
        Remove-PathWithRetries -LiteralPath $backupDir -Recurse
    } finally {
        Remove-PathWithRetries -LiteralPath $zipPath
        Remove-PathWithRetries -LiteralPath $extractDir -Recurse
        Remove-PathWithRetries -LiteralPath $preparedDir -Recurse
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
        "fast" { return "incremental PyInstaller cache, native helpers rebuild incrementally, skips onefile archive validation; use for local iteration" }
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
        "native\cdmw_archive_accelerator\build\$Configuration\cdmw-archive-accelerator.exe",
        "native\cdmw_mesh_core\build\$Configuration\cdmw-mesh-core.exe"
    )

    foreach ($relativePath in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $scriptDir $relativePath))) {
            return $false
        }
    }
    return $true
}

function Invoke-DotNetMeshEditorGpuSmoke {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
        throw ".NET Mesh Editor $Context helper is missing: $ExecutablePath"
    }
    $smokeReport = Join-Path ([System.IO.Path]::GetTempPath()) ("cdmw-dotnet-gpu-smoke-{0}.json" -f [Guid]::NewGuid().ToString("N"))
    try {
        & $ExecutablePath --headless-gpu-sparse-soak --gpu-soak-smoke --gpu-soak-vertices 100000 --gpu-soak-updates 100 --gpu-soak-warmup 16 --gpu-soak-no-cadence --gpu-soak-report $smokeReport | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $smokeReport)) {
            throw ".NET Mesh Editor $Context hidden GPU smoke failed with exit code $LASTEXITCODE."
        }
        $smoke = Get-Content -LiteralPath $smokeReport -Raw | ConvertFrom-Json
        if ($smoke.ok -ne $true -or $smoke.backend_proof.backend -ne "d3d11_vortice_shader" -or $smoke.gates.native_windows_remained_hidden -ne $true) {
            throw ".NET Mesh Editor $Context hidden GPU smoke did not prove the production Vortice backend."
        }
    } finally {
        Remove-Item -LiteralPath $smokeReport -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-DotNetMeshEditorBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration,
        [switch]$Required
    )

    $projectPath = Join-Path $scriptDir "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
    if (-not (Test-Path -LiteralPath $projectPath)) {
        if ($Required) {
            throw "Required .NET Mesh Editor experiment project is missing: $projectPath"
        }
        return
    }

    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $dotnet) {
        if ($Required) {
            throw ".NET SDK is required to publish the Mesh Editor experiment helper."
        }
        Write-Warning ".NET SDK not found; skipping Mesh Editor experiment helper publish."
        return
    }

    $outputDir = Join-Path $scriptDir "native\cdmw_mesh_dotnet_editor\build\$Configuration"
    Remove-PathWithRetries -LiteralPath $outputDir -Recurse
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Write-Host "Publishing .NET Mesh Editor experiment helper ($Configuration)..."
    & $dotnet.Source publish $projectPath -c $Configuration -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false -o $outputDir
    if ($LASTEXITCODE -ne 0) {
        if ($Required) {
            throw ".NET Mesh Editor experiment helper publish failed with exit code $LASTEXITCODE."
        }
        Write-Warning ".NET Mesh Editor experiment helper publish failed with exit code $LASTEXITCODE."
        return
    }

    $exePath = Join-Path $outputDir "cdmw-mesh-dotnet-editor.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        if ($Required) {
            throw ".NET Mesh Editor experiment helper publish did not create $exePath."
        }
        Write-Warning ".NET Mesh Editor experiment helper publish did not create $exePath."
        return
    }
    if ($Required) {
        Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $exePath -Context "published"
    }
}

function Invoke-NativeHelperPreparation {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration,
        [switch]$Clean,
        [switch]$RequireDotNet
    )

    Write-Host "Building native helpers ($Configuration)..."
    $nativeBuildArgs = @{ Configuration = $Configuration }
    if ($Clean) {
        $nativeBuildArgs.Clean = $true
    }
    & (Join-Path $scriptDir "build_native_windows.ps1") @nativeBuildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Native helper build failed with exit code $LASTEXITCODE."
    }
    Invoke-DotNetMeshEditorBuild -Configuration $Configuration -Required:$RequireDotNet
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
    Write-Host "  .NET helper: win-x64 self-contained single-file"
    Write-Host ""
}

if ($DotNetGpuSmokeExecutable) {
    Invoke-DotNetMeshEditorGpuSmoke `
        -ExecutablePath $DotNetGpuSmokeExecutable `
        -Context "packaged QA"
    return
}

if ($NativeHelpersOnly) {
    if ($SkipNativeBuild) {
        throw "-NativeHelpersOnly cannot be combined with -SkipNativeBuild."
    }
    $nativeConfig = if ($BuildProfile -eq "debug") { "Debug" } else { "Release" }
    if ($DescribeOnly) {
        Write-Host "Native helper-only gate: rebuild $nativeConfig helpers, publish the self-contained .NET Mesh Editor, and require its hidden d3d11_vortice_shader smoke."
        return
    }
    Invoke-NativeHelperPreparation `
        -Configuration $nativeConfig `
        -Clean:($BuildProfile -ne "fast") `
        -RequireDotNet:($BuildProfile -eq "release")
    return
}

$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "python"
}

if (-not (Test-Path -LiteralPath $specPath)) {
    throw "PyInstaller spec file not found: $specPath"
}

Write-BuildProgress -Percent 3 -Stage "Checking generated feature metadata"
& $pythonExe $providerMetadataGenerator --check
if ($LASTEXITCODE -ne 0) {
    throw "Generated MainWindow feature metadata is stale. Run scripts\generate_window_feature_provider_members.py before packaging."
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

if ($BuildProfile -eq "release") {
    Write-BuildProgress -Percent 4 -Stage "Verifying release dependency pins"
    & $pythonExe $releaseDependencyVerifier --constraints $releaseConstraintsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Release dependency verification failed. Install requirements-build.txt with constraints-release.txt."
    }
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

if ($BuildProfile -eq "release") {
    Write-BuildProgress -Percent 10 -Stage "Release dirty-tree preflight"
    $releaseInventoryPath = Join-Path $stableBuildDir "release-change-inventory.json"
    & $pythonExe (Join-Path $scriptDir "scripts\release_preflight.py") --inventory $releaseInventoryPath
    if ($LASTEXITCODE -ne 0) {
        throw "Release preflight blocked packaging. Review $releaseInventoryPath and classify or remove generated/untracked source before release."
    }
}

if (-not $SkipNativeBuild) {
    $nativeConfig = if ($BuildProfile -eq "debug") { "Debug" } else { "Release" }
    Write-BuildProgress -Percent 12 -Stage "Building native helpers"
    Invoke-NativeHelperPreparation `
        -Configuration $nativeConfig `
        -Clean:($BuildProfile -ne "fast") `
        -RequireDotNet:($BuildProfile -eq "release")
    Write-BuildProgress -Percent 20 -Stage "Native helpers ready"
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

if ($BuildProfile -eq "release") {
    if ($Mode -eq "onedir") {
        Write-BuildProgress -Percent 95 -Stage "Verifying packaged .NET Mesh Editor GPU backend"
        $packagedDotNetHelper = Join-Path $pyInstallerDistDir "$appName\_internal\native\cdmw-mesh-dotnet-editor.exe"
        Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"
    } else {
        Write-Host "Direct packaged .NET helper smoke is deferred for onefile because PyInstaller extracts helpers at app runtime."
    }
    Write-BuildProgress -Percent 96 -Stage "Verifying packaged startup"
    $startupSmokeExecutable = if ($Mode -eq "onefile") {
        Join-Path $pyInstallerDistDir "$appName.exe"
    } else {
        Join-Path (Join-Path $pyInstallerDistDir $appName) "$appName.exe"
    }
    & $packagedStartupVerifier -ExecutablePath $startupSmokeExecutable
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
