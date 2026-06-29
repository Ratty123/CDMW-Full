param(
    [ValidateSet("smoke", "stability", "responsiveness", "archive", "texture", "mesh", "full")]
    [string]$Area = "smoke"
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
    mesh = @(
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

if ($Area -eq "full") {
    Write-Host "Running full pytest suite with $Python"
    & $Python -m pytest
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
& $Python -m pytest @ExistingTests
exit $LASTEXITCODE
