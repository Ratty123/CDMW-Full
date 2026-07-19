function Invoke-FullArchiveBackendProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$WorkerPath,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (-not (Test-Path -LiteralPath $WorkerPath -PathType Leaf)) {
        throw "Full archive backend $Context worker is missing: $WorkerPath"
    }
    $nativeCorePath = Join-Path (Split-Path -Parent $WorkerPath) "cdmw-full-archive-core.dll"
    if (-not (Test-Path -LiteralPath $nativeCorePath -PathType Leaf)) {
        throw "Full archive backend $Context native core is missing beside the worker: $nativeCorePath"
    }
    if (-not (Test-Path -LiteralPath $fullArchiveBackendProbe -PathType Leaf)) {
        throw "Full archive backend probe is missing: $fullArchiveBackendProbe"
    }

    $reportPath = Join-Path ([System.IO.Path]::GetTempPath()) ("cdmw-full-archive-packaged-{0}.json" -f [Guid]::NewGuid().ToString("N"))
    try {
        $probeOutput = & $PythonExe $fullArchiveBackendProbe --worker $WorkerPath --report $reportPath 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
            $details = ($probeOutput | Out-String).Trim()
            if (-not $details) {
                $details = "No probe output was returned."
            }
            throw "Full archive backend $Context probe failed with exit code $exitCode. $details"
        }
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if (
            $report.status -ne "passed" -or
            $report.evidence -ne "synthetic_headless_qprocess" -or
            $report.cancelled -ne $true -or
            $report.worker_stopped -ne $true -or
            [int]$report.entry_count -le 0 -or
            [int]$report.page_rows -le 0
        ) {
            throw "Full archive backend $Context probe did not prove protocol/ABI, open, query, cancel, and clean shutdown."
        }
        Write-Host "Full archive backend $Context synthetic probe passed."
    } finally {
        Remove-Item -LiteralPath $reportPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-OnedirFullArchiveBackend {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$OnedirPath
    )

    if (-not (Test-Path -LiteralPath $OnedirPath -PathType Container)) {
        throw "Cannot validate packaged onedir full archive backend because the directory is missing: $OnedirPath"
    }
    $workerPath = Join-Path $OnedirPath "_internal\archive_backend\cdmw-full-archive-worker.exe"
    Invoke-FullArchiveBackendProbe -PythonExe $PythonExe -WorkerPath $workerPath -Context "packaged onedir"
}

