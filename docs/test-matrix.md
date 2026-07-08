# Test Matrix

Last reviewed: 2026-07-06

Use the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m pytest <tests> --basetemp="%TEMP%\cdmw-pytest-<name>"
```

Use `%TEMP%` for pytest temp dirs when `.pytest-tmp` is locked.

## Smoke

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py
.\scripts\codex_check.ps1 -Area smoke
```

## Startup, Crash Reporting, And Packaging Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py tests/test_crash_reporting_guards.py tests/test_pyinstaller_temp_cleanup.py tests/test_shell_main_window_proxy.py
.\.venv\Scripts\python.exe -m pytest tests/test_settings_tab_asset_authoring.py
.\scripts\codex_check.ps1 -Area stability
```

## UI Responsiveness And Source Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_responsiveness_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_texture_workflow_ui_source_guards.py
.\scripts\codex_check.ps1 -Area responsiveness
```

## Archive Browser And Archive Services

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_archive_browser_virtual_model.py tests/test_archive_preview_state.py tests/test_archive_preview_settings_state.py tests/test_material_sidecar_editor.py tests/test_mesh_import_setup_state.py tests/test_archive_browser_filters.py tests/test_archive_caches.py tests/test_progressive_archive_preview.py tests/test_archive_extract_progress.py
.\.venv\Scripts\python.exe -m pytest tests/test_static_replacement_camera.py tests/test_static_replacement_geometry_math.py tests/test_static_replacement_preview_models.py tests/test_static_replacement_d3d11_mapping.py tests/test_static_replacement_d3d11_state.py tests/test_static_replacement_accept_state.py tests/test_static_replacement_startup_state.py tests/test_static_replacement_original_texture_preview_state.py tests/test_static_replacement_build_footer.py tests/test_static_replacement_qt_helpers.py
.\scripts\codex_check.ps1 -Area archive
```

## Mesh Editor Suite

For user-facing Mesh Editor edit/viewport proof, run the real archive side-by-side
D3D11 smoke. `codex_check -Area mesh` is the real-game wrapper for that proof.
Do not substitute `codex_check -Area mesh-unit`, `build_synthetic_mesh`,
`harness_quad`, or the synthetic D3D11 protocol harnesses; those catch
regressions but do not prove game geometry renders or edits correctly.

```powershell
dotnet build tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj -c Release
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_asset_pipeline.py tests/test_mesh_pipeline_cli.py tests/test_mesh_dotnet_experiment.py tests/test_mesh_edit_operations.py tests/test_mesh_service_editing.py tests/test_mesh_editor_controller.py tests/test_mesh_editor_dev_harness.py tests/test_mesh_editor_actions.py tests/test_mesh_editor_action_bar.py tests/test_mesh_deformer.py tests/test_mesh_selection_tools.py tests/test_archive_structured_asset_preview.py tests/test_rigging_binary_parsers.py
.\scripts\codex_check.ps1 -Area mesh
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-benchmark --output "$env:TEMP\cdmw-native-mesh-editor-benchmark"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-static-screen-stroke --output "$env:TEMP\cdmw-native-mesh-editor-static-screen-stroke"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-qt-responsiveness --output "$env:TEMP\cdmw-native-mesh-editor-qt"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-qt-cancellation --output "$env:TEMP\cdmw-native-mesh-editor-qt-cancel"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-mesh-editor-d3d11-edit-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-real-archive-mesh-editor-d3d11-edit"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-rigging-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-rigging"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-animation-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-animation"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-sequence-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-sequence"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-app-workflow-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-app-workflow"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario mesh-dotnet-native-parity-report --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-dotnet-native-parity"
.\scripts\codex_check.ps1 -Area mesh-unit
```

Protocol-only local smoke, when a real game archive is not available:

```powershell
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario service-smoke --output "$env:TEMP\cdmw-mesh-editor-service-smoke"
```

Chunked PAC parser corpus compatibility, for proving real archive parser coverage
without long connector/process runs:

```powershell
.\.venv\Scripts\python.exe tools\pac_parser_corpus_harness.py --pamt "C:\games\Steam\steamapps\common\Crimson Desert\0009\0.pamt" --out "$env:TEMP\cdmw-pac-parser-corpus-0009" --chunk-size 1000 --chunk-index 0 --chunk-count 1 --fail-on-issue
```

Repeat with the next `--chunk-index` until `summary.json` reports
`all_entries_scanned=true` and `parser_compatibility_ready_for_scanned_entries=true`.
Use `--force` to regenerate a chunk after parser changes.

Focused editable-package UI worker smoke:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_workspace_editable_package_buttons_emit_requests tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_opens_last_editable_package_folder tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_runs_validation_report_in_background tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_copies_validation_report_json tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editable_package_workers_export_and_import_with_validation tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_replace_working_mesh_blocks_obj_sidecar_source_hash_mismatch
```

