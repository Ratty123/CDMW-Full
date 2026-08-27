$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$HelperDll = Join-Path $RepoRoot "tools\dotnet_mesh_editor_experiment\bin\Release\net10.0-windows\cdmw-mesh-dotnet-editor.dll"
$FixtureRoot = Join-Path $RepoRoot "tests\fixtures\asset_authoring"
$FixtureMesh = Join-Path $FixtureRoot "triangle.obj"
$TempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$RunRoot = Join-Path $TempRoot ("cdmw-dotnet-status-" + [Guid]::NewGuid().ToString("N"))

if (-not (Test-Path -LiteralPath $HelperDll)) {
    throw "The release .NET Mesh Editor helper must be built before the status-output smoke."
}
if (-not (Test-Path -LiteralPath $FixtureMesh)) {
    throw "The status-output smoke fixture is missing: '$FixtureMesh'."
}

function Start-HeadlessStatusSmoke {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatusPath,
        [Parameter(Mandatory = $true)]
        [string]$OutputDir
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "dotnet.exe"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    @(
        $HelperDll,
        "--headless-smoke",
        "--input-package", $FixtureRoot,
        "--mesh", $FixtureMesh,
        "--metadata", (Join-Path $FixtureRoot "missing.cdmeta.json"),
        "--status", $StatusPath,
        "--output", $OutputDir,
        "--edit-operations", (Join-Path $OutputDir "edit_operations.json"),
        "--evaluation", (Join-Path $OutputDir "evaluation.md")
    ) | ForEach-Object { [void]$startInfo.ArgumentList.Add($_) }

    $process = [System.Diagnostics.Process]::Start($startInfo)
    return [pscustomobject]@{
        Process = $process
        StdoutTask = $process.StandardOutput.ReadToEndAsync()
        StderrTask = $process.StandardError.ReadToEndAsync()
    }
}

function Complete-HeadlessStatusSmoke {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Running
    )

    if (-not $Running.Process.WaitForExit(30000)) {
        $Running.Process.Kill($true)
        $Running.Process.WaitForExit()
        throw "The headless status-output smoke did not exit within 30 seconds."
    }
    return [pscustomobject]@{
        ExitCode = $Running.Process.ExitCode
        Stdout = $Running.StdoutTask.GetAwaiter().GetResult()
        Stderr = $Running.StderrTask.GetAwaiter().GetResult()
    }
}

function Invoke-HeadlessStatusSmoke {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatusPath,
        [Parameter(Mandatory = $true)]
        [string]$OutputDir
    )

    return Complete-HeadlessStatusSmoke (Start-HeadlessStatusSmoke -StatusPath $StatusPath -OutputDir $OutputDir)
}

