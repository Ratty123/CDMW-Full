# Test Matrix

Last reviewed: 2026-06-29

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

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_service_editing.py tests/test_mesh_editor_controller.py tests/test_mesh_editor_dev_harness.py tests/test_mesh_editor_actions.py tests/test_mesh_editor_action_bar.py tests/test_mesh_deformer.py tests/test_mesh_selection_tools.py tests/test_archive_structured_asset_preview.py tests/test_rigging_binary_parsers.py
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario full-suite-smoke --output "$env:TEMP\cdmw-mesh-editor-harness"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-rigging-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-rigging"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-animation-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-animation"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-sequence-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-sequence"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-app-workflow-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-app-workflow"
.\scripts\codex_check.ps1 -Area mesh
```

## Texture Workflow

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_texture_workflow_ui_source_guards.py tests/test_texture_domain_profiles.py tests/test_texture_workflow_unavailable_editor.py tests/test_texture_editor_workers.py tests/test_texture_editor_ui_helpers.py tests/test_texture_editor_native_service.py tests/test_texture_editor_dev_harness.py tests/test_static_texture_replacement.py
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
.\.venv\Scripts\python.exe -m pytest tests/test_services.py tests/test_diagnostics_service.py tests/test_workers.py tests/test_shell_context.py
```

## Full Suite

```powershell
.\.venv\Scripts\python.exe -m pytest
.\scripts\codex_check.ps1 -Area full
```

## Release Packaging

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onefile -BuildProfile release
$env:QT_QPA_PLATFORM='offscreen'; $env:CDMW_GUI_STARTUP_SMOKE='1'; .\dist\CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe
```

## Notes

- Prefer targeted tests before broader suites.
- Source guard tests are expected in this codebase for large PySide wiring surfaces.
- Update this matrix when tests move, split, or stop being authoritative for a change type.
