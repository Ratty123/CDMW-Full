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
    Assert-PackagedRustMeshEditorEvidence -Payload $payload
    if ($ExpectedTarget -eq "mesh_archive_textures") {
        Assert-PackagedMeshTextureEvidence -Payload $payload
    }
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
        "build_profile",
        "locked_dependencies",
        "executable",
        "control_contract",
        "control_contract_schema",
        "capabilities",
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
        [string]$provenance.build_profile -ne "release" -or
        $provenance.locked_dependencies -ne $true -or
        [string]$provenance.executable -cne "cdmw_mesh_lab.exe" -or
        [string]$provenance.control_contract -cne "cdmw_mesh_lab.control-contract.json" -or
        [string]$provenance.control_contract_schema -ne "cdmw_rust_mesh_editor_control_contract_v2" -or
        @($provenance.capabilities) -notcontains "embedded_child_window_v1" -or
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


function Assert-PackagedMeshTextureEvidence {
    param([Parameter(Mandatory = $true)]$Payload)

    if (-not ($Payload.PSObject.Properties.Name -contains "evidence")) {
        throw "Packaged Mesh Editor texture smoke reported no evidence section."
    }
    $evidence = $Payload.evidence
    if ([string]$evidence.schema -ne "cdmw_packaged_mesh_editor_controls_smoke_v3") {
        throw "Packaged Mesh Editor texture smoke returned an unknown evidence schema."
    }
    if ($evidence.read_only -ne $true -or $evidence.archive_sources_unchanged -ne $true) {
        throw "Packaged Mesh Editor texture smoke did not prove read-only archive access."
    }
    if (
        [string]$evidence.production_route -ne "MainWindow._launch_archive_mesh_editor_for_entry" -or
        $evidence.actual_csharp_controls -ne $true -or
        $evidence.global_mouse_input_used -ne $false -or
        [int64]$evidence.physical_mouse_input.gesture_count -ne 0 -or
        $evidence.physical_mouse_input.active -ne $false -or
        [int64]$evidence.physical_mouse_input.restore_failure_count -ne 0
    ) {
        throw "Packaged Mesh Editor smoke used global desktop input instead of the helper-local UI-thread probe."
    }
    $viewport = $evidence.viewport_availability
    if (
        $viewport.before_session.standalone_workspace_current -ne $true -or
        $viewport.before_session.host_visible -ne $true -or
        $viewport.after_close.standalone_workspace_current -ne $true -or
        $viewport.after_close.host_visible -ne $true -or
        $viewport.before_controls.owned -ne $true -or
        $viewport.before_controls.visible -ne $true -or
        $viewport.before_controls.nonzero -ne $true -or
        $viewport.after_textured.visible -ne $true -or
        $viewport.after_textured.nonzero -ne $true -or
        $viewport.after_select.visible -ne $true -or
        $viewport.after_select.nonzero -ne $true -or
        $viewport.after_grab_history.visible -ne $true -or
        $viewport.after_grab_history.nonzero -ne $true
    ) {
        throw "Packaged Mesh Editor smoke did not keep the viewport visibly available across empty, textured, Select, and closed states."
    }
    $mode = $evidence.solid_textured
    if ($mode.actual_controls -ne $true -or [string]$mode.selected_mode -ne "textured") {
        throw "Packaged Mesh Editor smoke did not retain Solid (Textured) through the real control."
    }
    if ([string]$mode.renderer_resources.display_mode -ne "textured") {
        throw "Packaged Mesh Editor texture smoke renderer did not apply textured mode."
    }
    if ($mode.renderer_resources.textures_enabled -ne $true) {
        throw "Packaged Mesh Editor texture smoke renderer disabled texture sampling."
    }
    if ([int64]$mode.renderer_resources.live_texture_srvs -le 0) {
        throw "Packaged Mesh Editor texture smoke reported no live texture SRV."
    }
    if ([int64]$mode.renderer_resources.textured_draw_calls -le 0) {
        throw "Packaged Mesh Editor texture smoke reported no textured draw call."
    }
    if ([string]$mode.renderer_resources.draw_counter_source -ne "renderer.live_metrics.geometry_resources") {
        throw "Packaged Mesh Editor texture smoke used cached rather than live draw counters."
    }
    if (
        $evidence.select.ok -ne $true -or
        $evidence.select.actual_control -ne $true -or
        [string]$evidence.select.input_backend -ne "helper_ui_thread_resident_probe" -or
        $evidence.select.global_mouse_input_used -ne $false
    ) {
        throw "Packaged Mesh Editor smoke did not prove the real Select control and authoritative helper-owned selection path."
    }
    if (
        [string]$evidence.select.overlay.counter_source -ne "renderer.live_metrics.geometry_resources" -or
        [int64]$evidence.select.overlay.committed_primitives_after -le [int64]$evidence.select.overlay.committed_primitives_before -or
        $evidence.select.capture.ok -ne $true
    ) {
        throw "Packaged Mesh Editor smoke did not prove and capture a newly drawn committed selection highlight."
    }
    if (
        $evidence.control_continuity.ok -ne $true -or
        $evidence.control_continuity.actual_controls -ne $true -or
        [int64]$evidence.control_continuity.case_count -ne 8 -or
        [double]$evidence.control_continuity.settlement_p95_ms -gt 50.0 -or
        @($evidence.control_continuity.cases | Where-Object { $_.stable -ne $true }).Count -ne 0
    ) {
        throw "Packaged Mesh Editor smoke did not preserve the resident viewport across all real tool and page controls."
    }
    $history = $evidence.grab_undo_redo
    if (
        $history.ok -ne $true -or
        $history.actual_controls -ne $true -or
        @($history.gates.PSObject.Properties | Where-Object { $_.Value -ne $true }).Count -ne 0 -or
        $evidence.grab_redo_capture.ok -ne $true
    ) {
        throw "Packaged Mesh Editor smoke did not prove Grab, Undo, Grab, Undo, and Redo through the real controls."
    }
    if (-not ($evidence.PSObject.Properties.Name -contains "resident_interactions")) {
        throw "Packaged Mesh Editor smoke reported no resident interaction proof for the required tools."
    }
    $residentInteractions = $evidence.resident_interactions
    $requiredResidentTools = @("select", "move", "grab", "smooth", "inflate", "pinch")
    $residentCorrelationFields = @(
        "process_generation",
        "helper_process_id",
        "request_id",
        "gesture_id",
        "transaction_sequence",
        "base_revision",
        "target_revision",
        "base_selection_revision",
        "target_selection_revision",
        "topology_generation"
    )
    $residentTimingFields = @(
        "begin_ms",
        "input_sample_p95_ms",
        "input_sample_max_ms",
        "finish_ms",
        "total_ms"
    )
    foreach ($residentTool in $requiredResidentTools) {
        $residentProperty = $residentInteractions.PSObject.Properties[$residentTool]
        if ($null -eq $residentProperty) {
            throw "Packaged Mesh Editor smoke did not report resident interaction evidence for '$residentTool'."
        }
        $resident = $residentProperty.Value
        $residentGates = @($resident.gates.PSObject.Properties | Where-Object { $_.Value -ne $true })
        $gesture = $resident.gesture
        $transaction = $gesture.resident_interaction_transaction
        $acknowledgement = $gesture.commit_v2_acknowledgement
        $missingTiming = @(
            $residentTimingFields |
                Where-Object { $gesture.timing.PSObject.Properties.Name -notcontains $_ }
        )
        if (
            $resident.ok -ne $true -or
            [string]$gesture.input_backend -ne "helper_ui_thread_resident_probe" -or
            $gesture.global_mouse_input_used -ne $false -or
            [int64]$gesture.resident_interaction_transaction_count -ne 1 -or
            [int64]$gesture.helper_originated_mutation_echo_count -ne 0 -or
            [string]$gesture.terminal_event -ne "resident_interaction_transaction" -or
            [string]$gesture.operator.state -ne "idle" -or
            $gesture.probe_acknowledgement.ok -ne $true -or
            [string]$gesture.probe_acknowledgement.status -ne "applied" -or
            [string]$acknowledgement.status -ne "applied" -or
            $missingTiming.Count -ne 0 -or
            @($residentTimingFields | Where-Object { [double]$gesture.timing.$_ -lt 0.0 }).Count -ne 0 -or
            $residentGates.Count -ne 0
        ) {
            throw "Packaged Mesh Editor smoke did not prove an idle, one-transaction, applied resident '$residentTool' interaction."
        }
        if (
            [int64]$gesture.probe_acknowledgement.request_id -ne [int64]$transaction.request_id -or
            [int64]$acknowledgement.request_id -ne [int64]$transaction.request_id -or
            [string]$acknowledgement.session_id -ne [string]$transaction.session_id -or
            [string]$acknowledgement.sha256 -ne [string]$transaction.sha256
        ) {
            throw "Packaged Mesh Editor smoke lost resident '$residentTool' request/session/digest correlation."
        }
        foreach ($residentField in $residentCorrelationFields) {
            if ([int64]$acknowledgement.$residentField -ne [int64]$transaction.$residentField) {
                throw "Packaged Mesh Editor smoke lost resident '$residentTool' commit-v2 correlation field '$residentField'."
            }
        }
    }
    if (
        $evidence.desktop_input.ok -ne $true -or
        [string]$evidence.desktop_input.method -ne "helper_ui_thread_no_global_input" -or
        [int64]$evidence.desktop_input.gesture_count -ne 0 -or
        $evidence.desktop_input.active -ne $false -or
        [int64]$evidence.desktop_input.restore_failure_count -ne 0
    ) {
        throw "Packaged Mesh Editor smoke did not keep all interaction inside the helper UI thread."
    }
    if (
        [string]::IsNullOrWhiteSpace([string]$evidence.helper.path) -or
        [string]::IsNullOrWhiteSpace([string]$evidence.helper.sha256) -or
        [int64]$evidence.helper.process_id -le 0
    ) {
        throw "Packaged Mesh Editor smoke did not identify the helper executable it actually ran."
    }
    $provenance = $evidence.helper.provenance
    $nativeAbi = $provenance.native_abi
    if (
        @($evidence.helper.capabilities) -notcontains "resident_interaction_abi_v1" -or
        [int64]$provenance.protocol_version -ne 3 -or
        [string]$provenance.manifest_mode -ne "release_manifest" -or
        [string]$provenance.manifest_id -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$provenance.source_revision -notmatch "^[0-9a-fA-F]{40}$" -or
        [string]$provenance.process_sha256 -ne [string]$evidence.helper.sha256 -or
        [string]$provenance.shader_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$provenance.renderer_backend -ne "d3d11_vortice_shader" -or
        [string]$provenance.edit_backend -ne "cdmw_mesh_core_0.1" -or
        [int64]$nativeAbi.abi_version -ne 1 -or
        [string]$nativeAbi.contract -ne "cdmw_mesh_interaction_abi_v1" -or
        [string]$nativeAbi.backend -ne "cdmw_mesh_core_0.1" -or
        [System.IO.Path]::GetFileName([string]$nativeAbi.library_path) -ne "cdmw-mesh-core.dll" -or
        [string]$nativeAbi.library_sha256 -notmatch "^[0-9a-fA-F]{64}$" -or
        [string]$nativeAbi.header_sha256 -notmatch "^[0-9a-fA-F]{64}$"
    ) {
        throw "Packaged Mesh Editor smoke did not prove the packaged helper native interaction ABI provenance."
    }
    if (
        $evidence.application.frozen -ne $true -or
        $evidence.application.helper_inside_bundle_root -ne $true -or
        [string]::IsNullOrWhiteSpace([string]$evidence.application.executable_sha256)
    ) {
        throw "Packaged Mesh Editor smoke used an unfrozen app or a helper outside that app's unpacked bundle."
    }
    if ($evidence.capture.ok -ne $true) {
        throw "Packaged Mesh Editor smoke did not capture the real textured D3D11 viewport."
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
        "Packaged Mesh Editor controls verified: model={0}, resources={1}, live_srvs={2}, select_backend={3}" -f `
            [string]$evidence.model_path, `
            [int64]$evidence.material_update.resource_count, `
            [int64]$evidence.solid_textured.renderer_resources.live_texture_srvs, `
            [string]$evidence.select.input_backend
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
        # The mesh texture target shows without activation on its assigned
        # monitor; SW_HIDE here would suppress every frame and test a state the
        # GUI can never enter instead of validating the packaged renderer.
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
