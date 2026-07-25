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
$fullArchiveBackendProbe = Join-Path $scriptDir "tools\dotnet_archive_backend\probe_full_archive_backend.py"
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

function Remove-PackagedOnedirRuntimeArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$OnedirPath
    )

    foreach ($artifactName in @("workspace", "CrimsonDesertModWorkbench.cfg")) {
        Remove-PathWithRetries -LiteralPath (Join-Path $OnedirPath $artifactName) -Recurse
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

function Invoke-TextureBackendSelfTest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
        throw "Native texture backend $Context helper is missing: $ExecutablePath"
    }
    $selfTestOutput = & $ExecutablePath self-test 2>&1
    $exitCode = $LASTEXITCODE
    $selfTestText = ($selfTestOutput | Out-String).Trim()
    if ($exitCode -ne 0 -or $selfTestText -notmatch '"ok"\s*:\s*true') {
        if (-not $selfTestText) {
            $selfTestText = "No self-test output was returned."
        }
        throw "Native texture backend $Context self-test failed with exit code $exitCode. $selfTestText"
    }
    Write-Host "Native texture backend $Context self-test passed."
}

function Test-OnedirTextureBackend {
    param(
        [Parameter(Mandatory = $true)]
        [string]$OnedirPath
    )

    if (-not (Test-Path -LiteralPath $OnedirPath -PathType Container)) {
        throw "Cannot validate packaged onedir texture backend because the directory is missing: $OnedirPath"
    }
    $retiredExecutableName = "tex" + "conv.exe"
    $retiredPayloads = @(
        Get-ChildItem -LiteralPath $OnedirPath -Recurse -File -ErrorAction Stop |
            Where-Object { $_.Name -ieq $retiredExecutableName }
    )
    if ($retiredPayloads.Count -gt 0) {
        $paths = ($retiredPayloads | ForEach-Object { $_.FullName }) -join ", "
        throw "Packaged onedir contains retired texture executables: $paths"
    }
    $helperPath = Join-Path $OnedirPath "_internal\native\cd-texture-dx.exe"
    Invoke-TextureBackendSelfTest -ExecutablePath $helperPath -Context "packaged onedir"
}

function Test-OnefileTextureBackend {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$ExePath
    )

    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Cannot validate packaged onefile texture backend because the EXE is missing: $ExePath"
    }

$validationScript = @'
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

from PyInstaller.archive.readers import CArchiveReader

exe_path = Path(sys.argv[1])
archive = CArchiveReader(str(exe_path))
names = sorted(name for name in archive.toc if name)
normalized = {name: name.replace("\\", "/") for name in names}
retired_leaf = ("tex" + "conv.exe").casefold()
retired = [
    name
    for name, normalized_name in normalized.items()
    if PurePosixPath(normalized_name).name.casefold() == retired_leaf
]
if retired:
    raise RuntimeError(f"Onefile archive contains retired texture executables: {retired}")

helper_names = [
    name
    for name, normalized_name in normalized.items()
    if normalized_name.casefold().endswith("native/cd-texture-dx.exe")
]
if len(helper_names) != 1:
    raise RuntimeError(
        f"Expected exactly one bundled cd-texture-dx.exe, found {len(helper_names)}: {helper_names}"
    )

helper_member = helper_names[0]
helper_data = archive.extract(helper_member)
if not helper_data:
    raise RuntimeError(f"Bundled helper extracted as empty data: {helper_member}")

