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
    Assert-PackagedRustMeshEditorEvidence -Payload $payload
    return $payload
}


function Assert-PackagedRustMeshEditorEvidence {
    param([Parameter(Mandatory = $true)]$Payload)

    if (-not ($Payload.PSObject.Properties.Name -contains "rust_mesh_editor")) {
        throw (
            "Packaged startup smoke reported no independent rust_mesh_editor section. " +
            "The build cannot prove that Rust Edit Mesh was bundled."
        )
    }
    $proof = $Payload.rust_mesh_editor
    if ($null -eq $proof) {
        throw "Packaged startup smoke reported an empty rust_mesh_editor section."
    }
    $requiredProofFields = @(
        "schema",
        "status",
        "reason",
        "source",
        "frozen",
        "path",
        "relative_path",
        "inside_bundle_root",
        "executable_sha256",
        "provenance_path",
        "provenance_relative_path",
        "provenance_inside_bundle_root",
        "provenance_sha256",
        "provenance"
    )
    $missingProofFields = @(
        $requiredProofFields |
            Where-Object { $proof.PSObject.Properties.Name -notcontains $_ }
    )
    if ($missingProofFields.Count -gt 0) {
        throw (
            "Packaged Rust Edit Mesh evidence is incomplete: " +
            ($missingProofFields -join ", ")
        )
    }
    if ([string]$proof.schema -ne "cdmw_packaged_rust_mesh_editor_v1") {
        throw "Packaged Rust Edit Mesh evidence returned an unknown schema."
    }
    if ([string]$proof.status -ne "available") {
        $reason = [string]$proof.reason
        $suffix = if ([string]::IsNullOrWhiteSpace($reason)) { "" } else { " Reason: $reason" }
        throw "Packaged Rust Edit Mesh is unavailable.$suffix"
    }
    if (
        $proof.frozen -ne $true -or
        [string]$proof.source -ne "frozen" -or
        $proof.inside_bundle_root -ne $true -or
        [string]$proof.relative_path -cne "native/rust_mesh_editor/cdmw_mesh_lab.exe" -or
        [System.IO.Path]::GetFileName([string]$proof.path) -cne "cdmw_mesh_lab.exe"
    ) {
        throw (
            "Packaged Rust Edit Mesh did not resolve as " +
            "native/rust_mesh_editor/cdmw_mesh_lab.exe inside the frozen bundle."
        )
    }
    if (
        $proof.provenance_inside_bundle_root -ne $true -or
        [string]$proof.provenance_relative_path -cne "native/rust_mesh_editor/cdmw_mesh_lab.manifest.json" -or
        [System.IO.Path]::GetFileName([string]$proof.provenance_path) -cne "cdmw_mesh_lab.manifest.json" -or
        [System.IO.Path]::GetDirectoryName([string]$proof.path) -cne `
            [System.IO.Path]::GetDirectoryName([string]$proof.provenance_path)
    ) {
        throw "Packaged Rust Edit Mesh did not report its sibling provenance manifest."
    }
    if (
        [string]$proof.executable_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$proof.provenance_sha256 -notmatch "^[0-9a-fA-F]{64}$"
    ) {
        throw "Packaged Rust Edit Mesh did not report valid observed file hashes."
    }

    $provenance = $proof.provenance
    if ($null -eq $provenance) {
        throw "Packaged Rust Edit Mesh reported no provenance manifest payload."
    }
    $requiredProvenanceFields = @(
        "schema",
        "renderer",
        "edit_backend",
        "protocol",
        "authoring_package",
        "preview_protocol",
        "preview_package",
        "preview_backend",
        "build_profile",
        "locked_dependencies",
        "executable",
        "control_contract",
        "control_contract_schema",
        "capabilities",
        "preview_capabilities",
        "source_revision",
        "source_tree_sha256",
        "cargo_lock_sha256",
        "executable_sha256",
        "control_contract_sha256",
        "cargo_version",
        "rustc_version"
    )
    $missingProvenanceFields = @(
        $requiredProvenanceFields |
            Where-Object { $provenance.PSObject.Properties.Name -notcontains $_ }
    )
    if ($missingProvenanceFields.Count -gt 0) {
        throw (
            "Packaged Rust Edit Mesh provenance is incomplete: " +
            ($missingProvenanceFields -join ", ")
        )
    }
    if (
        [string]$provenance.schema -ne "cdmw_rust_mesh_editor_build_provenance_v1" -or
        [string]$provenance.renderer -ne "wgpu_d3d12_rust" -or
        [string]$provenance.edit_backend -ne "cdmw_rust_mesh_0.1" -or
        [string]$provenance.protocol -ne "cdmw_rust_mesh_editor_protocol_v1" -or
        [string]$provenance.authoring_package -ne "cdmw_rust_mesh_authoring_package_v1" -or
        [string]$provenance.preview_protocol -ne "cdmw_rust_preview_protocol_v1" -or
        [string]$provenance.preview_package -ne "cdmw_rust_preview_package_v1" -or
        [string]$provenance.preview_backend -ne "cdmw_rust_preview_0.1" -or
        [string]$provenance.build_profile -ne "release" -or
        $provenance.locked_dependencies -ne $true -or
        [string]$provenance.executable -cne "cdmw_mesh_lab.exe" -or
        [string]$provenance.control_contract -cne "cdmw_mesh_lab.control-contract.json" -or
        [string]$provenance.control_contract_schema -ne "cdmw_rust_mesh_editor_control_contract_v2" -or
        @($provenance.capabilities) -notcontains "embedded_child_window_v1" -or
        @($provenance.capabilities) -notcontains "rust_preview_runtime_v1" -or
        @($provenance.preview_capabilities) -notcontains "resident_preview_package_replace_v2" -or
        @($provenance.preview_capabilities) -notcontains "static_replacement_mesh_input_v1" -or
        [string]$provenance.source_revision -notmatch "^[0-9a-fA-F]{40}$" -or
        [string]$provenance.source_tree_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$provenance.cargo_lock_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$provenance.control_contract_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]::IsNullOrWhiteSpace([string]$provenance.cargo_version) -or
        [string]::IsNullOrWhiteSpace([string]$provenance.rustc_version)
    ) {
        throw (
            "Packaged Rust Edit Mesh provenance did not prove the locked Release " +
            "wgpu/D3D12 Rust editor contract."
        )
    }
    if (
        -not [string]::Equals(
            [string]$provenance.executable_sha256,
            [string]$proof.executable_sha256,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Packaged Rust Edit Mesh executable hash does not match its provenance manifest."
    }
    Write-Host (
        "Packaged Rust Edit Mesh verified: path={0}, renderer={1}, edit_backend={2}, protocol={3}" -f `
            [string]$proof.relative_path, `
            [string]$provenance.renderer, `
            [string]$provenance.edit_backend, `
            [string]$provenance.protocol
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
        $startParameters = @{
            FilePath = $resolvedExecutable
            WorkingDirectory = (Split-Path -Parent $resolvedExecutable)
            PassThru = $true
        }
        $startParameters["WindowStyle"] = "Hidden"
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
