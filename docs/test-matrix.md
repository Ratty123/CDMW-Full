# Test Matrix

Last reviewed: 2026-07-12

Use the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m pytest <tests> -p no:cacheprovider --basetemp="$env:TEMP\cdmw-pytest-<name>"
```

Use `$env:TEMP` for pytest temp dirs when `.pytest-tmp` is locked.
`scripts/codex_check.ps1` fails closed if an area's configured test path is missing.

## Smoke

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py
.\scripts\codex_check.ps1 -Area smoke
```

## Startup, Crash Reporting, And Packaging Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py tests/test_crash_reporting_guards.py tests/test_pyinstaller_temp_cleanup.py tests/test_startup_splash_lifecycle.py tests/test_shell_main_window_proxy.py tests/test_window_feature_controller.py tests/test_archive_scan_ui_delivery.py
.\.venv\Scripts\python.exe -m pytest tests/test_lazy_tool_tabs.py
.\.venv\Scripts\python.exe -m pytest tests/test_settings_tab_asset_authoring.py
.\.venv\Scripts\python.exe scripts/generate_window_feature_provider_members.py --check
.\.venv\Scripts\python.exe tools/benchmark_app_startup.py --runs 11 --first-tab mesh_editor_tab --baseline docs/reference/app-startup-benchmark-phase5.json --output docs/reference/app-startup-benchmark-phase6.json
.\scripts\codex_check.ps1 -Area stability
```

After adding, removing, renaming, or changing a shell feature-provider member,
regenerate the manifest with
`.\.venv\Scripts\python.exe scripts/generate_window_feature_provider_members.py`.
`test_window_feature_controller.py` also proves that lazy callbacks connected to
worker signals execute on the owning QApplication thread.

## UI Responsiveness And Source Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_responsiveness_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_texture_workflow_ui_source_guards.py
.\.venv\Scripts\python.exe -m pytest tests/test_attachment_async_io.py tests/test_appearance_async.py tests/test_localization_async_io.py tests/test_localization_translations.py
.\scripts\codex_check.ps1 -Area responsiveness
```

## Archive Browser And Archive Services

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_archive_mutation_service.py tests/test_archive_patch_preflight.py
.\.venv\Scripts\python.exe -m pytest tests/test_archive_service_boundaries.py tests/test_architecture_import_boundaries.py::test_ui_does_not_import_archive_compatibility_facades
.\.venv\Scripts\python.exe -m pytest tests/test_archive_hkx_decomposition.py tests/test_archive_hkx_helper_decomposition.py tests/test_native_hkx_decomposition.py tests/test_hkx_editor_dialog_decomposition.py tests/test_hkx_preview.py tests/test_hkx_native_backend.py tests/test_hkx_ui_source_guards.py
.\.venv\Scripts\python.exe -m pytest tests/test_archive_binary_preview_decomposition.py tests/test_archive_binary_preview_helper_decomposition.py tests/test_archive_structured_asset_preview.py
.\.venv\Scripts\python.exe -m pytest tests/test_archive_preview_decomposition.py tests/test_archive_preview_texture_binding.py tests/test_mesh_import_preview_static_edit.py
.\.venv\Scripts\python.exe -m pytest tests/test_archive_lightweight_indexes.py
.\.venv\Scripts\python.exe -m pytest tests/test_temp_cache.py tests/test_archive_media_preview_cache.py
.\.venv\Scripts\python.exe -m pytest tests/test_archive_browser_virtual_model.py tests/test_archive_preview_state.py tests/test_archive_preview_settings_state.py tests/test_material_sidecar_editor.py tests/test_mesh_import_setup_state.py tests/test_archive_browser_filters.py tests/test_archive_caches.py tests/test_progressive_archive_preview.py tests/test_archive_extract_progress.py
.\.venv\Scripts\python.exe -m pytest tests/test_static_replacement_dialog_factory_decomposition.py tests/test_static_replacement_camera.py tests/test_static_replacement_geometry_math.py tests/test_static_replacement_preview_models.py tests/test_static_replacement_d3d11_mapping.py tests/test_static_replacement_d3d11_state.py tests/test_static_replacement_accept_state.py tests/test_static_replacement_startup_state.py tests/test_static_replacement_original_texture_preview_state.py tests/test_static_replacement_build_footer.py tests/test_static_replacement_qt_helpers.py
.\scripts\codex_check.ps1 -Area archive
```

The HKX group includes clean-process facade/owner identity checks, representative
document/overlay/model/text golden hashes, deterministic pure/native corpus
report and CSV goldens, the offscreen HKX dialog/widget-tree golden, owner size
limits, and the existing converter
corpus/native-backend behavior suite.

## Mesh Editor Suite

Archive mesh-import setup responsiveness, cancellation, stale-result rejection,
and in-game swap-scope preflight:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_import_setup_async.py
```