runtime_leaves = {
    "concrt140.dll",
    "msvcp140.dll",
    "vcomp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}
with tempfile.TemporaryDirectory(prefix="cdmw-packaged-texture-") as temp_dir:
    root = Path(temp_dir)
    helper_path = root / "cd-texture-dx.exe"
    helper_path.write_bytes(helper_data)
    for name, normalized_name in normalized.items():
        leaf = PurePosixPath(normalized_name).name.casefold()
        if leaf not in runtime_leaves:
            continue
        runtime_data = archive.extract(name)
        if runtime_data:
            (root / PurePosixPath(normalized_name).name).write_bytes(runtime_data)
    completed = subprocess.run(
        [str(helper_path), "self-test"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0 or '"ok":true' not in completed.stdout.replace(" ", ""):
        raise RuntimeError(
            "Extracted onefile texture backend self-test failed "
            f"with exit code {completed.returncode}. "
            f"STDOUT: {completed.stdout.strip()} STDERR: {completed.stderr.strip()}"
        )
    print(
        json.dumps(
            {
                "ok": True,
                "helper_member": helper_member,
                "helper_sha256": hashlib.sha256(helper_data).hexdigest(),
            },
            sort_keys=True,
        )
    )
'@

    $validationOutput = $validationScript | & $PythonExe - $ExePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = ($validationOutput | Out-String).Trim()
        if (-not $details) {
            $details = "No validation details were returned."
        }
        throw "Packaged onefile texture backend validation failed for '$ExePath'. $details"
    }
    Write-Host ($validationOutput | Out-String).Trim()
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
        "native\cdmw_archive_accelerator\build\$Configuration\cdmw-archive-accelerator.exe",
        "native\cdmw_mesh_core\build\$Configuration\cdmw-mesh-core.exe",
        "native\cdmw_full_archive_backend\build\$Configuration\cdmw-full-archive-worker.exe",
        "native\cdmw_full_archive_backend\build\$Configuration\cdmw-full-archive-core.dll"
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
        $smokeProcess = Start-Process -FilePath $ExecutablePath -ArgumentList @(
            "--headless-gpu-sparse-soak", "--gpu-soak-smoke", "--gpu-soak-vertices", "100000",
            "--gpu-soak-updates", "100", "--gpu-soak-warmup", "16", "--gpu-soak-no-cadence",
            "--gpu-soak-report", $smokeReport
        ) -Wait -PassThru -WindowStyle Hidden
        if ($smokeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $smokeReport)) {
            throw ".NET Mesh Editor $Context hidden GPU smoke failed with exit code $($smokeProcess.ExitCode)."
        }
        $smoke = Get-Content -LiteralPath $smokeReport -Raw | ConvertFrom-Json
        if ($smoke.ok -ne $true -or $smoke.backend_proof.backend -ne "d3d11_vortice_shader" -or $smoke.gates.native_windows_remained_hidden -ne $true) {
            throw ".NET Mesh Editor $Context hidden GPU smoke did not prove the production Vortice backend."
        }
    } finally {
        Remove-Item -LiteralPath $smokeReport -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-DotNetMeshEditorProvenanceCheck {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    $manifestPath = Join-Path (Split-Path -Parent $ExecutablePath) "cdmw-mesh-dotnet-editor.manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw ".NET Mesh Editor $Context manifest is missing: $manifestPath"
    }
    $reportPath = Join-Path ([System.IO.Path]::GetTempPath()) ("cdmw-dotnet-provenance-{0}.json" -f [Guid]::NewGuid().ToString("N"))
    try {
        $provenanceProcess = Start-Process -FilePath $ExecutablePath -ArgumentList @(
            "--helper-provenance-report", $reportPath
        ) -Wait -PassThru -WindowStyle Hidden
        if ($provenanceProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
            throw ".NET Mesh Editor $Context provenance report failed with exit code $($provenanceProcess.ExitCode)."
        }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        $manifestCapabilities = @($manifest.capabilities | ForEach-Object { [string]$_ } | Sort-Object)
        $reportCapabilities = @($report.capabilities | ForEach-Object { [string]$_ } | Sort-Object)
        if (
            $report.manifest_mode -ne "release_manifest" -or
            $report.manifest_id -ne $manifest.manifest_id -or
            $report.semantic_version -ne $manifest.semantic_version -or
            $report.protocol_version -ne $manifest.protocol_version -or
            $report.process_sha256 -ne $manifest.executable_sha256 -or
            $report.shader_sha256 -ne $manifest.shader_sha256 -or
            $report.renderer_backend -ne $manifest.renderer_backend -or
            $report.edit_backend -ne $manifest.edit_backend -or
            $manifestCapabilities.Count -eq 0 -or
            $reportCapabilities.Count -ne $manifestCapabilities.Count -or
            ($reportCapabilities -join "`n") -ne ($manifestCapabilities -join "`n")
        ) {
            throw ".NET Mesh Editor $Context provenance does not match its packaged manifest."
        }
    } finally {
        Remove-Item -LiteralPath $reportPath -Force -ErrorAction SilentlyContinue
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
    $shaderPath = Join-Path $outputDir "D3D11MaterialShaders.hlsl"
    if (-not (Test-Path -LiteralPath $shaderPath -PathType Leaf)) {
        throw ".NET Mesh Editor publish did not include the authoritative shader: $shaderPath"
    }
    $exeHash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaderHash = (Get-FileHash -LiteralPath $shaderPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $semanticVersion = "2.0.0"
    $protocolCapabilities = @(
        "mesh_edit_revision_ack_v1"
        "resident_mutation_envelope_v2"
        "host_tool_state_v1"
        "resident_material_updates_v2"
        "resident_material_parameter_updates_v1"
        "resident_texture_region_updates_v1"
        "resident_package_load_v1"
        "viewport_display_modes_v1"
        "resident_scene_state_v1"
        "authoritative_resident_scene_frame_v2"
        "helper_build_provenance_v1"
        "deterministic_offscreen_capture_v1"
        "performance_capture_v1"
        "resident_preview_package_replace_v2"
        "preview_profile_read_only_v1"
        "preview_session_v1"
        "view_state_changed_v1"
        "absolute_camera_state_v1"
        "read_only_part_pick_v1"
        "overlay_state_update_v1"
        "skeleton_overlay_v1"
        "pbd_cloth_overlay_v1"
    )
    $sourceRevision = (& git -C $scriptDir rev-parse HEAD 2>$null | Select-Object -First 1)
    if (-not $sourceRevision) {
        $sourceRevision = "unavailable"
    }
    $manifestSeed = "$exeHash|$shaderHash|$sourceRevision|$semanticVersion|$($protocolCapabilities -join ',')"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $manifestId = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($manifestSeed)) | ForEach-Object { $_.ToString("x2") })
    } finally {
        $sha.Dispose()
    }
    $manifestPath = Join-Path $outputDir "cdmw-mesh-dotnet-editor.manifest.json"
    $manifest = [ordered]@{
        format = "cdmw_mesh_dotnet_helper_manifest_v1"
        manifest_id = $manifestId
        source_revision = [string]$sourceRevision
        semantic_version = $semanticVersion
        protocol_version = 2
        executable = "cdmw-mesh-dotnet-editor.exe"
        executable_sha256 = $exeHash
        shader = "D3D11MaterialShaders.hlsl"
        shader_sha256 = $shaderHash
        renderer_backend = "d3d11_vortice_shader"
        edit_backend = "cdmw_mesh_core_0.1"
        capabilities = $protocolCapabilities
    }
    [IO.File]::WriteAllText(
        $manifestPath,
        ($manifest | ConvertTo-Json -Depth 4),
        [Text.UTF8Encoding]::new($false)
    )
    if ($Required) {
        Invoke-DotNetMeshEditorProvenanceCheck -ExecutablePath $exePath -Context "published"
        Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $exePath -Context "published"
    }
}

