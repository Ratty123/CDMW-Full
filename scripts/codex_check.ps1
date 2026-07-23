param(
    [ValidateSet("smoke", "stability", "responsiveness", "archive", "texture", "mesh", "mesh-unit", "full")]
    [string]$Area = "smoke",
    [string]$GameRoot = "",
    [string]$PytestBaseTemp = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

$TestsByArea = @{
    smoke = @(
        "tests/test_runtime_dependency_smoke.py"
    )
    stability = @(
        "tests/test_runtime_dependency_smoke.py",
        "tests/test_crash_reporting_guards.py",
        "tests/test_pyinstaller_temp_cleanup.py",
        "tests/test_startup_archive_path_async.py"
    )
    responsiveness = @(
        "tests/test_ui_responsiveness_source_guards.py",
        "tests/test_mesh_edit_responsiveness_source_guards.py",
        "tests/test_texture_workflow_ui_source_guards.py"
    )
    archive = @(
        "tests/test_archive_browser_virtual_model.py",
        "tests/test_archive_browser_filters.py",
        "tests/test_archive_caches.py",
        "tests/test_progressive_archive_preview.py",
        "tests/test_archive_extract_progress.py"
    )
    texture = @(
        "tests/test_texture_backend_retirement.py",
        "tests/test_texture_replacer_headless_harness.py",
        "tests/test_texture_native_backend.py",
        "tests/test_texture_workflow_guardrails.py",
        "tests/test_texture_workflow_ui_source_guards.py",
        "tests/test_texture_domain_profiles.py",
        "tests/test_texture_workflow_unavailable_editor.py",
        "tests/test_static_texture_replacement.py"
    )
    "mesh-unit" = @(
        "tests/test_mesh_dotnet_experiment.py",
        "tests/test_mesh_dotnet_experiment_output.py",
        "tests/test_mesh_dotnet_material_state.py",
        "tests/test_mesh_dotnet_material_visual_parity.py",
        "tests/test_mesh_dotnet_material_package.py",
        "tests/test_mesh_dotnet_material_dds_synthesis.py",
        "tests/test_mesh_dotnet_material_parameters.py",
        "tests/test_mesh_visual_audit_harness.py",
        "tests/test_mesh_visual_audit_integrity.py",
        "tests/test_mesh_visual_audit_package.py",
        "tests/test_dotnet_mesh_editor_layout_contract.py",
        "tests/test_dotnet_mesh_editor_tool_protocol_source.py",
        "tests/test_mesh_morph_slider_ui_source_guards.py",
        "tests/test_dotnet_preview_performance_contract.py",
        "tests/test_dotnet_texture_region_protocol.py",
        "tests/test_dotnet_material_parameter_protocol.py",
        "tests/test_native_preview_material_authority_protocol.py",
        "tests/test_dotnet_icon_capture_protocol.py",
        "tests/test_mesh_service_editing.py",
        "tests/test_mesh_editor_controller.py",
        "tests/test_mesh_editor_actions.py",
        "tests/test_mesh_editor_action_bar.py",
        "tests/test_mesh_builder_runtime_wiring.py",
        "tests/test_mesh_builder_construction_lifecycle.py",
        "tests/test_static_replacement_post_open_state.py",
        "tests/test_mesh_resident_editor_regressions.py",
        "tests/test_static_replacement_dotnet_presentation.py",
        "tests/test_mesh_harness_performance_contract.py",
        "tests/test_mesh_harness_scenario_registry.py",
        "tests/test_mesh_harness_real_dotnet_evidence.py",
        "tests/test_mesh_dotnet_live_stroke_dispatch.py",
        "tests/test_mesh_deformer.py",
        "tests/test_mesh_selection_tools.py",
        "tests/test_archive_structured_asset_preview.py",
        "tests/test_rigging_binary_parsers.py"
    )
}

Set-Location -LiteralPath $RepoRoot

$RealMeshScenario = "real-archive-mesh-editor-dotnet-edit-smoke"
$PytestTempArgs = @()
if ($PytestBaseTemp) {
    $PytestTempArgs = @("-p", "no:cacheprovider", "--basetemp=$PytestBaseTemp")
}

if ($Area -eq "full") {
    Write-Host "Running non-visual full pytest suite with $Python"
    & $Python -m pytest @PytestTempArgs
    exit $LASTEXITCODE
}

if ($Area -eq "mesh") {
    $ResolvedGameRoot = $GameRoot
    if (-not $ResolvedGameRoot) {
        $ResolvedGameRoot = $env:CDMW_GAME_ROOT
    }
    if (-not $ResolvedGameRoot) {
        $ResolvedGameRoot = "C:\games\Steam\steamapps\common\Crimson Desert"
    }
    $PamtPath = Join-Path $ResolvedGameRoot "0009\0.pamt"
    if (-not (Test-Path -LiteralPath $PamtPath)) {
        Write-Error "Mesh proof requires the real game archive index at '$PamtPath'. Pass -GameRoot or set CDMW_GAME_ROOT."
        exit 1
    }
    $ProofRunId = [Guid]::NewGuid().ToString("N")
    $OutputDir = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-real-archive-mesh-editor-dotnet-$ProofRunId"
    Write-Host "Running real in-game PAC .NET Mesh Editor proof from $PamtPath"
    & $Python tools\mesh_editor_dev_harness.py --scenario $RealMeshScenario --game-root $ResolvedGameRoot --output $OutputDir
    exit $LASTEXITCODE
}

$ConfiguredTests = @($TestsByArea[$Area])
if ($ConfiguredTests.Count -eq 0) {
    throw "No tests are configured for area '$Area'."
}
$MissingTests = @($ConfiguredTests | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $RepoRoot $_))
})
if ($MissingTests.Count -gt 0) {
    throw "Configured tests are missing for area '$Area': $($MissingTests -join ', ')"
}