Mesh-service owner boundaries, clean import identity, stateful native dispatch,
bounded history, and revision transport:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_editor_tab_decomposition.py tests/test_mesh_editor_workspace_decomposition.py tests/test_static_replacement_mesh_edit_decomposition.py tests/test_mesh_service_decomposition.py tests/test_mesh_native_core_decomposition.py tests/test_native_mesh_core_decomposition.py tests/test_native_mesh_core_service.py tests/test_mesh_history_bounds.py tests/test_mesh_edit_revision_protocol.py
```

Native preview-core/D3D11 ownership, aggregated source guards, Release builds,
and headless self-tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_native_preview_core_decomposition.py tests/test_native_d3d11_preview_decomposition.py tests/test_native_preview_core.py tests/test_native_preview_package_cache_concurrency.py
cmake -S native/cdmw_preview_core -B native/cdmw_preview_core/build
cmake --build native/cdmw_preview_core/build --config Release
native\cdmw_preview_core\build\Release\cdmw-preview-core.exe self-test
cmake -S native/cdmw_d3d11_preview -B native/cdmw_d3d11_preview/build
cmake --build native/cdmw_d3d11_preview/build --config Release
native\cdmw_d3d11_preview\build\Release\cdmw-d3d11-preview.exe --self-test
```

For user-facing Mesh Editor edit proof, run the read-only real game archive
scenario. `codex_check -Area mesh` reads an in-game PAC through `0009/0.pamt`,
opens the actual body mesh in the embedded .NET/Vortice D3D11 viewport, routes
edits through `cdmw_mesh_core`, then proves selection/transform, scalar state,
two linked texture strokes, committed DDS assignment, UV/topology edits,
undo/redo, coherent export, and GLB/OBJ/DDS/sidecar readback. Evidence stays
under the temp directory. It also requires an initially empty Parts selection
and proves face/vertex selection does not select or highlight a part.
`mesh-unit` excludes visual scenarios, so it never opens the synthetic legacy
checker-square window.
Before capture or physical mouse-down, the proof requires the exact .NET form
to own the foreground and the sampled screen point to resolve to a viewport
descendant with the renderer PID; otherwise it aborts without injecting input.
The direct harness CLI resolves the game root from `--game-root`, then
`CDMW_GAME_ROOT`, then the standard Steam installation path.