Focused patched-asset rebuild UI/service smoke:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_rebuild_asset_writes_validated_output_file tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_rebuild_asset_refuses_original_source_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_workspace_rebuild_panel_reflects_report tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_rebuild_asset_requires_passing_validation_and_output_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_preview_rebuilt_asset_routes_archive_target_and_output_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_shell_mesh_editor_preview_rebuilt_asset_routes_import_preview_preset tests/test_archive_mesh_export_naming.py::ArchiveMeshExportNamingTests::test_rebuilt_asset_preset_flows_open_mesh_editor_and_schedule_preview_and_patch tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_rebuild_report_worker_writes_asset_when_output_path_is_set
```

`codex_check -Area mesh-unit` skips interactive D3D11/Qt harness cases and is
synthetic/protocol coverage only. Use `codex_check -Area mesh` or the real
archive Mesh Editor D3D11 edit smokes above for visual proof on game geometry.
Run the Qt harness commands above only when intentionally validating worker
responsiveness/cancellation. D3D11 harness windows are moved to screen 1 before
captures and mouse input.
The side-by-side real archive D3D11 smoke is also the current live-stroke frame
budget proof: `live_stroke_frame_budget_ok` must be true and the harness should
report sub-16.7 ms `handler_ms` for live vertex-update dispatch.

Do not use `native-mesh-editor-d3d11-delta`,
`native-mesh-editor-d3d11-payloads`, or `full-suite-smoke` as visual edit proof.
They are synthetic/protocol regression harnesses and intentionally do not show game geometry.
The harness blocks them by default; pass `--allow-synthetic-d3d11` only for
protocol-only regression testing.

## Texture Workflow

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_texture_workflow_ui_source_guards.py tests/test_texture_workflow_asset_authoring_panel.py tests/test_texture_domain_profiles.py tests/test_texture_workflow_unavailable_editor.py tests/test_texture_editor_workers.py tests/test_texture_editor_ui_helpers.py tests/test_texture_editor_native_service.py tests/test_texture_editor_dev_harness.py tests/test_static_texture_replacement.py
.\scripts\codex_check.ps1 -Area texture
```

## Supporting Feature Tabs

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_research_archive_picker_state.py tests/test_research_analysis_state.py tests/test_research_classification_review_state.py tests/test_research_display_preferences_state.py tests/test_research_layout_state.py tests/test_research_notes_state.py tests/test_research_reference_payload_state.py tests/test_research_refresh_population_state.py tests/test_research_texture_group_state.py tests/test_research_tree_column_specs.py tests/test_research_models.py tests/test_research_workers.py tests/test_research_state.py tests/test_model_library_inline_preview_ui.py tests/test_model_library_ui_source_guards.py tests/test_item_icons_state.py
```

## Runtime Regression Smokes

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_restructure_runtime_regression_smoke.py
```

## Architecture Boundary Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_architecture_import_boundaries.py tests/test_architecture_no_wildcard_imports.py tests/test_architecture_public_facades.py
```

## Services, Domain, And Workers

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_services.py tests/test_asset_authoring_service.py tests/test_asset_authoring_workers.py tests/test_diagnostics_service.py tests/test_workers.py tests/test_shell_context.py
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-discovery --output "%TEMP%\cdmw-asset-authoring-discovery"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-mesh-health --output "%TEMP%\cdmw-asset-authoring-mesh-health"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-uv-report --output "%TEMP%\cdmw-asset-authoring-uv-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-tangent-report --output "%TEMP%\cdmw-asset-authoring-tangent-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-openimageio-report --output "%TEMP%\cdmw-asset-authoring-openimageio-report"
```

`asset-authoring-mesh-health` writes both mesh-health and meshoptimizer
optimization preflight reports.

## Full Suite

```powershell
.\.venv\Scripts\python.exe -m pytest
.\scripts\codex_check.ps1 -Area full
```

## Release Packaging

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onefile -BuildProfile release
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; $env:CDMW_GUI_STARTUP_SMOKE_TARGET='mesh_editor'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; $env:CDMW_GUI_STARTUP_SMOKE_TARGET='mesh_editor'; $env:CDMW_GUI_STARTUP_SMOKE_MESH_ASSET='D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; $env:CDMW_GUI_STARTUP_SMOKE_TARGET='mesh_editor'; $env:CDMW_GUI_STARTUP_SMOKE_MESH_ASSET='D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac'; $env:CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD='1'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; $env:CDMW_GUI_STARTUP_SMOKE_TARGET='mesh_editor'; $env:CDMW_GUI_STARTUP_SMOKE_MESH_ASSET='D:\Byggverkstaden\test_mesh_editor\cd_phm_00_nude_10_0001.pac'; $env:CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET='1'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
```

## Notes

- Prefer targeted tests before broader suites.
- Source guard tests are expected in this codebase for large PySide wiring surfaces.
- Update this matrix when tests move, split, or stop being authoritative for a change type.