Write-Host "Running $Area checks with $Python"
& $Python -m pytest @PytestTempArgs @ConfiguredTests
$PytestExitCode = $LASTEXITCODE
if ($PytestExitCode -ne 0) {
    exit $PytestExitCode
}

if ($Area -eq "mesh-unit") {
    $DotNetProject = Join-Path $RepoRoot "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
    Write-Host "Building the resident .NET Mesh Editor for the Bottom Tool Deck construction gate"
    & dotnet build $DotNetProject -c Release --nologo --verbosity:minimal
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $LayoutRunId = [Guid]::NewGuid().ToString("N")
    $LayoutReport = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-edit-mesh-layout-$LayoutRunId.json"
    $DotNetHelper = Join-Path $RepoRoot "tools\dotnet_mesh_editor_experiment\bin\Release\net8.0-windows\cdmw-mesh-dotnet-editor.exe"
    $LayoutProcess = Start-Process `
        -FilePath $DotNetHelper `
        -ArgumentList @("--headless-edit-mesh-layout-smoke", "--layout-report", $LayoutReport) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($LayoutProcess.ExitCode -ne 0) {
        Write-Error "Bottom Tool Deck construction smoke failed with exit code $($LayoutProcess.ExitCode)."
        exit $LayoutProcess.ExitCode
    }
    if (-not (Test-Path -LiteralPath $LayoutReport)) {
        Write-Error "Bottom Tool Deck construction smoke did not create '$LayoutReport'."
        exit 1
    }
    $LayoutPayload = Get-Content -LiteralPath $LayoutReport -Raw | ConvertFrom-Json
    if (-not $LayoutPayload.ok `
        -or -not $LayoutPayload.classic_default `
        -or -not $LayoutPayload.same_control_instances `
        -or -not $LayoutPayload.same_viewport_instance `
        -or -not $LayoutPayload.same_viewport_handle `
        -or -not $LayoutPayload.zero_size_splitter_construction `
        -or $LayoutPayload.pages_visited.Count -ne 5 `
        -or $LayoutPayload.renderer_started `
        -or $LayoutPayload.visible_window_started) {
        Write-Error "Bottom Tool Deck construction smoke returned an invalid report at '$LayoutReport'."
        exit 1
    }
    Remove-Item -LiteralPath $LayoutReport
    Write-Host "Bottom Tool Deck construction smoke passed."
}

exit 0
