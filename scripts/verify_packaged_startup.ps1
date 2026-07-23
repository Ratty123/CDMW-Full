param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,
    [ValidateSet("default", "mesh_builder")]
    [string]$Target = "default",
    [ValidateRange(1, 900)]
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest


function Assert-PackagedStartupResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResultPath,
        [ValidateSet("default", "mesh_builder")]
        [string]$ExpectedTarget = "default"
    )

    if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
        throw "Packaged startup smoke did not write its result marker: $ResultPath"
    }
    try {
        $payload = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    } catch {
        throw "Packaged startup smoke wrote invalid result JSON: $($_.Exception.Message)"
    }
    if ($payload.ok -ne $true) {
        throw "Packaged startup smoke reported failure at stage '$([string]$payload.stage)'."
    }
    if ([string]$payload.stage -ne "post_construction") {
        throw "Packaged startup smoke did not prove post-construction success. Stage: '$([string]$payload.stage)'."
    }
    if ([string]$payload.target -ne $ExpectedTarget) {
        throw (
            "Packaged startup smoke returned an unexpected target: " +
            "'$([string]$payload.target)' (expected '$ExpectedTarget')."
        )
    }
    if ([int64]$payload.pid -le 0) {
        throw "Packaged startup smoke result did not contain a valid process id."
    }
    return $payload
}


function Stop-PackagedStartupProcess {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process -or $Process.HasExited) {
        return
    }
    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path -LiteralPath $taskkill) {
        & $taskkill /PID $Process.Id /T /F 2>$null | Out-Null
    } else {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
    $Process.WaitForExit(5000) | Out-Null
}


function Remove-PackagedStartupRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\', '/')
    $target = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $tempPrefix = $tempRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing packaged-startup cleanup outside the system temp directory: $target"
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}


function Invoke-PackagedStartupVerification {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [int]$Timeout,
        [ValidateSet("default", "mesh_builder")]
        [string]$SmokeTarget = "default"
    )

    $resolvedExecutable = (Resolve-Path -LiteralPath $Path).Path
    $runId = [Guid]::NewGuid().ToString("N")
    $smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-packaged-startup-$runId"
    $resultPath = Join-Path $smokeRoot "startup-result.json"
    $crashRoot = Join-Path $smokeRoot "crash-reports"
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
    $targetEnvironment = if ($SmokeTarget -eq "default") { "" } else { $SmokeTarget }

    $smokeEnvironment = [ordered]@{
        "TEMP" = $smokeRoot
        "TMP" = $smokeRoot
        "QT_QPA_PLATFORM" = "offscreen"
        "CDMW_GUI_STARTUP_SMOKE" = "1"
        "CDMW_GUI_STARTUP_SMOKE_RESULT" = $resultPath
        "CDMW_GUI_STARTUP_SMOKE_TARGET" = $targetEnvironment
        "CDMW_SINGLE_INSTANCE_SCOPE" = "packaged-startup-$runId"
        "CDMW_CRASH_DIR" = $crashRoot
        "CDMW_TEMP_CACHE_ROOT" = (Join-Path $smokeRoot "cache")
    }
    $previousEnvironment = @{}
    $process = $null
    try {
        foreach ($name in $smokeEnvironment.Keys) {
            $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            [Environment]::SetEnvironmentVariable($name, $smokeEnvironment[$name], "Process")
        }
        $process = Start-Process -FilePath $resolvedExecutable `
            -WorkingDirectory (Split-Path -Parent $resolvedExecutable) `
            -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit($Timeout * 1000)) {
            Stop-PackagedStartupProcess -Process $process
            throw "Packaged startup smoke target '$SmokeTarget' timed out after $Timeout second(s)."
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Packaged startup smoke exited with code $($process.ExitCode)."
        }
        $payload = Assert-PackagedStartupResult `
            -ResultPath $resultPath `
            -ExpectedTarget $SmokeTarget
        Write-Host (
            "Packaged startup verified: stage={0}, target={1}, pid={2}" -f `
                $payload.stage, $payload.target, $payload.pid
        )
    } finally {
        Stop-PackagedStartupProcess -Process $process
        if ($null -ne $process) {
            $process.Dispose()
        }
        foreach ($name in $smokeEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
        Remove-PackagedStartupRoot -Path $smokeRoot
    }
}


if ($MyInvocation.InvocationName -ne ".") {
    Invoke-PackagedStartupVerification `
        -Path $ExecutablePath `
        -Timeout $TimeoutSeconds `
        -SmokeTarget $Target
}
