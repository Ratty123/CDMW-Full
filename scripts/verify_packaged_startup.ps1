param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath,
    [ValidateSet("default", "mesh_builder", "mesh_archive_textures")]
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
        [ValidateSet("default", "mesh_builder", "mesh_archive_textures")]
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
        $detail = [string]$payload.detail
        $suffix = if ([string]::IsNullOrWhiteSpace($detail)) { "" } else { " Detail: $detail" }
        throw "Packaged startup smoke reported failure at stage '$([string]$payload.stage)'.$suffix"
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
    Assert-PackagedBundledHelpers -Payload $payload
    if ($ExpectedTarget -eq "mesh_archive_textures") {
        Assert-PackagedMeshTextureEvidence -Payload $payload
    }
    return $payload
}


function Assert-PackagedMeshTextureEvidence {
    param([Parameter(Mandatory = $true)]$Payload)

    if (-not ($Payload.PSObject.Properties.Name -contains "evidence")) {
        throw "Packaged Mesh Editor texture smoke reported no evidence section."
    }
    $evidence = $Payload.evidence
    if ([string]$evidence.schema -ne "cdmw_packaged_mesh_texture_smoke_v1") {
        throw "Packaged Mesh Editor texture smoke returned an unknown evidence schema."
    }
    if ($evidence.read_only -ne $true -or $evidence.archive_sources_unchanged -ne $true) {
        throw "Packaged Mesh Editor texture smoke did not prove read-only archive access."
    }
    foreach ($modeName in @("normal_mode", "edit_mode")) {
        $mode = $evidence.$modeName
        if ([string]$mode.selected_mode -ne "textured") {
            throw "Packaged Mesh Editor texture smoke did not retain Solid (Textured) in $modeName."
        }
        if ([string]$mode.renderer_resources.display_mode -ne "textured") {
            throw "Packaged Mesh Editor texture smoke renderer did not apply textured mode in $modeName."
        }
        if ($mode.renderer_resources.textures_enabled -ne $true) {
            throw "Packaged Mesh Editor texture smoke renderer disabled texture sampling in $modeName."
        }
        if ([int64]$mode.renderer_resources.live_texture_srvs -le 0) {
            throw "Packaged Mesh Editor texture smoke reported no live texture SRV in $modeName."
        }
        if ([int64]$mode.renderer_resources.textured_draw_calls -le 0) {
            throw "Packaged Mesh Editor texture smoke reported no textured draw call in $modeName."
        }
    }
    if ([int64]$evidence.material_update.resource_count -le 0) {
        throw "Packaged Mesh Editor texture smoke compiled zero texture resources."
    }
    if ([int64]$evidence.material_update.resource_file_count -ne [int64]$evidence.material_update.resource_count) {
        throw "Packaged Mesh Editor texture smoke compiled a missing texture resource."
    }
    if (@($evidence.material_failures).Count -ne 0) {
        throw "Packaged Mesh Editor texture smoke recorded material failures."
    }
    Write-Host (
        "Packaged Mesh Editor textures verified: model={0}, resources={1}, live_srvs={2}" -f `
            [string]$evidence.model_path, `
            [int64]$evidence.material_update.resource_count, `
            [int64]$evidence.edit_mode.renderer_resources.live_texture_srvs
    )
}


function Assert-PackagedBundledHelpers {
    param([Parameter(Mandatory = $true)]$Payload)

    # Helpers the app ships with itself must resolve from inside the package.
    # Nothing outside a packaged run can prove this: the payload directory and
    # sys._MEIPASS only exist there, which is how OpenImageIO shipped for a
    # while resolving out of the developer's virtualenv and reporting
    # unavailable to every user.
    # Set-StrictMode turns a missing property into a PropertyNotFoundException,
    # so a result file written before this section existed would fail with that
    # instead of the explanation below.
    $helpers = $null
    if ($Payload.PSObject.Properties.Name -contains "bundled_helpers") {
        $helpers = $Payload.bundled_helpers
    }
    if ($null -eq $helpers) {
        throw (
            "Packaged startup smoke reported no bundled_helpers section. The packaged build " +
            "cannot confirm that helpers shipping inside it actually resolve."
        )
    }
    $helperList = @($helpers)
    if ($helperList.Count -eq 0) {
        throw "Packaged startup smoke reported an empty bundled_helpers list; expected at least one bundled helper."
    }
    $unresolved = @($helperList | Where-Object { [string]$_.status -ne "available" })
    if ($unresolved.Count -gt 0) {
        $rendered = ($unresolved | ForEach-Object { "{0}={1}" -f [string]$_.key, [string]$_.status }) -join ", "
        throw "Bundled helpers did not resolve inside the package: $rendered"
    }
    $rendered = ($helperList | ForEach-Object {
        "{0} ({1})" -f [string]$_.key, [string]$_.source
    }) -join ", "
    Write-Host "Bundled helpers resolved in package: $rendered"
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
        [ValidateSet("default", "mesh_builder", "mesh_archive_textures")]
        [string]$SmokeTarget = "default"
    )

    $resolvedExecutable = (Resolve-Path -LiteralPath $Path).Path
    $runId = [Guid]::NewGuid().ToString("N")
    $smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-packaged-startup-$runId"
    $resultPath = Join-Path $smokeRoot "startup-result.json"
    $crashRoot = Join-Path $smokeRoot "crash-reports"
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
    $targetEnvironment = if ($SmokeTarget -eq "default") { "" } else { $SmokeTarget }
    if (
        $SmokeTarget -eq "mesh_archive_textures" -and
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("CDMW_GUI_STARTUP_SMOKE_MESH_ASSET", "Process"))
    ) {
        throw (
            "Target mesh_archive_textures requires CDMW_GUI_STARTUP_SMOKE_MESH_ASSET " +
            "to name the game root or 0009/0.pamt."
        )
    }

    $smokeEnvironment = [ordered]@{
        "TEMP" = $smokeRoot
        "TMP" = $smokeRoot
        "QT_QPA_PLATFORM" = if ($SmokeTarget -eq "mesh_archive_textures") { "windows" } else { "offscreen" }
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
        $startParameters = @{
            FilePath = $resolvedExecutable
            WorkingDirectory = (Split-Path -Parent $resolvedExecutable)
            PassThru = $true
        }
        if ($SmokeTarget -ne "mesh_archive_textures") {
            $startParameters["WindowStyle"] = "Hidden"
        }
        # D3D11 must own a genuinely shown HWND to exercise swap-chain painting.
        # The mesh texture target moves that real window off-screen inside the
        # app; SW_HIDE here would suppress every frame and test a state the GUI
        # can never enter instead of validating the packaged renderer.
        $process = Start-Process @startParameters
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
