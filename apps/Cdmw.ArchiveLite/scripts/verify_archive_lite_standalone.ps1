param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$standalone = [IO.Path]::GetFullPath($ExecutablePath)
if (-not (Test-Path -LiteralPath $standalone -PathType Leaf)) {
    throw "Standalone executable does not exist: $standalone"
}

function Assert-X64Pe([string]$Path) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $dosHeader = [byte[]]::new(64)
        if ($stream.Read($dosHeader, 0, $dosHeader.Length) -ne $dosHeader.Length -or
            $dosHeader[0] -ne 0x4D -or $dosHeader[1] -ne 0x5A) {
            throw "Not a valid PE file: $Path"
        }
        $peOffset = [BitConverter]::ToInt32($dosHeader, 0x3C)
        if ($peOffset -lt 0 -or $peOffset -gt ($stream.Length - 6)) {
            throw "Invalid PE header offset: $Path"
        }
        $stream.Position = $peOffset
        $peHeader = [byte[]]::new(6)
        if ($stream.Read($peHeader, 0, $peHeader.Length) -ne $peHeader.Length -or
            $peHeader[0] -ne 0x50 -or $peHeader[1] -ne 0x45 -or
            $peHeader[2] -ne 0 -or $peHeader[3] -ne 0) {
            throw "Invalid PE signature: $Path"
        }
        $machine = [BitConverter]::ToUInt16($peHeader, 4)
        if ($machine -ne 0x8664) {
            throw "Standalone executable is not x64 (machine 0x$($machine.ToString('X4'))): $Path"
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-HiddenStandalone([string]$Path, [int]$TimeoutSeconds) {
    $process = Start-Process `
        -FilePath $Path `
        -ArgumentList @("--standalone-self-test") `
        -WorkingDirectory (Split-Path -Parent $Path) `
        -WindowStyle Hidden `
        -PassThru
    try {
        Wait-Process -Id $process.Id -Timeout $TimeoutSeconds -ErrorAction Stop
        $process.Refresh()
        return $process.ExitCode
    }
    catch {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Standalone self-test timed out or could not be observed. $($_.Exception.Message)"
    }
    finally {
        $process.Dispose()
    }
}

Assert-X64Pe $standalone
$testDataRoot = Join-Path ([IO.Path]::GetTempPath()) "cdmw-archive-lite-standalone-$([Guid]::NewGuid().ToString('N'))"
$previousTestMode = $env:CDMW_ARCHIVE_LITE_TEST_MODE
$previousDataRoot = $env:CDMW_ARCHIVE_LITE_DATA_ROOT
try {
    $env:CDMW_ARCHIVE_LITE_TEST_MODE = "1"
    $env:CDMW_ARCHIVE_LITE_DATA_ROOT = $testDataRoot
    New-Item -ItemType Directory -Path $testDataRoot -Force | Out-Null

    $firstExitCode = Invoke-HiddenStandalone -Path $standalone -TimeoutSeconds 240
    if ($firstExitCode -ne 0) {
        $launcherLog = Join-Path $testDataRoot "logs\standalone-launcher.log"
        $diagnostic = if (Test-Path -LiteralPath $launcherLog -PathType Leaf) {
            Get-Content -LiteralPath $launcherLog -Tail 20 | Out-String
        } else {
            "No standalone launcher log was written."
        }
        throw "Standalone first-run self-test failed with exit code $firstExitCode. $diagnostic"
    }
    foreach ($portableDirectory in @("cache", "logs", "crash")) {
        if (-not (Test-Path -LiteralPath (Join-Path $testDataRoot $portableDirectory) -PathType Container)) {
            throw "Standalone launch did not route $portableDirectory into the isolated portable root."
        }
    }

    $payloadRoot = Join-Path $testDataRoot "standalone\payloads"
    $payloadDirectories = @(Get-ChildItem -LiteralPath $payloadRoot -Directory)
    if ($payloadDirectories.Count -ne 1) {
        throw "Standalone first run did not publish exactly one content-addressed runtime."
    }
    $runtime = $payloadDirectories[0].FullName
    $required = @(
        "CdmwArchiveLite.exe",
        "CdmwArchiveLite.Worker.exe",
        "cdmw-archive-core.dll",
        "PACKAGE-CONTENTS.json",
        ".standalone-ready",
        "preview\cdmw-preview-core.exe",
        "indexer\cdmw-archive-accelerator.exe",
        "mesh\cdmw-mesh-core.exe",
        "renderer\cdmw-mesh-dotnet-editor.exe"
    )
    foreach ($relativePath in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $runtime $relativePath) -PathType Leaf)) {
            throw "Standalone extraction is missing $relativePath."
        }
    }

    $marker = Join-Path $runtime ".standalone-ready"
    $markerTimestamp = (Get-Item -LiteralPath $marker).LastWriteTimeUtc.Ticks
    $markerHash = (Get-FileHash -LiteralPath $marker -Algorithm SHA256).Hash
    $secondExitCode = Invoke-HiddenStandalone -Path $standalone -TimeoutSeconds 120
    if ($secondExitCode -ne 0) {
        throw "Standalone cached-run self-test failed with exit code $secondExitCode."
    }
    if ((Get-Item -LiteralPath $marker).LastWriteTimeUtc.Ticks -ne $markerTimestamp -or
        (Get-FileHash -LiteralPath $marker -Algorithm SHA256).Hash -ne $markerHash) {
        throw "Standalone cached run rebuilt or changed an already verified runtime."
    }

    $worker = Join-Path $runtime "CdmwArchiveLite.Worker.exe"
    $orphanWorker = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).Equals($worker, [StringComparison]::OrdinalIgnoreCase)
    }
    if ($orphanWorker) {
        throw "Standalone self-test left an Archive Lite worker process running."
    }
}
finally {
    $env:CDMW_ARCHIVE_LITE_TEST_MODE = $previousTestMode
    $env:CDMW_ARCHIVE_LITE_DATA_ROOT = $previousDataRoot
    if (Test-Path -LiteralPath $testDataRoot) {
        Remove-Item -LiteralPath $testDataRoot -Recurse -Force
    }
}

Write-Host "Standalone guard passed: one x64 executable, verified first-run extraction, cached reuse, and worker-connected application self-test."