function Test-OnefileFullArchiveBackend {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$ExePath
    )

    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Cannot validate packaged onefile full archive backend because the EXE is missing: $ExePath"
    }

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("cdmw-packaged-archive-backend-{0}" -f [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
$extractionScript = @'
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import sys

from PyInstaller.archive.readers import CArchiveReader

exe_path = Path(sys.argv[1])
destination = Path(sys.argv[2]).resolve()
archive = CArchiveReader(str(exe_path))
prefix = "archive_backend/"
extracted: list[str] = []
for name in sorted(entry for entry in archive.toc if entry):
    normalized = name.replace("\\", "/")
    folded = normalized.casefold()
    marker = folded.rfind(prefix)
    if marker < 0:
        continue
    relative = PurePosixPath(normalized[marker + len(prefix):])
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeError(f"Unsafe archive backend member: {name}")
    target = destination.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(destination):
        raise RuntimeError(f"Archive backend member escaped the extraction root: {name}")
    data = archive.extract(name)
    if not data:
        raise RuntimeError(f"Archive backend member extracted as empty data: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    extracted.append(relative.as_posix())

required = {"cdmw-full-archive-worker.exe", "cdmw-full-archive-core.dll"}
missing = sorted(required.difference({PurePosixPath(path).name.casefold() for path in extracted}))
if missing:
    raise RuntimeError(f"Onefile archive is missing full archive backend members: {missing}")
print(json.dumps({"extracted": len(extracted), "required": sorted(required)}, sort_keys=True))
'@
        $extractionOutput = $extractionScript | & $PythonExe - $ExePath $tempRoot 2>&1
        if ($LASTEXITCODE -ne 0) {
            $details = ($extractionOutput | Out-String).Trim()
            throw "Packaged onefile full archive backend extraction failed. $details"
        }
        if ($extractionOutput) {
            Write-Host ($extractionOutput | Out-String).Trim()
        }
        $workerPath = Join-Path $tempRoot "cdmw-full-archive-worker.exe"
        Invoke-FullArchiveBackendProbe -PythonExe $PythonExe -WorkerPath $workerPath -Context "extracted onefile"
    } finally {
        Remove-PathWithRetries -LiteralPath $tempRoot -Recurse
    }
}

function Invoke-FullArchiveBackendBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Release", "Debug")]
        [string]$Configuration,
        [switch]$Clean,
        [switch]$Required
    )

    $nativeRoot = Join-Path $scriptDir "native\cdmw_full_archive_core"
    $nativeBuild = Join-Path $nativeRoot "build"
    $workerProject = Join-Path $scriptDir "tools\dotnet_archive_backend\src\Cdmw.FullArchive.Worker\Cdmw.FullArchive.Worker.csproj"
    $testProject = Join-Path $scriptDir "tools\dotnet_archive_backend\tests\Cdmw.FullArchive.Tests\Cdmw.FullArchive.Tests.csproj"
    $outputDir = Join-Path $scriptDir "native\cdmw_full_archive_backend\build\$Configuration"
    $nativeDll = Join-Path $nativeBuild "$Configuration\cdmw-full-archive-core.dll"
    $workerExe = Join-Path $outputDir "cdmw-full-archive-worker.exe"
    $packagedNativeDll = Join-Path $outputDir "cdmw-full-archive-core.dll"

    foreach ($requiredPath in @($nativeRoot, $workerProject, $testProject, $fullArchiveBackendProbe)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            if ($Required) {
                throw "Required full archive backend source is missing: $requiredPath"
            }
            Write-Warning "Full archive backend source is missing; skipping publish: $requiredPath"
            return
        }
    }

    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    $ctest = Get-Command ctest -ErrorAction SilentlyContinue
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $cmake -or $null -eq $ctest -or $null -eq $dotnet) {
        $missingTools = @()
        if ($null -eq $cmake) { $missingTools += "cmake" }
        if ($null -eq $ctest) { $missingTools += "ctest" }
        if ($null -eq $dotnet) { $missingTools += "dotnet" }
        $message = "Full archive backend build tools are missing: $($missingTools -join ', ')."
        if ($Required) {
            throw $message
        }
        Write-Warning "$message Skipping full archive backend publish."
        return
    }

    if ($Clean) {
        Remove-PathWithRetries -LiteralPath $nativeBuild -Recurse
        Remove-PathWithRetries -LiteralPath $outputDir -Recurse
    }
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    Write-Host "Building full archive native core ($Configuration)..."
    & $cmake.Source -S $nativeRoot -B $nativeBuild
    if ($LASTEXITCODE -ne 0) {
        throw "Full archive native configure failed with exit code $LASTEXITCODE."
    }
    & $cmake.Source --build $nativeBuild --config $Configuration --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "Full archive native build failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $nativeDll -PathType Leaf)) {
        throw "Full archive native build did not create $nativeDll."
    }

    if ($Required) {
        & $ctest.Source --test-dir $nativeBuild -C $Configuration --output-on-failure
        if ($LASTEXITCODE -ne 0) {
            throw "Full archive native self-tests failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Publishing self-contained full archive worker ($Configuration)..."
    & $dotnet.Source publish $workerProject -c $Configuration -r win-x64 --self-contained true -p:PublishSingleFile=false -p:PublishTrimmed=false -o $outputDir --nologo --verbosity:minimal
    if ($LASTEXITCODE -ne 0) {
        throw "Full archive worker publish failed with exit code $LASTEXITCODE."
    }
    Copy-Item -LiteralPath $nativeDll -Destination $packagedNativeDll -Force
    if (
        -not (Test-Path -LiteralPath $workerExe -PathType Leaf) -or
        -not (Test-Path -LiteralPath $packagedNativeDll -PathType Leaf)
    ) {
        throw "Full archive worker publish did not create the worker/DLL bundle in $outputDir."
    }

    if ($Required) {
        & $dotnet.Source run --project $testProject -c $Configuration
        if ($LASTEXITCODE -ne 0) {
            throw "Full archive worker tests failed with exit code $LASTEXITCODE."
        }
        $probePython = Join-Path $scriptDir ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $probePython -PathType Leaf)) {
            throw "Project virtualenv Python is required for the full archive backend probe: $probePython"
        }
        Invoke-FullArchiveBackendProbe -PythonExe $probePython -WorkerPath $workerExe -Context "published"
    }
}
