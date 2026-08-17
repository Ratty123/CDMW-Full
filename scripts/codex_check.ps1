param(
    [ValidateSet("smoke", "stability", "responsiveness", "archive", "texture", "mesh", "mesh-unit", "full")]
    [string]$Area = "smoke",
    [string]$GameRoot = "",
    [string]$PytestBaseTemp = "",
    # Split the full suite across sequential shards. Each shard is an ordinary
    # pytest run over a subset, so nothing about how a test executes changes;
    # only the wall clock moves. Defaults run the whole suite as before.
    [int]$Shard = 1,
    [int]$ShardCount = 1
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

$TestsByArea = @{
    smoke = @(
        "tests/test_runtime_dependency_smoke.py",
        # Generated-manifest freshness. Both of these are verified by
        # build_pyside6_app.ps1 before it compiles anything, so a stale one is a
        # failed release build. The localization manifest stores a line number
        # per UI string, which means ANY edit that shifts a line in a file
        # containing one goes stale -- no new string required. That is not
        # guessable from an area name, so it belongs in the cheapest gate.
        "tests/test_window_feature_controller.py",
        "tests/test_localization_catalog_contracts.py"
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
        "tests/test_packaged_bundled_helper_reporting.py"
    )
    responsiveness = @(
        "tests/test_attachment_async_io.py",
        "tests/test_ui_responsiveness_source_guards.py",
        "tests/test_mesh_edit_responsiveness_source_guards.py",
        "tests/test_texture_workflow_ui_source_guards.py",
        "tests/test_localization_async_io.py",
        "tests/test_localization_translations.py",
        "tests/test_localization_catalog_contracts.py",
        "tests/test_localization_translation_quality.py",
        "tests/test_persistent_tree_headers.py"
    )
    archive = @(
        "tests/test_archive_browser_virtual_model.py",
        "tests/test_archive_browser_filters.py",
        "tests/test_archive_caches.py",
        "tests/test_progressive_archive_preview.py",
        "tests/test_archive_preview_request_coalescing.py",
        "tests/test_archive_d3d11_process_lifecycle.py",
        "tests/test_archive_extract_progress.py",
        "tests/test_archive_progress_bar_writes_on_change.py",
        # Unregistered until 2026-08-08, which is how its progress-bar and
        # selection-context needles sat stale across four commits.
        "tests/test_archive_browser_asset_understanding_ui_source_guards.py",
        # Archive writers: in-place patching, brand-new PAMT entries, and the
        # table/part-prefab owners the New Item flow appends through.
        "tests/test_archive_patch_preflight.py",
        "tests/test_archive_mutation_service.py",
        "tests/test_archive_entry_addition.py",
        "tests/test_pappt_format.py",
        "tests/test_stringinfo_table.py",
        "tests/test_iteminfo_row.py",
        # New Item Studio domain: the spec, its validation and identity allocation.
        "tests/test_new_item_spec.py"
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
        "tests/test_material_category_contract.py",
        "tests/test_mesh_dotnet_material_state.py",
        "tests/test_mesh_dotnet_material_visual_parity.py",
        "tests/test_mesh_dotnet_material_package.py",
        "tests/test_material_combiner_decode_retry.py",
        "tests/test_mesh_dotnet_material_dds_synthesis.py",
        "tests/test_mesh_dotnet_material_parameters.py",
        "tests/test_mesh_dotnet_resident_material_ui.py",
        "tests/test_mesh_visual_audit_harness.py",
        "tests/test_mesh_visual_audit_integrity.py",
        "tests/test_mesh_visual_audit_package.py",
        "tests/test_dotnet_protocol_trail_writes.py",
        "tests/test_mesh_editor_no_undefined_globals.py",
        "tests/test_edit_mesh_tool_rail_reaches_python.py",
        "tests/test_mesh_native_operation_coverage.py",
        "tests/test_mesh_native_session_recovery.py",
        "tests/test_mesh_topology_provenance.py",
        "tests/test_native_mesh_topology_provenance.py",
        "tests/test_mesh_pac_topology_serializer.py",
        "tests/test_mesh_topology_rebuild_integration.py",
        "tests/test_mesh_topology_checks_panel.py",
        "tests/test_stroke_orphan_refusal.py",
        "tests/test_mesh_edit_combo_mirror.py",
        "tests/test_mesh_edit_selection_mirror.py",
        "tests/test_mesh_edit_paint_select_sample.py",
        "tests/test_mesh_edit_stroke_single_authority.py",
        "tests/test_mesh_delta_temp_cleanup_budget.py",
        "tests/test_prewarm_placeholder_not_revealed.py",
        "tests/test_mesh_edit_display_mode_slot.py",
        "tests/test_transform_button_captions_not_squeezed.py",
        "tests/test_dotnet_helper_manifest_contract.py",
        "tests/test_dotnet_ui_localization_protocol_source.py",
        "tests/test_dotnet_preview_shared_host.py",
        "tests/test_dotnet_mesh_editor_layout_contract.py",
        "tests/test_dotnet_mesh_editor_tool_protocol_source.py",
        "tests/test_mesh_morph_slider_ui_source_guards.py",
        "tests/test_mesh_morph_refit_protocol.py",
        "tests/test_mesh_morph_service.py",
        "tests/test_dotnet_preview_performance_contract.py",
        "tests/test_dotnet_texture_region_protocol.py",
        "tests/test_dotnet_material_parameter_protocol.py",
        "tests/test_native_preview_material_authority_protocol.py",
        "tests/test_native_preview_core.py",
        "tests/test_dotnet_icon_capture_protocol.py",
        "tests/test_mesh_edit_native_coverage.py",
        "tests/test_native_mesh_editor_session.py",
        "tests/test_mesh_service_editing.py",
        "tests/test_mesh_editor_controller.py",
        "tests/test_mesh_editor_actions.py",
        "tests/test_mesh_editor_action_bar.py",
        "tests/test_mesh_editor_builder_interaction_defaults.py",
        "tests/test_mesh_builder_runtime_wiring.py",
        "tests/test_mesh_builder_construction_lifecycle.py",
        "tests/test_mesh_builder_construction_invariants.py",
        "tests/test_mesh_builder_preview_control_honesty.py",
        "tests/test_static_replacement_post_open_state.py",
        "tests/test_static_replacement_prompt_preflight_async.py",
        "tests/test_static_replacement_mesh_edit_dotnet_toggle.py",
        "tests/test_mesh_resident_editor_regressions.py",
        "tests/test_static_replacement_dotnet_presentation.py",
        "tests/test_mesh_editor_presentation_republish.py",
        "tests/test_mesh_editor_preview_mode_survives_publish.py",
        "tests/test_mesh_editor_textured_view_request_settles.py",
        # Material publication ordering, the boundary an imported model's own
        # materials are published from, and the Edit Mesh session states. The
        # first two are the Solid (Textured) reproducers; the third is what
        # refuses a finish over a working state whose renderer died.
        "tests/test_mesh_material_publication_coordinator.py",
        "tests/test_mesh_editor_imported_material_publication.py",
        "tests/test_mesh_editor_runtime_diagnostics.py",
        "tests/test_mesh_edit_session_state.py",
        # Element kind and drag gesture, which shared one field and one name
        # until an edge tool started resetting the reader's Lasso to Brush.
        "tests/test_mesh_edit_selection_vocabulary.py",
        # Why each action is off the rail, and that the two reasons stay apart:
        # eleven blocked by the writer, three superseded by the Select tool.
        "tests/test_mesh_editor_hidden_action_contract.py",
        # What an import resolved per material slot, and the build log that now
        # reads that manifest rather than retelling the same rows.
        "tests/test_imported_material_manifest.py",
        # The import's account of a slot against the package's, which agreed
        # only by reading the same pipeline until this compared them.
        "tests/test_material_manifest_agreement.py",
        # Every link of the import setup chain accepts every workflow preset.
        # Two shipped crashes were a keyword one link took and the next refused.
        "tests/test_mesh_import_setup_flag_chain.py",
        # The gizmo drag reaching the host with the transform it was sent. The
        # payload nests it, the host read the top level, and every drag reported
        # no movement at all.
        "tests/test_placement_gizmo_transform_signals.py",
        # An imported material's emissive surviving the Material Authority
        # update that used to clear it: the preview mesh dropped the factor
        # parameters, so the bridge decided the part had no glow.
        "tests/test_imported_emissive_survives_material_authority.py",
        # Part Setup's combo selecting and highlighting a part the lazily
        # populated source tree has not reached yet.
        "tests/test_part_setup_combo_selects_and_highlights.py",
        # Where the Builder's Setup controls live after the owner's restructure:
        # options under Options, Material Authority flat inside Advanced, and
        # Parts & Routing folded into Part Setup with its tab hidden.
        "tests/test_builder_setup_tab_layout.py",
        # Replace Materials and Textures Only, whose whole guarantee is that the
        # commit boundary emits no mesh entry at all.
        "tests/test_materials_and_textures_replacement.py",
        "tests/test_mesh_editor_edit_session_boundary.py",
        "tests/test_mesh_editor_error_codes.py",
        "tests/test_mesh_operation_spec.py",
        # The operation the Builder's controls classify to, the flags derived
        # from it, and the build that refuses options which stopped describing
        # it. The first proves the derivation still produces what the six
        # expressions it replaced produced; the second is the fail-closed path.
        "tests/test_mesh_builder_operation.py",
        "tests/test_static_mesh_build_operation_guard.py",
        "tests/test_full_replacement_texture_payload.py",
        "tests/test_mesh_authoring_capability.py",
        "tests/test_fbx_support_contract.py",
        "tests/test_mesh_editor_mixin_composition.py",
        "tests/test_mesh_editor_camera_is_not_reset.py",
        "tests/test_dotnet_solid_textured_view_survives_publish.py",
        "tests/test_dotnet_edit_mesh_entry_layout.py",
        "tests/test_select_drag_shape_survives_tool_state.py",
        "tests/test_mesh_editor_scene_mode_reads.py",
        "tests/test_mesh_editor_host_window_reparent.py",
        "tests/test_mesh_preview_stale_package_reveal.py",
        "tests/test_qt_rhi_plugin_contract.py",
        "tests/test_dotnet_preview_package_cache_reuse.py",
        "tests/test_static_replacement_selection_commits.py",
        "tests/test_mesh_harness_performance_contract.py",
        "tests/test_mesh_harness_scenario_registry.py",
        "tests/test_mesh_harness_real_dotnet_evidence.py",
        "tests/test_mesh_dotnet_live_stroke_dispatch.py",
        "tests/test_mesh_dotnet_stroke_protocol_flow.py",
        "tests/test_mesh_live_stroke_dispatcher.py",
        "tests/test_dotnet_update_queue.py",
        "tests/test_mesh_selection_targets.py",
        "tests/test_mesh_dense_subdivide.py",
        "tests/test_mesh_geometry_layers.py",
        "tests/test_modify_original_mesh_layer_drafts.py",
        "tests/test_modify_original_draft_chain_async.py",
        "tests/test_mesh_editor_camera_only_on_open.py",
        "tests/test_preview_overlay_color_settings.py",
        "tests/test_xray_overlay_color_follows_preference.py",
        "tests/test_dotnet_preview_settings_contract.py",
        # Also unregistered until 2026-08-08; its embedded-dialog, part-pick and
        # flip-V needles had drifted from the source they guard.
        "tests/test_alignment_dialog_source_guards.py",
        "tests/test_static_replacement_dialog_helpers.py",
        "tests/test_static_replacement_d3d11_deleted_process.py",
        "tests/test_mesh_editor_nonblocking_close.py",
        "tests/test_dotnet_overlay_color_controls.py",
        "tests/test_mesh_deformer.py",
        "tests/test_mesh_body_regions.py",
        "tests/test_mesh_body_region_falloff.py",
        "tests/test_mesh_body_region_sliders.py",
        "tests/test_mesh_body_region_slider_native.py",
        "tests/test_mesh_region_decompose.py",
        "tests/test_mesh_body_region_atlas.py",
        "tests/test_native_morph_field_generation.py",
        "tests/test_pac_skin_layout_regression.py",
        "tests/test_static_skin_weight_export.py",
        "tests/test_mesh_selection_tools.py",
        "tests/test_archive_structured_asset_preview.py",
        "tests/test_rigging_binary_parsers.py",
        "tests/test_mesh_parser_path_argument_guard.py"
    )
}

Set-Location -LiteralPath $RepoRoot

$RealMeshScenario = "real-archive-mesh-editor-dotnet-edit-smoke"
$PytestTempArgs = @()
if ($PytestBaseTemp) {
    $PytestTempArgs = @("-p", "no:cacheprovider", "--basetemp=$PytestBaseTemp")
}

if ($Area -eq "full") {
    if ($ShardCount -gt 1) {
        $ShardFiles = @(& $Python (Join-Path $PSScriptRoot "shard_tests.py") --shard $Shard --of $ShardCount)
        if ($LASTEXITCODE -ne 0 -or $ShardFiles.Count -eq 0) {
            throw "Could not resolve shard $Shard of $ShardCount."
        }
        Write-Host "Running full pytest shard $Shard of $ShardCount ($($ShardFiles.Count) files) with $Python"
        & $Python -m pytest @PytestTempArgs @ShardFiles
        exit $LASTEXITCODE
    }
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
# The wall-clock responsiveness tests are excluded by default, because a shared
# runner can deschedule the process for seconds and fail them for the machine
# being busy rather than for the code blocking the UI. This area is where they
# are meant to run, on a machine whose scheduler the caller controls, so it opts
# them back in.
$AreaMarkerArgs = @()
if ($Area -eq "responsiveness") {
    $AreaMarkerArgs = @("-m", "not visual and not real_game")
}
& $Python -m pytest @PytestTempArgs @AreaMarkerArgs @ConfiguredTests
$PytestExitCode = $LASTEXITCODE
if ($PytestExitCode -ne 0) {
    exit $PytestExitCode
}

if ($Area -eq "mesh-unit") {
    $DotNetProject = Join-Path $RepoRoot "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
    Write-Host "Building the resident .NET Mesh Editor for the Edit Mesh Tool Rail construction gate"
    & dotnet build $DotNetProject -c Release --nologo --verbosity:minimal
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $LayoutRunId = [Guid]::NewGuid().ToString("N")
    $LayoutReport = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-edit-mesh-layout-$LayoutRunId.json"
    $DotNetHelper = Join-Path $RepoRoot "tools\dotnet_mesh_editor_experiment\bin\Release\net10.0-windows\cdmw-mesh-dotnet-editor.exe"
    $LayoutProcess = Start-Process `
        -FilePath $DotNetHelper `
        -ArgumentList @("--headless-edit-mesh-layout-smoke", "--layout-report", $LayoutReport) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($LayoutProcess.ExitCode -ne 0) {
        Write-Error "Edit Mesh Tool Rail construction smoke failed with exit code $($LayoutProcess.ExitCode)."
        exit $LayoutProcess.ExitCode
    }
    if (-not (Test-Path -LiteralPath $LayoutReport)) {
        Write-Error "Edit Mesh Tool Rail construction smoke did not create '$LayoutReport'."
        exit 1
    }
    $LayoutPayload = Get-Content -LiteralPath $LayoutReport -Raw | ConvertFrom-Json
    # The Tool Rail is the only Edit Mesh layout: the Classic layout is gone,
    # so the round trip the smoke reports is mesh-edit entry and the return to
    # the placement flanks. The rail itself is one flat list -- six tool
    # buttons that each arm exactly the tool they name, and three reveal-only
    # command-page entries. The camera never became a rail entry -- it is
    # reached by the modifiers on the navigation strip -- so orbit owns no
    # page and the rail opens on none of them.
    if (-not $LayoutPayload.ok `
        -or -not $LayoutPayload.tool_rail_default `
        -or -not $LayoutPayload.tool_rail_only_layout `
        -or $LayoutPayload.round_trip_layout -ne "placement" `
        -or -not $LayoutPayload.same_control_instances `
        -or -not $LayoutPayload.same_viewport_instance `
        -or -not $LayoutPayload.same_viewport_handle `
        -or -not $LayoutPayload.stable_viewport_parent `
        -or -not $LayoutPayload.material_sync_completion_is_correlated `
        -or -not $LayoutPayload.activation_package_generation_is_fenced `
        -or -not $LayoutPayload.zero_size_splitter_construction `
        -or $LayoutPayload.pages_visited.Count -ne 6 `
        -or $LayoutPayload.rail_tool_count -ne 6 `
        -or $LayoutPayload.rail_command_page_count -ne 3 `
        -or $LayoutPayload.opening_page -ne "none" `
        -or $LayoutPayload.opening_tool -ne "orbit" `
        -or $LayoutPayload.renderer_started `
        -or $LayoutPayload.visible_window_started) {
        Write-Error "Edit Mesh Tool Rail construction smoke returned an invalid report at '$LayoutReport'."
        exit 1
    }
    Remove-Item -LiteralPath $LayoutReport
    Write-Host "Edit Mesh Tool Rail construction smoke passed."

    $LocalizationRunId = [Guid]::NewGuid().ToString("N")
    $LocalizationReport = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-ui-localization-$LocalizationRunId.json"
    $LocalizationProcess = Start-Process `
        -FilePath $DotNetHelper `
        -ArgumentList @("--headless-ui-localization-contract", "--localization-report", $LocalizationReport) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($LocalizationProcess.ExitCode -ne 0) {
        Write-Error ".NET interface-localization contract smoke failed with exit code $($LocalizationProcess.ExitCode)."
        exit $LocalizationProcess.ExitCode
    }
    if (-not (Test-Path -LiteralPath $LocalizationReport)) {
        Write-Error ".NET interface-localization contract smoke did not create '$LocalizationReport'."
        exit 1
    }
    $LocalizationPayload = Get-Content -LiteralPath $LocalizationReport -Raw | ConvertFrom-Json
    if (-not $LocalizationPayload.ok `
        -or $LocalizationPayload.boundary_count -lt 28 `
        -or $LocalizationPayload.localization_key_count -lt 1 `
        -or $LocalizationPayload.localization_key_manifest_hash.Length -ne 64 `
        -or -not $LocalizationPayload.presentation_format_ok `
        -or -not $LocalizationPayload.invariant_metrics_source_ok `
        -or -not $LocalizationPayload.cjk_font_fallbacks_ok `
        -or $LocalizationPayload.renderer_started `
        -or $LocalizationPayload.visible_window_started) {
        Write-Error ".NET interface-localization contract smoke returned an invalid report at '$LocalizationReport'."
        exit 1
    }
    Remove-Item -LiteralPath $LocalizationReport
    Write-Host ".NET interface-localization contract smoke passed."
}

exit 0
