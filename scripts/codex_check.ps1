param(
    [ValidateSet("smoke", "stability", "responsiveness", "archive", "texture", "mesh", "mesh-unit", "full")]
    [string]$Area = "smoke",
    [string]$GameRoot = ""
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
        "tests/test_pyinstaller_temp_cleanup.py"
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
        "tests/test_texture_workflow_ui_source_guards.py",
        "tests/test_texture_domain_profiles.py",
        "tests/test_texture_workflow_unavailable_editor.py",
        "tests/test_static_texture_replacement.py"
    )
    "mesh-unit" = @(
        "tests/test_mesh_service_editing.py",
        "tests/test_mesh_editor_controller.py",
        "tests/test_mesh_editor_dev_harness.py",
        "tests/test_mesh_editor_actions.py",
        "tests/test_mesh_editor_action_bar.py",
        "tests/test_mesh_deformer.py",
        "tests/test_mesh_selection_tools.py",
        "tests/test_archive_structured_asset_preview.py",
        "tests/test_rigging_binary_parsers.py"
    )
}

Set-Location -LiteralPath $RepoRoot

$RealMeshScenario = "real-archive-mesh-editor-d3d11-side-by-side-edit-smoke"

if ($Area -eq "full") {
    Write-Host "Running full pytest suite with $Python"
    & $Python -m pytest
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
    if (-not (Test-Path -LiteralPath $ResolvedGameRoot)) {
        Write-Error "Mesh proof requires a real game root. Pass -GameRoot or set CDMW_GAME_ROOT. Synthetic unit coverage moved to -Area mesh-unit."
        exit 1
    }
    $OutputDir = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-real-archive-mesh-editor-d3d11-side-by-side-codex-check"
    Write-Host "Running real game Mesh Editor proof with $Python"
    & $Python tools\mesh_editor_dev_harness.py --scenario $RealMeshScenario --game-root $ResolvedGameRoot --output $OutputDir
    exit $LASTEXITCODE
}

$ExistingTests = @()
foreach ($Test in $TestsByArea[$Area]) {
    if (Test-Path -LiteralPath (Join-Path $RepoRoot $Test)) {
        $ExistingTests += $Test
    } else {
        Write-Host "Skipping missing test: $Test"
    }
}

if ($ExistingTests.Count -eq 0) {
    Write-Host "No existing tests configured for area '$Area'."
    exit 0
}

Write-Host "Running $Area checks with $Python"
if ($Area -eq "mesh-unit") {
    $MeshUnitFilter = "not native_mesh_editor_d3d11_delta_scenario_uses_vertex_update_without_fallback and not native_mesh_editor_standalone_stroke_scenario_uses_native_session_without_fallback and not native_mesh_editor_qt_responsiveness_scenario_uses_worker_without_fallback and not native_mesh_editor_qt_cancellation_scenario_cancels_without_fallback"
    & $Python -m pytest @ExistingTests -k $MeshUnitFilter
} else {
    & $Python -m pytest @ExistingTests
}
exit $LASTEXITCODE