$statusHandle = $null
try {
    [void][System.IO.Directory]::CreateDirectory($RunRoot)
    $statusPath = Join-Path $RunRoot "dotnet_status.json"

    # A status reader may keep the old file open. Sharing delete permits an
    # atomic replacement while deliberately refusing an in-place writer.
    [System.IO.File]::WriteAllText($statusPath, "{}")
    $readDeleteShare = [System.IO.FileShare]([System.IO.FileShare]::Read -bor [System.IO.FileShare]::Delete)
    $statusHandle = [System.IO.File]::Open(
        $statusPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        $readDeleteShare)
    $replaceResult = Invoke-HeadlessStatusSmoke `
        -StatusPath $statusPath `
        -OutputDir (Join-Path $RunRoot "replace-output")
    $statusHandle.Dispose()
    $statusHandle = $null
    if ($replaceResult.ExitCode -ne 0) {
        throw "Atomic status replacement failed with exit code $($replaceResult.ExitCode): $($replaceResult.Stderr)"
    }
    $payload = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    if ($payload.event -ne "saved") {
        throw "Atomic status replacement produced event '$($payload.event)' instead of 'saved'."
    }

    # The path-derived named mutex serializes commits from overlapping helper
    # processes without holding the file open. Wait until the helper has staged
    # its JSON, then prove it cannot publish until this test releases the mutex.
    $mutexStatusPath = Join-Path $RunRoot "mutex-status.json"
    [System.IO.File]::WriteAllText($mutexStatusPath, "{}")
    $statusBytes = [System.Text.Encoding]::UTF8.GetBytes($mutexStatusPath.ToUpperInvariant())
    $statusKey = [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($statusBytes))
    $statusMutex = [System.Threading.Mutex]::new(
        $false,
        "Local\CDMW.MeshEditorExperiment.Status.$statusKey")
    $ownsStatusMutex = $statusMutex.WaitOne(0)
    if (-not $ownsStatusMutex) {
        $statusMutex.Dispose()
        throw "The status-output smoke could not acquire its path mutex."
    }
    try {
        $running = Start-HeadlessStatusSmoke `
            -StatusPath $mutexStatusPath `
            -OutputDir (Join-Path $RunRoot "mutex-output")
        $stagingPattern = ([System.IO.Path]::GetFileName($mutexStatusPath) + ".*.tmp")
        $stagingDeadline = [DateTime]::UtcNow.AddSeconds(5)
        do {
            $staged = @(Get-ChildItem -LiteralPath $RunRoot -Filter $stagingPattern).Count -gt 0
            if (-not $staged -and -not $running.Process.HasExited) {
                Start-Sleep -Milliseconds 10
            }
        } while (-not $staged -and -not $running.Process.HasExited -and [DateTime]::UtcNow -lt $stagingDeadline)
        if (-not $staged -or $running.Process.HasExited) {
            $earlyResult = Complete-HeadlessStatusSmoke $running
            throw "The helper did not wait at the status publication mutex (exit $($earlyResult.ExitCode)): $($earlyResult.Stderr)"
        }
        $statusMutex.ReleaseMutex()
        $ownsStatusMutex = $false
        $mutexResult = Complete-HeadlessStatusSmoke $running
        if ($mutexResult.ExitCode -ne 0) {
            throw "Serialized status publication failed with exit code $($mutexResult.ExitCode): $($mutexResult.Stderr)"
        }
    }
    finally {
        if ($ownsStatusMutex) {
            $statusMutex.ReleaseMutex()
        }
        $statusMutex.Dispose()
    }

    # An unexpected exclusive lock must still end as a normal headless failure.
    # The fatal reporter must not throw a second exception that reaches Windows.
    [System.IO.File]::WriteAllText($statusPath, "{}")
    $statusHandle = [System.IO.File]::Open(
        $statusPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None)
    $lockedResult = Invoke-HeadlessStatusSmoke `
        -StatusPath $statusPath `
        -OutputDir (Join-Path $RunRoot "locked-output")
    $statusHandle.Dispose()
    $statusHandle = $null
    if ($lockedResult.ExitCode -ne 1) {
        throw "Locked status output escaped the headless failure path with exit code $($lockedResult.ExitCode)."
    }
    if ($lockedResult.Stderr -match "Unhandled exception") {
        throw "Locked status output escaped as an unhandled managed exception."
    }
    if ($lockedResult.Stderr -notmatch "System\.(?:IO\.IOException|UnauthorizedAccessException)") {
        throw "Locked status output did not preserve the original file error on stderr: $($lockedResult.Stderr)"
    }

    Write-Host "Resident .NET Mesh Editor status-output concurrency smoke passed."
}
finally {
    if ($null -ne $statusHandle) {
        $statusHandle.Dispose()
    }
    $resolvedRunRoot = [System.IO.Path]::GetFullPath($RunRoot)
    if (-not $resolvedRunRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove status-output smoke data outside system temp: '$resolvedRunRoot'."
    }
    if (Test-Path -LiteralPath $resolvedRunRoot) {
        Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    }
}