. (Join-Path $scriptDir "scripts\full_archive_backend_release.ps1")

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
    Invoke-FullArchiveBackendBuild `
        -Configuration $Configuration `
        -Clean:$Clean `
        -Required:$RequireDotNet
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
    Write-Host "  .NET helpers: self-contained Mesh Editor plus standalone archive worker/DLL"
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
        Write-Host "Native helper-only gate: rebuild $nativeConfig helpers, publish the self-contained .NET Mesh Editor and full archive worker/DLL, then run the hidden d3d11_vortice_shader smoke and full archive synthetic gates."
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

Write-BuildProgress -Percent 3 -Stage "Refreshing generated feature metadata"
& $pythonExe $providerMetadataGenerator
if ($LASTEXITCODE -ne 0) {
    throw "Failed to regenerate MainWindow feature metadata before packaging."
}

Write-BuildProgress -Percent 3 -Stage "Verifying generated feature metadata"
& $pythonExe $providerMetadataGenerator --check
if ($LASTEXITCODE -ne 0) {
    throw "Generated MainWindow feature metadata failed verification after regeneration."
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

# PyInstaller packages the renderer from the staging tree, not from the .NET
# build output, so a skipped or failed publish leaves the previous helper in
# place and the build ships it without complaint.  That is silent: the app then
# runs an old shader while the source tree looks correct.  Compare the staged
# shader against the authoritative one and refuse to package a stale renderer.
$stagedShader = Join-Path $scriptDir "native\cdmw_mesh_dotnet_editor\build\$(if ($BuildProfile -eq 'debug') { 'Debug' } else { 'Release' })\D3D11MaterialShaders.hlsl"
$sourceShader = Join-Path $scriptDir "tools\dotnet_mesh_editor_experiment\D3D11MaterialShaders.hlsl"
if (Test-Path -LiteralPath $sourceShader -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $stagedShader -PathType Leaf)) {
        throw "The packaged Mesh Editor renderer is missing its shader: $stagedShader`nRun a build without -SkipNativeBuild, or publish the helper:`n  dotnet publish tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false -o native\cdmw_mesh_dotnet_editor\build\Release"
    }
    $stagedHash = (Get-FileHash -LiteralPath $stagedShader -Algorithm SHA256).Hash.ToLowerInvariant()
    $sourceHash = (Get-FileHash -LiteralPath $sourceShader -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($stagedHash -ne $sourceHash) {
        throw "The staged Mesh Editor shader is stale, so this build would ship an old renderer.`n  staged: $stagedShader`n  source: $sourceShader`nRepublish the helper:`n  dotnet publish tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false -o native\cdmw_mesh_dotnet_editor\build\Release"
    }
    Write-Host "Staged Mesh Editor shader matches the source tree."
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
    Write-BuildProgress -Percent 94 -Stage "Verifying packaged native texture backend"
    if ($Mode -eq "onefile") {
        $packagedOnefile = Join-Path $pyInstallerDistDir "$appName.exe"
        Test-OnefileTextureBackend -PythonExe $pythonExe -ExePath $packagedOnefile
    } else {
        $packagedOnedir = Join-Path $pyInstallerDistDir $appName
        Test-OnedirTextureBackend -OnedirPath $packagedOnedir
    }
    if ($Mode -eq "onedir") {
        Write-BuildProgress -Percent 95 -Stage "Verifying packaged .NET Mesh Editor GPU backend"
        $packagedDotNetHelper = Join-Path $pyInstallerDistDir "$appName\_internal\native\cdmw-mesh-dotnet-editor.exe"
        Invoke-DotNetMeshEditorProvenanceCheck -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"
        Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"
    } else {
        Write-Host "Direct packaged .NET helper smoke is deferred for onefile because PyInstaller extracts helpers at app runtime."
    }
    Write-BuildProgress -Percent 95 -Stage "Verifying packaged full archive backend"
    if ($Mode -eq "onefile") {
        Test-OnefileFullArchiveBackend -PythonExe $pythonExe -ExePath $packagedOnefile
    } else {
        Test-OnedirFullArchiveBackend -PythonExe $pythonExe -OnedirPath $packagedOnedir
    }
    Write-BuildProgress -Percent 96 -Stage "Verifying packaged startup"
    $startupSmokeExecutable = if ($Mode -eq "onefile") {
        Join-Path $pyInstallerDistDir "$appName.exe"
    } else {
        Join-Path (Join-Path $pyInstallerDistDir $appName) "$appName.exe"
    }
    & $packagedStartupVerifier -ExecutablePath $startupSmokeExecutable
    & $packagedStartupVerifier -ExecutablePath $startupSmokeExecutable -Target mesh_builder
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
    Remove-PackagedOnedirRuntimeArtifacts -OnedirPath $builtDir
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
