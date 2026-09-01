param(
    [ValidateSet("smoke", "stability", "responsiveness", "archive", "texture", "mesh", "mesh-contract", "mesh-native", "mesh-unit", "rust-mesh-lab-unit", "rust-mesh-lab-gpu", "rust-mesh-lab-stress", "full")]
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
        "tests/test_runtime_dependency_smoke.py",
        "tests/test_restructure_runtime_regression_smoke.py",
        # Exact, Free Edit, and Read Only policy routing plus atomic non-exact
        # output. These fail at user-command time if session filtering drifts.
        "tests/test_mesh_output_policy.py",
        "tests/test_mesh_editor_ui_state.py",
        "tests/test_mesh_editor_ui_state_bridge.py",
        # Generated-manifest freshness. Both of these are verified by
        # build_pyside6_app.ps1 before it compiles anything, so a stale one is a
        # failed release build. Source line numbers are informational; only
        # key/path/sink/manual/exclusion changes affect freshness.
        "tests/test_window_feature_controller.py",
        "tests/test_localization_catalog_contracts.py",
        "tests/test_localization_runtime_owner.py",
        "tests/test_documentation_dialog.py",
        "tests/test_character_context.py",
        "tests/test_compact_shell.py",
        "tests/test_compact_shell_presentations.py",
        "tests/test_compact_shell_visual_harness.py",
        "tests/test_shell_theme_controller.py",
        "tests/test_theme_surface_coherence.py",
        "tests/test_format_explorer.py",
        "tests/test_translation_studio.py",
        "tests/test_translation_studio_theme.py",
        # New Item Studio: headless construction, and a plan driven through its panels.
        "tests/test_combo_popup_limiter.py",
        "tests/test_new_item_item_preview.py",
        "tests/test_new_item_fit.py",
        "tests/test_new_item_model_cleanup.py",
        "tests/test_new_item_studio_tab.py",
        "tests/test_new_item_glow_preview.py",
        "tests/test_effect_character_reference.py",
        "tests/test_effect_placement_dialog.py",
        "tests/test_new_item_effect_workspace.py",
        "tests/test_new_item_workflow_header.py"
    )
    stability = @(
        "tests/test_runtime_dependency_smoke.py",
        "tests/test_crash_reporting_guards.py",
        "tests/test_utility_task_refusal_logging.py",
        "tests/test_hang_watchdog_keeps_reporting.py",
        "tests/test_pyinstaller_temp_cleanup.py",
        "tests/test_startup_archive_path_async.py",
        "tests/test_session_recorder.py",
        "tests/test_window_frame_blink_detection.py",
        "tests/test_session_monitor_timeline.py",
        "tests/test_settings_tab_flush_persistence.py",
        "tests/test_profile_controller.py",
        "tests/test_asset_authoring_service.py",
        "tests/test_packaged_bundled_helper_reporting.py",
        "tests/test_shell_app_startup.py",
        "tests/test_shell_startup_controller.py"
    )
    responsiveness = @(
        "tests/test_attachment_async_io.py",
        "tests/test_character_context.py",
        "tests/test_lazy_tool_tabs.py",
        "tests/test_translation_studio.py",
        "tests/test_ui_responsiveness_source_guards.py",
        "tests/test_mesh_edit_responsiveness_source_guards.py",
        "tests/test_texture_workflow_ui_source_guards.py",
        "tests/test_localization_async_io.py",
        "tests/test_localization_translations.py",
        "tests/test_localization_catalog_contracts.py",
        "tests/test_localization_translation_quality.py",
        "tests/test_compact_shell.py",
        "tests/test_compact_shell_presentations.py",
        "tests/test_persistent_tree_headers.py"
    )
    archive = @(
        "tests/test_archive_browser_virtual_model.py",
        "tests/test_archive_browser_filters.py",
        "tests/test_archive_caches.py",
        "tests/test_archive_game_update_evidence.py",
        "tests/test_progressive_archive_preview.py",
        "tests/test_release_inspired_improvements.py",
        "tests/test_scene_import_policy.py",
        "tests/test_archive_preview_request_coalescing.py",
        "tests/test_archive_remote_window_bridge.py",
        "tests/test_archive_remote_preview_dependencies.py",
        "tests/test_archive_remote_finder_dialog.py",
        "tests/test_archive_preview_dependency_optimization.py",
        "tests/test_archive_d3d11_process_lifecycle.py",
        "tests/test_archive_extract_progress.py",
        "tests/test_archive_output_path_safety.py",
        "tests/test_archive_progress_bar_writes_on_change.py",
        # Unregistered until 2026-08-08, which is how its progress-bar and
        # selection-context needles sat stale across four commits.
        "tests/test_archive_browser_asset_understanding_ui_source_guards.py",
        # Archive writers: in-place patching, brand-new PAMT entries, and the
        # table/part-prefab owners the New Item flow appends through.
        "tests/test_archive_patch_preflight.py",
        "tests/test_archive_mutation_service.py",
        "tests/test_archive_overlay_install.py",
        "tests/test_archive_entry_addition.py",
        "tests/test_pappt_format.py",
        "tests/test_stringinfo_table.py",
        "tests/test_iteminfo_row.py",
        # New Item Studio, phase 2: store rows, model families, and new icons.
        "tests/test_storeinfo_table.py",
        "tests/test_item_model_family.py",
        "tests/test_item_icon_addition.py",
        # New Item Studio domain: the spec, its validation and identity allocation.
        "tests/test_new_item_spec.py",
        # New Item Studio, phase 3: item groups, and the service that plans, exports and installs.
        "tests/test_itemgroupinfo_table.py",
        "tests/test_new_item_service.py",
        # New Item Studio, phase 5: the plan reproduces the in-game-verified spike byte for byte.
        "tests/test_new_item_golden.py",
        # New Item Studio, phase 6: enhancement transition rows.
        "tests/test_multichangeinfo_table.py",
        # New Item Studio, phase 6b: the texture registry (meta/0.pathc) a new icon must be registered in.
        "tests/test_pathc_format.py",
        # New Item Studio visual effects: grafting a component into compatible item prefabs.
        "tests/test_prefab_component_graft.py",
        # New Item Studio, phase 8: the UI's icon registry a new icon must be declared in.
        "tests/test_item_icon_registry.py",
        # New Item Studio, phase 9: imported materials rewritten to the game's plain-PBR shaders.
        "tests/test_pac_xml_standard_material.py",
        "tests/test_new_item_materials.py",
        "tests/test_effect_binary.py",
        "tests/test_effect_catalogue.py",
        "tests/test_new_item_effect_targets.py",
        "tests/test_new_item_effect_proof.py",
        "tests/test_effect_placement_preview.py",
        "tests/test_effect_edit.py",
        # Placement & Animations: the Move a weapon dialog must construct without
        # firing programmatic scope changes into controls that do not exist yet.
        "tests/test_placement_studio_move_dialog.py",
        "tests/test_placement_studio_move_apply.py"
    )
    texture = @(
        "tests/test_texture_backend_retirement.py",
        "tests/test_texture_replacer_headless_harness.py",
        "tests/test_texture_native_backend.py",
        "tests/test_texture_workflow_guardrails.py",
        "tests/test_texture_workflow_ui_source_guards.py",
        "tests/test_recolor_variants_layout.py",
        "tests/test_texture_domain_profiles.py",
        "tests/test_texture_workflow_unavailable_editor.py",
        "tests/test_material_combiner_decode_retry.py",
        "tests/test_material_combiner_vectorized.py",
        "tests/test_static_texture_replacement.py"
    )
    "mesh-contract" = @(
        "tests/test_mesh_rust_archive_texture_launch.py",
        "tests/test_mesh_rust_embedding.py",
        "tests/test_rust_mesh_editor_control_contract.py",
        "tests/test_dotnet_preview_shared_host.py",
        "tests/test_rust_preview_production_cutover.py"
    )
    "mesh-native" = @(
        "tests/test_native_mesh_interaction_abi.py",
        "tests/test_mesh_native_operation_coverage.py",
        "tests/test_mesh_native_session_recovery.py",
        "tests/test_native_mesh_editor_session.py",
        "tests/test_mesh_service_editing.py"
    )
    "mesh-unit" = @(
        "tests/test_mesh_rust_authoring.py",
        "tests/test_mesh_rust_authoring_exact_output.py",
        "tests/test_mesh_rust_archive_texture_launch.py",
        "tests/test_mesh_rust_embedding.py",
        "tests/test_mesh_rust_editor_selection.py",
        "tests/test_mesh_rust_morph_safety.py",
        "tests/test_rust_mesh_editor_control_contract.py",
        "tests/test_dotnet_preview_shared_host.py",
        "tests/test_rust_preview_production_cutover.py",
        "tests/test_mesh_service_editing.py",
        "tests/test_mesh_native_operation_coverage.py",
        "tests/test_mesh_native_session_recovery.py",
        "tests/test_native_mesh_editor_session.py",
        "tests/test_mesh_operation_spec.py",
        "tests/test_mesh_topology_provenance.py",
        "tests/test_native_mesh_topology_provenance.py",
        "tests/test_mesh_topology_rebuild_integration.py",
        "tests/test_mesh_selection_tools.py",
        "tests/test_mesh_geometry_layers.py",
        "tests/test_mesh_morph_service.py",
        "tests/test_static_skin_weight_export.py",
        "tests/test_mesh_output_policy.py",
        "tests/test_mesh_editor_controller.py",
        "tests/test_mesh_editor_actions.py",
        "tests/test_mesh_editor_action_bar.py",
        "tests/test_mesh_editor_direct_mode.py",
        "tests/test_mesh_editor_edit_session_boundary.py",
        "tests/test_mesh_editor_ui_state.py",
        "tests/test_mesh_editor_ui_state_bridge.py",
        "tests/test_pbd_cloth_preview.py",
        "tests/test_archive_preview_texture_binding.py",
        "tests/test_archive_preview_request_coalescing.py",
        "tests/test_model_library_preview.py",
        "tests/test_new_item_item_preview.py",
        "tests/test_effect_placement_preview.py",
        "tests/test_effect_placement_dialog.py",
        "tests/test_material_sidecar_editor.py",
        "tests/test_static_replacement_mesh_edit_state.py",
        "tests/test_static_replacement_selection_commits.py",
        "tests/test_attachment_async_io.py"
    )
}