```powershell
dotnet build tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj -c Release
dotnet .\tools\dotnet_mesh_editor_experiment\bin\Release\net8.0-windows\cdmw-mesh-dotnet-editor.dll --material-resource-policy-report "$env:TEMP\cdmw-material-resource-policy-runtime.json"
dotnet .\tools\dotnet_mesh_editor_experiment\bin\Release\net8.0-windows\cdmw-mesh-dotnet-editor.dll --headless-gpu-sparse-soak --gpu-soak-report "$env:TEMP\cdmw-dotnet-gpu-sparse-soak.json"
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_asset_pipeline.py tests/test_mesh_pipeline_cli.py tests/test_mesh_dotnet_experiment.py tests/test_dotnet_mesh_editor_tool_protocol_source.py tests/test_dotnet_gpu_geometry_resources.py tests/test_dotnet_topology_channel_updates.py tests/test_mesh_edit_revision_protocol.py tests/test_mesh_history_bounds.py tests/test_native_preview_package_cache_concurrency.py tests/test_mesh_edit_operations.py tests/test_mesh_service_editing.py tests/test_mesh_editor_controller.py tests/test_mesh_editor_actions.py tests/test_mesh_editor_action_bar.py tests/test_mesh_resident_editor_regressions.py tests/test_static_replacement_mesh_edit_dotnet_toggle.py tests/test_static_replacement_d3d11_cache.py tests/test_mesh_deformer.py tests/test_mesh_selection_tools.py tests/test_archive_structured_asset_preview.py tests/test_rigging_binary_parsers.py
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_harness_scenario_registry.py tests/test_mesh_harness_real_dotnet_evidence.py tests/test_mesh_dotnet_live_stroke_dispatch.py
.\.venv\Scripts\python.exe -m pytest tests/test_scene_import_uv_contract.py tests/test_scene_import_normalization.py tests/test_scene_importer_gltf.py
.\scripts\codex_check.ps1 -Area mesh -GameRoot "C:\games\Steam\steamapps\common\Crimson Desert"
.\scripts\codex_check.ps1 -Area mesh-unit
```

The default .NET GPU soak is the release-scale 1,000,000-vertex / 1,000-update
60 Hz-equivalent upload gate and never shows a window. Verified frames bracket
the paced upload interval; their timings remain evidence but do not throttle
or redefine the edit-handler gate. The report also proves exact editable and
reference visibility plus pane roles for Side by Side, Overlay, Replacement
Only, and Original Only. It additionally renders hidden offscreen front, back,
and oblique captures of both a two-sided neutral plane and a textured,
fully-metallic two-sided plane through the production shader. It rejects low
center-patch luminance, lost texture contrast, background collapse, or
front/back lighting imbalance, and excessive angle-driven chromaticity or
all-view brightness drift. That synthetic GPU check is regression evidence,
not a substitute for the explicit real-PAC visual gate. For a fast environment check,
use `--gpu-soak-smoke --gpu-soak-vertices 30000 --gpu-soak-updates 100
--gpu-soak-warmup 16 --gpu-soak-no-cadence`; smoke JSON is explicitly marked
`release_gate_eligible=false`.

Native-core protocol, responsiveness, production .NET, and legacy-renderer
compatibility checks:

```powershell
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-benchmark --output "$env:TEMP\cdmw-native-mesh-editor-benchmark"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-sparse-update-soak --output "$env:TEMP\cdmw-native-mesh-editor-sparse-update-soak"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-static-screen-stroke --output "$env:TEMP\cdmw-native-mesh-editor-static-screen-stroke"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-qt-responsiveness --output "$env:TEMP\cdmw-native-mesh-editor-qt"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario native-mesh-editor-qt-cancellation --output "$env:TEMP\cdmw-native-mesh-editor-qt-cancel"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-mesh-editor-dotnet-edit-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-real-archive-mesh-editor-dotnet-edit"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-mesh-editor-d3d11-edit-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-real-archive-mesh-editor-d3d11-edit"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-rigging-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-rigging"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-animation-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-animation"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-sequence-binding-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-sequence"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario real-archive-app-workflow-smoke --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --output "$env:TEMP\cdmw-mesh-real-archive-app-workflow"
```

The `real-archive-mesh-editor-dotnet-edit-smoke` scenario is canonical.
`real-archive-mesh-editor-d3d11-edit-smoke` is legacy C++ renderer
compatibility only. Registry validation fails if a production visual role is
not .NET/Vortice or if a legacy/checker role is not opt-in compatibility-only;
normal/full QA metadata excludes both visual classes. The real proof cycles the
same resident nude PAC through neutral untextured faces, wire plus vertices,
vertices only, and restored production textures. It requires stable PID/HWND,
zero package/decode/SRV churn, non-black geometry, and captured draw counters
for every mode. `mesh-dotnet-native-parity-report` is a headless, offline
OpenImageIO comparison for two explicit PNG captures. It reports mean/RMS/max
error, peak SNR, threshold counts, and an amplified absolute-difference PNG.
It does not create captures or prove matching camera/light/provenance, so a
pass is regression evidence and never replaces the canonical real-PAC visual
gate. Configure `oiiotool` with `--oiio-path`, `CDMW_OIIO_BIN`, or `PATH`:

