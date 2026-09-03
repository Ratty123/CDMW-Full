param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onefile",
    [ValidateSet("release", "fast", "debug")]
    [string]$BuildProfile = "release",
    [switch]$SkipNativeBuild,
    [switch]$NativeHelpersOnly,
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
$localizationManifestGenerator = Join-Path $scriptDir "scripts\generate_ui_localization_manifest.py"
$localizationCatalogValidator = Join-Path $scriptDir "scripts\validate_ui_localization_catalogs.py"
$packagedStartupVerifier = Join-Path $scriptDir "scripts\verify_packaged_startup.ps1"
$fullArchiveBackendProbe = Join-Path $scriptDir "tools\dotnet_archive_backend\probe_full_archive_backend.py"
$vgmstreamRuntimeDir = Join-Path $scriptDir ".tools\vgmstream"
$vgmstreamVersion = "r1980"
$vgmstreamBuildCommit = "21bfb6f0a513271f2e18a51322128756bb59f365"
$vgmstreamArchiveSha256 = "110f9087e60057c4af6cff84e26c214159c224792421affdddd3aaa2091f2641"
$vgmstreamDownloadUrl = "https://github.com/bnnm/vgmstream-builds/raw/$vgmstreamBuildCommit/bin/vgmstream-$vgmstreamVersion-test-u.zip"

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    $stream = [IO.File]::OpenRead($LiteralPath)
    try {
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        } finally {
            $sha256.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Test-HostInjectedCodexPopplerPathEntry {
    param(
        [AllowEmptyString()]
        [string]$PathEntry
    )

    if (-not $PathEntry) {
        return $false
    }
    $normalizedEntry = $PathEntry.Trim().Trim([char]'"').TrimEnd([char[]]@('\', '/'))
    return $normalizedEntry -match '(?i)[\\/]codex-runtimes[\\/](?:[^\\/]+[\\/])*dependencies[\\/]native[\\/]poppler[\\/]Library[\\/]bin$'
}

function Get-PackagingPathIsolation {
    param(
        [AllowEmptyString()]
        [string]$PathValue
    )

    $separator = [string][IO.Path]::PathSeparator
    $keptEntries = [Collections.Generic.List[string]]::new()
    $removedEntries = [Collections.Generic.List[string]]::new()
    foreach ($entry in ($PathValue -split [regex]::Escape($separator))) {
        if (Test-HostInjectedCodexPopplerPathEntry -PathEntry $entry) {
            $removedEntries.Add($entry)
        } else {
            $keptEntries.Add($entry)
        }
    }
    return [pscustomobject]@{
        FilteredPath = $keptEntries -join $separator
        RemovedEntries = [string[]]$removedEntries.ToArray()
    }
}

function Get-PathHoldingProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    # "Access to the path is denied" on a build output almost always means the
    # app is running out of it. Name the process rather than making the reader
    # guess at an ACL problem.
    $normalized = $LiteralPath.TrimEnd('\')
    $holders = @()
    foreach ($proc in (Get-Process -ErrorAction SilentlyContinue)) {
        $processPath = $null
        try {
            $processPath = $proc.Path
        } catch {
            continue
        }
        if (-not $processPath) {
            continue
        }
        if (
            $processPath -eq $normalized -or
            $processPath.StartsWith("$normalized\", [StringComparison]::OrdinalIgnoreCase)
        ) {
            $holders += "$($proc.ProcessName) [$($proc.Id)]"
        }
    }
    return @($holders | Sort-Object -Unique)
}

function Get-PathBlockedNote {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath
    )

    $holders = Get-PathHoldingProcesses -LiteralPath $LiteralPath
    if ($holders.Count -eq 0) {
        return ""
    }
    return " Still running from that path: $($holders -join ', '). Close it and build again."
}

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
                throw "Failed to remove '$LiteralPath' after $RetryCount attempt(s): $($_.Exception.Message)$(Get-PathBlockedNote -LiteralPath $LiteralPath)"
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

    # A destination whose parent is missing fails with "Could not find a part of
    # the path", and the retry loop then spends eight attempts on something that
    # cannot start working. `.tools` is the case that bit: it is gitignored, so a
    # developer machine always has it and a fresh clone never does, which is why
    # the pinned vgmstream fetch only failed on CI.
    $destinationParent = Split-Path -Parent $DestinationPath
    if ($destinationParent -and -not (Test-Path -LiteralPath $destinationParent)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        try {
            Move-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -ge $RetryCount) {
                throw "Failed to move '$SourcePath' to '$DestinationPath' after $RetryCount attempt(s): $($_.Exception.Message)$(Get-PathBlockedNote -LiteralPath $DestinationPath)"
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
            $actualHash = Get-Sha256Hex -LiteralPath $runtimeFile
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
        $downloadHash = Get-Sha256Hex -LiteralPath $zipPath
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
            $fileHashes[$file.Name] = Get-Sha256Hex -LiteralPath $file.FullName
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
        "native\cdmw_mesh_core\build\$Configuration\cdmw-mesh-core.dll",
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

function Get-NativeMeshInteractionAbiContract {
    # The ABI DLL exports these values at runtime, but the package manifest is
    # written before the helper can load it. Read the version and identity from
    # the C ABI sources so the release build records exactly the contract it
    # compiled, including the authoritative header hash.
    $headerPath = Join-Path $scriptDir "native\cdmw_mesh_core\src\mesh_interaction_abi.h"
    $implementationPath = Join-Path $scriptDir "native\cdmw_mesh_core\src\mesh_interaction_abi.cpp"
    foreach ($path in @($headerPath, $implementationPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Native mesh interaction ABI source is missing: $path"
        }
    }

    $headerText = Get-Content -LiteralPath $headerPath -Raw
    $versionMatch = [regex]::Match(
        $headerText,
        '#define\s+CDMW_MESH_INTERACTION_ABI_VERSION\s+(?<value>\d+)u?')
    if (-not $versionMatch.Success) {
        throw "Could not read CDMW_MESH_INTERACTION_ABI_VERSION from $headerPath."
    }

    $implementationText = Get-Content -LiteralPath $implementationPath -Raw
    $contractMatch = [regex]::Match(
        $implementationText,
        'cdmw_mesh_interaction_abi_contract\s*\(\s*void\s*\)\s*\{\s*return\s+"(?<value>[^"]+)";',
        [Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $contractMatch.Success) {
        throw "Could not read cdmw_mesh_interaction_abi_contract from $implementationPath."
    }
    $backendMatch = [regex]::Match(
        $implementationText,
        'cdmw_mesh_interaction_backend\s*\(\s*void\s*\)\s*\{\s*return\s+"(?<value>[^"]+)";',
        [Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $backendMatch.Success) {
        throw "Could not read cdmw_mesh_interaction_backend from $implementationPath."
    }

    return [ordered]@{
        AbiVersion = [int]$versionMatch.Groups['value'].Value
        Contract = $contractMatch.Groups['value'].Value
        Backend = $backendMatch.Groups['value'].Value
        HeaderSha256 = Get-Sha256Hex -LiteralPath $headerPath
    }
}

function Test-FullyQualifiedPath {
    param(
        [AllowEmptyString()]
        [string]$LiteralPath
    )

    if ([string]::IsNullOrWhiteSpace($LiteralPath) -or -not [IO.Path]::IsPathRooted($LiteralPath)) {
        return $false
    }
    try {
        $normalized = [IO.Path]::GetFullPath($LiteralPath).TrimEnd([char[]]@('\', '/'))
        $provided = $LiteralPath.TrimEnd([char[]]@('\', '/'))
        return [string]::Equals($normalized, $provided, [StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Get-RustMeshEditorSourceFingerprint {
    $rustRoot = Join-Path $scriptDir "tools\rust_mesh_lab"
    $rustRootPrefix = [IO.Path]::GetFullPath($rustRoot)
    $separator = [string][IO.Path]::DirectorySeparatorChar
    if (-not $rustRootPrefix.EndsWith($separator)) {
        $rustRootPrefix += $separator
    }
    $sourceFiles = @(
        Get-ChildItem -LiteralPath $rustRoot -Recurse -File |
            Where-Object {
                $_.FullName -notlike "*\target\*" -and
                ($_.Extension -eq ".rs" -or $_.Name -in @("Cargo.toml", "Cargo.lock", "rust-toolchain.toml"))
            } |
            Sort-Object FullName
    )
    if ($sourceFiles.Count -eq 0) {
        throw "Rust Mesh Editor source fingerprint has no inputs under $rustRoot."
    }
    $rows = foreach ($sourceFile in $sourceFiles) {
        $sourceFullName = [IO.Path]::GetFullPath($sourceFile.FullName)
        if (-not $sourceFullName.StartsWith($rustRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Rust Mesh Editor source fingerprint entry escaped its workspace: $sourceFullName"
        }
        # Path.GetRelativePath is unavailable under Windows PowerShell 5.1's
        # .NET Framework runtime. Every enumerated source is already contained
        # by the checked prefix, so a bounded substring is equivalent here.
        $relative = $sourceFullName.Substring($rustRootPrefix.Length).Replace('\', '/')
        "$relative|$(Get-Sha256Hex -LiteralPath $sourceFile.FullName)"
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($rows -join "`n")) | ForEach-Object { $_.ToString("x2") })
    } finally {
        $sha.Dispose()
    }
}

function Assert-RustMeshEditorControlContract {
    param(
        [Parameter(Mandatory = $true)]
        [object]$RustContract
    )

    if ($RustContract.ok -ne $true) {
        throw "The Rust Mesh Editor control contract did not report success."
    }
    if (
        $RustContract.renderer -ne "wgpu_d3d12_rust" -or
        $RustContract.edit_backend -ne "cdmw_rust_mesh_0.1"
    ) {
        throw "Rust Mesh Editor provenance does not match its CDMW integration contract."
    }
    if ([string]$RustContract.schema -ne "cdmw_rust_mesh_editor_control_contract_v2") {
        throw "Rust Mesh Editor control-contract schema is not v2."
    }
    if ($RustContract.preview_contract.ok -ne $true) {
        throw "The Rust Preview control contract did not report success."
    }
    $previewCapabilities = @(
        $RustContract.preview_contract.capabilities |
            ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($previewCapabilities.Count -eq 0) {
        throw "The Rust Preview control contract did not advertise any capabilities."
    }

    $rustRows = @($RustContract.rows)
    if ([int]$RustContract.row_count -ne $rustRows.Count -or $rustRows.Count -eq 0) {
        throw "Rust Mesh Editor control row count is invalid."
    }

    $seenKeys = @{}
    $expectedFeedback = @("disabled", "enabled", "failure_reason", "hover", "pressed", "selected")
    foreach ($rustRow in $rustRows) {
        $rowKey = [string]$rustRow.key
        if ([string]::IsNullOrWhiteSpace($rowKey) -or $seenKeys.ContainsKey($rowKey)) {
            throw "Rust Mesh Editor control contract has an empty or duplicate key '$rowKey'."
        }
        $seenKeys[$rowKey] = $true
        if ($rustRow.rust_implemented -ne $true) {
            throw "Rust Mesh Editor row '$rowKey' is not implemented."
        }
        if ($rustRow.disposition -eq "deliberately_disabled" -and [string]::IsNullOrWhiteSpace([string]$rustRow.reason)) {
            throw "Rust Mesh Editor disabled row '$rowKey' has no visible reason."
        }
        $feedback = @($rustRow.rust_state_feedback | ForEach-Object { [string]$_ } | Sort-Object)
        if ((ConvertTo-Json $feedback -Compress) -cne (ConvertTo-Json $expectedFeedback -Compress)) {
            throw "Rust Mesh Editor row '$rowKey' does not expose the required UI feedback states."
        }
    }
}

function Invoke-RustMeshEditorBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration,
        [switch]$Required
    )

    $rustRoot = Join-Path $scriptDir "tools\rust_mesh_lab"
    $manifestPath = Join-Path $rustRoot "Cargo.toml"
    $toolchainPath = Join-Path $rustRoot "rust-toolchain.toml"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or -not (Test-Path -LiteralPath $toolchainPath -PathType Leaf)) {
        if ($Required) {
            throw "Required pinned Rust Mesh Editor workspace is missing under $rustRoot."
        }
        Write-Warning "Pinned Rust Mesh Editor workspace was not found; skipping its build."
        return
    }
    $cargo = Get-Command cargo -ErrorAction SilentlyContinue
    if ($null -eq $cargo) {
        if ($Required) {
            throw "Cargo is required to build the Rust Mesh Editor."
        }
        Write-Warning "Cargo was not found; skipping the Rust Mesh Editor build."
        return
    }

    $cargoArguments = @("build", "--locked", "-p", "cdmw_mesh_lab")
    $profileDirectory = "debug"
    if ($Configuration -eq "Release") {
        $cargoArguments += "--release"
        $profileDirectory = "release"
    }
    Write-Host "Building Rust Mesh Editor with the pinned toolchain ($Configuration)..."
    Push-Location $rustRoot
    try {
        & $cargo.Source @cargoArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Rust Mesh Editor cargo build failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }

    $builtExecutable = Join-Path $rustRoot "target\$profileDirectory\cdmw_mesh_lab.exe"
    if (-not (Test-Path -LiteralPath $builtExecutable -PathType Leaf)) {
        throw "Rust Mesh Editor build did not create $builtExecutable."
    }
    $outputDir = Join-Path $scriptDir "native\rust_mesh_editor\build\$Configuration"
    Remove-PathWithRetries -LiteralPath $outputDir -Recurse
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    $stagedExecutable = Join-Path $outputDir "cdmw_mesh_lab.exe"
    Copy-Item -LiteralPath $builtExecutable -Destination $stagedExecutable -Force

    $controlContractPath = Join-Path $outputDir "cdmw_mesh_lab.control-contract.json"
    $contractProcess = Start-Process -FilePath $stagedExecutable -ArgumentList @(
        "--control-contract-json", "`"$controlContractPath`""
    ) -Wait -PassThru -WindowStyle Hidden
    if ($contractProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $controlContractPath -PathType Leaf)) {
        throw "Rust Mesh Editor control-contract probe failed with exit code $($contractProcess.ExitCode)."
    }
    try {
        # Windows PowerShell 5.1 treats UTF-8 without a BOM as the active ANSI
        # code page, so decode the Rust-owned report explicitly.
        $contract = Get-Content -LiteralPath $controlContractPath -Encoding UTF8 -Raw | ConvertFrom-Json
    } catch {
        throw "Mesh Editor control-contract output is not valid JSON: $($_.Exception.Message)"
    }
    Assert-RustMeshEditorControlContract -RustContract $contract

    $sourceRevision = (& git -C $scriptDir rev-parse HEAD 2>$null | Select-Object -First 1)
    if (-not $sourceRevision) {
        $sourceRevision = "unavailable"
    }
    $cargoVersion = (& $cargo.Source --version | Select-Object -First 1)
    $rustcVersion = (& rustc --version | Select-Object -First 1)
    $provenance = [ordered]@{
        schema = "cdmw_rust_mesh_editor_build_provenance_v1"
        renderer = "wgpu_d3d12_rust"
        edit_backend = "cdmw_rust_mesh_0.1"
        protocol = "cdmw_rust_mesh_editor_protocol_v1"
        authoring_package = "cdmw_rust_mesh_authoring_package_v1"
        preview_protocol = "cdmw_rust_preview_protocol_v1"
        preview_package = "cdmw_rust_preview_package_v1"
        preview_backend = "cdmw_rust_preview_0.1"
        build_profile = $Configuration.ToLowerInvariant()
        locked_dependencies = $true
        executable = "cdmw_mesh_lab.exe"
        control_contract = "cdmw_mesh_lab.control-contract.json"
        control_contract_schema = "cdmw_rust_mesh_editor_control_contract_v2"
        capabilities = @("embedded_child_window_v1", "rust_preview_runtime_v1")
        preview_capabilities = @(
            $contract.preview_contract.capabilities |
                ForEach-Object { [string]$_ }
        )
        source_revision = [string]$sourceRevision
        source_tree_sha256 = Get-RustMeshEditorSourceFingerprint
        cargo_lock_sha256 = Get-Sha256Hex -LiteralPath (Join-Path $rustRoot "Cargo.lock")
        executable_sha256 = Get-Sha256Hex -LiteralPath $stagedExecutable
        control_contract_sha256 = Get-Sha256Hex -LiteralPath $controlContractPath
        cargo_version = [string]$cargoVersion
        rustc_version = [string]$rustcVersion
    }
    $provenancePath = Join-Path $outputDir "cdmw_mesh_lab.manifest.json"
    [IO.File]::WriteAllText(
        $provenancePath,
        ($provenance | ConvertTo-Json -Depth 8),
        [Text.UTF8Encoding]::new($false)
    )
    Write-Host "Rust Mesh Editor staged: $stagedExecutable"
    Write-Host "Rust Mesh Editor SHA-256: $($provenance.executable_sha256)"
}

. (Join-Path $scriptDir "scripts\full_archive_backend_release.ps1")

function Invoke-NativeHelperPreparation {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration,
        [switch]$Clean,
        [switch]$RequireReleaseHelpers
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
    Invoke-RustMeshEditorBuild -Configuration $Configuration -Required:$RequireReleaseHelpers
    Invoke-FullArchiveBackendBuild `
        -Configuration $Configuration `
        -Clean:$Clean `
        -Required:$RequireReleaseHelpers
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
    Write-Host "  Native helpers: Rust Mesh Editor/Archive Preview and standalone archive worker/DLL"
    Write-Host ""
}

if ($NativeHelpersOnly) {
    if ($SkipNativeBuild) {
        throw "-NativeHelpersOnly cannot be combined with -SkipNativeBuild."
    }
    $nativeConfig = if ($BuildProfile -eq "debug") { "Debug" } else { "Release" }
    if ($DescribeOnly) {
        Write-Host "Native helper-only gate: rebuild $nativeConfig helpers, publish the pinned Rust Mesh Editor/Archive Preview plus full archive worker/DLL, then run their contract/provenance checks and existing synthetic gates."
        return
    }
    Invoke-NativeHelperPreparation `
        -Configuration $nativeConfig `
        -Clean:($BuildProfile -ne "fast") `
        -RequireReleaseHelpers:($BuildProfile -eq "release")
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

Write-BuildProgress -Percent 3 -Stage "Verifying interface localization catalogs"
& $pythonExe $localizationManifestGenerator --check
if ($LASTEXITCODE -ne 0) {
    throw "The interface localization source manifest is stale. Regenerate and review the catalogs before packaging."
}
& $pythonExe $localizationCatalogValidator
if ($LASTEXITCODE -ne 0) {
    throw "Interface localization catalog validation failed. Packaging requires exact parity for all built-in languages."
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
        -RequireReleaseHelpers:($BuildProfile -eq "release")
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

$packagingPathBeforeIsolation = [string][Environment]::GetEnvironmentVariable("PATH", "Process")
$packagingPathIsolation = Get-PackagingPathIsolation -PathValue $packagingPathBeforeIsolation
$removedPackagingPathEntries = @($packagingPathIsolation.RemovedEntries)
if ($removedPackagingPathEntries.Count -gt 0) {
    Write-Host "Temporarily removing host-injected Codex Poppler runtime from the packaging environment:"
    foreach ($removedPathEntry in $removedPackagingPathEntries) {
        Write-Host "  $removedPathEntry"
    }
}
[Environment]::SetEnvironmentVariable("PATH", $packagingPathIsolation.FilteredPath, "Process")
# Keep the same isolation through packaged verification so a host runtime
# cannot hide a missing dependency. The finally block restores the caller.
try {
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
} finally {
    [Environment]::SetEnvironmentVariable("PATH", $packagingPathBeforeIsolation, "Process")
}