Set-Location -LiteralPath $RepoRoot

$RealMeshScenario = "real-archive-rust-preview-smoke"
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
    $OutputDir = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-real-archive-rust-preview-$ProofRunId"
    Write-Host "Running no-window real PAC Rust Archive Preview proof from $PamtPath"
    & $Python tools\mesh_editor_dev_harness.py --scenario $RealMeshScenario --game-root $ResolvedGameRoot --output $OutputDir
    exit $LASTEXITCODE
}

if ($Area -eq "rust-mesh-lab-unit") {
    & (Join-Path $PSScriptRoot "test_rust_mesh_lab.ps1")
    exit $LASTEXITCODE
}

if ($Area -eq "rust-mesh-lab-gpu") {
    $RustRoot = Join-Path $RepoRoot "tools\rust_mesh_lab"
    Push-Location $RustRoot
    try {
        & cargo test -p cdmw_mesh_lab --all-features headless_tests::offscreen_d3d12_renders_every_mode_without_a_window -- --ignored --exact
        $RustGpuExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    exit $RustGpuExitCode
}

if ($Area -eq "rust-mesh-lab-stress") {
    $RustRoot = Join-Path $RepoRoot "tools\rust_mesh_lab"
    Push-Location $RustRoot
    try {
        & cargo test -p cdmw_mesh_lab --all-features headless_stress_tests:: -- --ignored --test-threads=1 --nocapture
        $RustStressExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    exit $RustStressExitCode
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
$NeedsMeshCore = $Area -in @("mesh-native", "mesh-unit")
if ($NeedsMeshCore) {
    $MeshCoreSource = Join-Path $RepoRoot "native\cdmw_mesh_core"
    $MeshCoreBuild = Join-Path $MeshCoreSource "build"
    Write-Host "Building the resident native Mesh Editor ABI used by the production helper"
    & cmake -S $MeshCoreSource -B $MeshCoreBuild -G "Visual Studio 17 2022" -A x64
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & cmake --build $MeshCoreBuild --config Release --target cdmw-mesh-core-abi
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
# The wall-clock responsiveness tests are excluded by default, because a shared
# runner can deschedule the process for seconds and fail them for the machine
# being busy rather than for the code blocking the UI. This area is where they
# are meant to run, on a machine whose scheduler the caller controls, so it opts
# them back in.
$AreaMarkerArgs = @()
if ($Area -eq "responsiveness") {
    $AreaMarkerArgs = @("-m", "not visual and not real_game")
}
if ($Area -eq "mesh-unit") {
    # PySide6 on Python 3.14 can terminate a very long-lived pytest interpreter
    # in pyside6.abi3.dll after hundreds of independently destroyed Qt forms.
    # Isolate modules so one module cannot leave a stale Qt wrapper for the next;
    # the real helper open/close soak below remains the product lifetime gate.
    foreach ($TestPath in $ConfiguredTests) {
        Write-Host "Running mesh-unit module $TestPath"
        & $Python -m pytest @PytestTempArgs @AreaMarkerArgs $TestPath
        $PytestExitCode = $LASTEXITCODE
        if ($PytestExitCode -ne 0) {
            exit $PytestExitCode
        }
    }
} else {
    & $Python -m pytest @PytestTempArgs @AreaMarkerArgs @ConfiguredTests
    $PytestExitCode = $LASTEXITCODE
    if ($PytestExitCode -ne 0) {
        exit $PytestExitCode
    }
}

if ($Area -in @("mesh-contract", "mesh-unit")) {
    & (Join-Path $PSScriptRoot "test_rust_mesh_lab.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

exit 0