```powershell
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario mesh-dotnet-native-parity-report --parity-reference "$env:TEMP\native.png" --parity-candidate "$env:TEMP\dotnet.png" --output "$env:TEMP\cdmw-mesh-image-parity"
```

Exact external-model import regression (local licensed/source assets, opt-in):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m real_game tests/test_real_external_sword_import.py
.\.venv\Scripts\python.exe tools\build_mesh_material_profile_corpus.py --game-root "C:\games\Steam\steamapps\common\Crimson Desert" --external-model "E:\ModelCatalogue\downloads\.cdmw_extracted\wolf_gravestone_sword_free (1)\scene.gltf" --oiio-path ".\.venv\Scripts\oiiotool.exe" --output "$env:TEMP\cdmw-mesh-material-profile-corpus.json"
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_material_profile_corpus.py tests/test_mesh_material_resource_policy.py
```

This resolves `wolf_gravestone_sword_free (1).zip` through production catalogue
ingestion and reads
`character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0016.pac`
through archive identity. It verifies centered/Y-grounded placement, one shared
side-by-side/overlay grid, discovered non-checker texture inputs, and unchanged
source PAMT/PAZ fingerprints. The corpus command consumes the scene produced by
that verified ZIP ingestion rather than treating the ZIP itself as a scene.
The profile corpus records supported-profile
channel/criticality/scalar/tint/normal-Y/layer contracts, real PAC and external
content-addressed inputs, OpenImageIO metadata/statistics, and required/optional
synthetic failures. Identical inputs must produce an identical corpus
fingerprint. Its scope is translator/resource parity; deterministic production
captures provide the separate renderer-pixel evidence. Packaged texture presentation is separately
confirmed by the explicit local Computer Use replay.

Protocol-only local smoke, when a real game archive is not available:

```powershell
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario service-smoke --output "$env:TEMP\cdmw-mesh-editor-service-smoke"
```

Resumable material corpora use stable source fingerprints and atomically replace
their JSON/CSV evidence. Reuse the same output and advance `--chunk-index` until
`progress.complete=true`. External ZIP member accounting includes parent stamp,
member path, CRC, expanded size, and a supported/review-required/safely-blocked
classification. PAC_XML reads normalized PAMT identities through the archive
reader and hashes every PAMT plus each PAZ that actually supplies an audited
entry before and after; unrelated sibling PAZs are excluded. `ok` remains false
if any source archive changes, accounting is incomplete, or a row is unclassified.
For the external catalogue, a caught per-asset parse failure is recorded as
`safely_blocked` and remains in `read_parse_error_count`; it is not a corpus
process crash. `corpus_ok` requires complete accounting, complete ZIP-member
classification, and zero unclassified rows.

```powershell
.\.venv\Scripts\python.exe -m tools.audit_external_model_catalogue --out-json "$env:TEMP\cdmw-external-model-audit.json" --audit-zip-contents --resume --chunk-size 500 --chunk-index 0
.\.venv\Scripts\python.exe -m tools.audit_pac_xml_material_authority --roots "C:\games\Steam\steamapps\common\Crimson Desert" --out-json "$env:TEMP\cdmw-pac-xml-audit.json" --out-csv "$env:TEMP\cdmw-pac-xml-audit.csv" --resume --chunk-size 500 --chunk-index 0
.\.venv\Scripts\python.exe -m pytest tests/test_external_model_audit_resume.py tests/test_external_model_audit_catalogue.py tests/test_pac_xml_material_authority_audit.py tests/test_pac_xml_material_authority_corpus.py
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
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_report_output_async.py tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_workspace_editable_package_buttons_emit_requests tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_opens_last_editable_package_folder tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_runs_validation_report_in_background tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_copies_validation_report_json tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editable_package_workers_export_and_import_with_validation tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_replace_working_mesh_blocks_obj_sidecar_source_hash_mismatch
```

Focused patched-asset rebuild UI/service smoke:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_rebuild_asset_writes_validated_output_file tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_rebuild_asset_refuses_original_source_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_workspace_rebuild_panel_reflects_report tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_rebuild_asset_requires_passing_validation_and_output_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_editor_tab_preview_rebuilt_asset_routes_archive_target_and_output_path tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_shell_mesh_editor_preview_rebuilt_asset_routes_import_preview_preset tests/test_archive_mesh_export_naming.py::ArchiveMeshExportNamingTests::test_rebuilt_asset_preset_flows_open_mesh_editor_and_schedule_preview_and_patch tests/test_mesh_editor_action_bar.py::MeshEditorActionBarTests::test_mesh_rebuild_report_worker_writes_asset_when_output_path_is_set
```

`codex_check -Area mesh-unit` excludes the developer harness and is non-visual
unit/protocol coverage only. Default pytest and `codex_check -Area full` run
every non-visual split harness test; only tests marked `visual` or `real_game`
are deselected. Use `codex_check -Area mesh` for the real in-game PAC visual
edit proof.
Run visible harness commands only when intentionally validating the production
.NET renderer or legacy compatibility. The canonical .NET proof requires
`renderer_backend=d3d11_vortice_shader`, `edit_backend=cdmw_mesh_core_0.1`, real
archive DDS bindings, selected-only geometry changes, stationary native HWNDs,
sub-16.7 ms handler p95, sub-200 ms heartbeat gaps, and unchanged PAMT/PAZ hashes.

Do not use `native-mesh-editor-d3d11-delta`,
`native-mesh-editor-d3d11-payloads`, or `full-suite-smoke` as visual edit proof.
They are synthetic/protocol regression harnesses and intentionally do not show game geometry.
The harness blocks them by default; pass `--allow-synthetic-d3d11` only for
protocol-only regression testing.

`tools/headless_feature_stress.py` never schedules the visible .NET proof by
default, even when `--game-root` is present. Pass `--include-native-visual`
only when a visible real-PAC .NET/Vortice window and automated mouse input are
intended.
Its focused facade/profile/output-safety/cache probe gate is:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_headless_feature_stress.py
```

## Texture Workflow

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_texture_decode_cache_concurrency.py tests/test_texture_native_backend.py tests/test_dds_resource_limits.py tests/test_texture_workflow_ui_source_guards.py tests/test_texture_workflow_asset_authoring_panel.py tests/test_texture_domain_profiles.py tests/test_texture_workflow_unavailable_editor.py tests/test_texture_editor_workers.py tests/test_texture_edit_hot_path.py tests/test_texture_editor_ui_helpers.py tests/test_texture_editor_native_service.py tests/test_texture_editor_dev_harness.py tests/test_static_texture_replacement.py
.\scripts\codex_check.ps1 -Area texture
```

## Supporting Feature Tabs

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_research_archive_picker_state.py tests/test_research_analysis_state.py tests/test_research_analysis_async.py tests/test_research_classification_review_state.py tests/test_research_display_preferences_state.py tests/test_research_layout_state.py tests/test_research_notes_state.py tests/test_research_reference_payload_state.py tests/test_research_refresh_population_state.py tests/test_research_texture_group_state.py tests/test_research_tree_column_specs.py tests/test_research_models.py tests/test_research_workers.py tests/test_research_service_boundary.py tests/test_research_state.py tests/test_import_order_regressions.py tests/test_architecture_import_boundaries.py tests/test_model_library_inline_preview_ui.py tests/test_model_library_ui_source_guards.py tests/test_item_icons_state.py tests/test_text_search_async_io.py tests/test_replace_assistant.py
```

## Runtime Regression Smokes

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_restructure_runtime_regression_smoke.py
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_supplemental_folder_scan.py tests/test_directory_scan_workers.py
.\.venv\Scripts\python.exe -m pytest tests/test_item_icon_output_workers.py tests/test_item_icon_workers.py tests/test_item_icon_loose_mod_patch.py tests/test_archive_item_icon_worker_decode.py tests/test_static_replacement_custom_icon_capture_async.py
.\.venv\Scripts\python.exe -m pytest tests/test_material_sidecar_editor_async.py tests/test_material_sidecar_editor.py
.\.venv\Scripts\python.exe -m pytest tests/test_mod_package_export.py tests/test_mod_package_retrofit.py tests/test_mod_package_retrofit_async.py
```

## Architecture Boundary Guards

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_architecture_size_ratchets.py tests/test_architecture_import_boundaries.py tests/test_architecture_no_wildcard_imports.py tests/test_architecture_public_facades.py tests/test_archive_workflow_boundary.py tests/test_preview_service_boundaries.py tests/test_mesh_workflow_service_boundary.py tests/test_texture_workflow_service_boundary.py tests/test_ui_workflow_service_facades.py tests/test_documentation_consistency.py
```

## Services, Domain, And Workers

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_services.py tests/test_asset_authoring_service.py tests/test_asset_authoring_workers.py tests/test_diagnostics_service.py tests/test_diagnostic_bundle_async.py tests/test_workers.py tests/test_shell_context.py
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-discovery --output "$env:TEMP\cdmw-asset-authoring-discovery"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-mesh-health --output "$env:TEMP\cdmw-asset-authoring-mesh-health"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-uv-report --output "$env:TEMP\cdmw-asset-authoring-uv-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-tangent-report --output "$env:TEMP\cdmw-asset-authoring-tangent-report"
.\.venv\Scripts\python.exe tools\mesh_editor_dev_harness.py --scenario asset-authoring-openimageio-report --output "$env:TEMP\cdmw-asset-authoring-openimageio-report"
```

`asset-authoring-mesh-health` writes both mesh-health and meshoptimizer
optimization preflight reports.

## Full Suite

```powershell
.\.venv\Scripts\python.exe -m pytest
.\scripts\codex_check.ps1 -Area full
.\run_full_qa.ps1
```

`run_full_qa.ps1` runs canonical non-visual pytest, compiles `cdmw`, `tests`,
and `tools`, then runs dependency, native, package, and packaged-startup gates
with per-step timeouts. All temporary pytest and
PyInstaller output stays under a unique system-temp directory; cleanup never
removes repository or user crash reports. It rebuilds the native helpers and
self-contained .NET Mesh Editor through the same release helper path as normal
packaging, then runs the exact `d3d11_vortice_shader`/hidden-window GPU smoke
against the packaged onedir `_internal/native/cdmw-mesh-dotnet-editor.exe`
before the packaged application startup smoke. Each child is started by one
owned `System.Diagnostics.Process`, so exact exit codes, timeout termination,
and process-tree cleanup remain observable on Windows PowerShell.

## Release Packaging

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dependency_pins.py tests/test_release_packaging.py
.\.venv\Scripts\python.exe scripts\verify_release_dependencies.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onefile -BuildProfile release
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_pyside6_app.ps1 -Mode onedir -BuildProfile release
```

Both release modes publish the self-contained .NET helper, require its hidden
`d3d11_vortice_shader` GPU smoke to keep all native windows hidden, and run the
packaged offscreen startup verifier before moving output into `dist/`. The
onedir publisher removes the smoke-created `workspace/` and
`CrimsonDesertModWorkbench.cfg` runtime artifacts before publishing. GitHub
Actions runs the complete nonvisual gate on Python 3.11 and 3.14 first;
packaging has a hard dependency on both matrix jobs. CI explicitly excludes
`visual` and `real_game` tests. Licensed local game evidence remains the separate
`codex_check.ps1 -Area mesh -GameRoot <PATH>` gate and is never scheduled by CI.

## Notes

- Prefer targeted tests before broader suites.
- Prefer behavior, protocol, import-order, AST-boundary, and golden-corpus tests.
  Keep narrow source guards only while legacy PySide wiring has no practical
  behavior seam, and delete them when the owning controller is extracted.
- Update this matrix when tests move, split, or stop being authoritative for a change type.
