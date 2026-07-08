# CDMW Deep Review Fix Status Handoff

Last updated: 2026-07-08
Workspace: `D:\Byggverkstaden\app_restructuring`

## Purpose

This file is the handoff for continuing the deep-review fix plan in a new session. It separates items that are code-complete and validated from items that are still open. Do not mark the remaining items complete until the specific open work and validation listed below are done.

## Ground rules for the next session

- Do not reset, clean, discard, or overwrite the current working tree.
- Do not commit unless explicitly asked.
- Preserve existing user changes in `cdmw/modding/static_mesh_geometry.py` and `tests/test_static_mesh_replacer_preview.py`.
- Stage explicit files only if a commit is later requested. Do not use `git add -A`.
- Keep `cdmw_app.py` and `cdmw/ui/main_window.py` thin.
- Do not add feature logic to `cdmw/ui/main_window.py`.
- Do not run slow work on the UI thread.
- Do not mutate archives directly from UI code.
- For Mesh Editor visual proof, use real game PAC validation, not only synthetic mesh-unit tests.

## 100% done

These items are complete in code and have focused validation. Do not reopen them unless a regression appears.

| ID | Status | Area | What is done | Main validation |
|---|---:|---|---|---|
| CDMW-001 | 100% done | Static replacement grid placement | Placement reset now forces `grid_flat` in both normal and modify-original clone flows. The old conditional fallback to manual is blocked by tests. | Static replacement transform tests and grid-flat tests passed. |
| CDMW-002 | 100% done | .NET mesh editor renderer and handoff guard | .NET launch package now declares OBJ sidecar interchange risk, requires edit operations, blocks degraded embedded production renderer states, validates material parity warnings/blockers, and prevents importing invalid output. | `dotnet build`, `tests/test_mesh_dotnet_experiment.py`, `tests/test_mesh_editor_dotnet_lifecycle.py`. |
| CDMW-004 | 100% done | Texture diagnostics and native decode failure reporting | DirectXTex/native texture failures now produce structured failure reports. Unknown or unverified metadata is no longer reported as clean decoded metadata. | `tests/test_texture_native_backend.py`, `tests/test_texture_*.py`. |
| CDMW-005 | 100% done | MeshService selection preservation | `replace_working_mesh()` preserves selection for same-topology replacement and clears selection with diagnostics when topology changes or previous selection is invalid. | Focused `tests/test_mesh_service_editing.py` cases passed. |
| CDMW-006 | 100% done | Archive and texture worker lifecycle | Archive preview/filter/prefetch and texture worker paths now record explicit cancellation, stale-result, shutdown, and failure reasons instead of silently swallowing worker lifecycle states. | Archive worker tests, archive test groups, and py_compile passed. |
| CDMW-007 | 100% done | Source guards for corrected behavior | Source guards were updated to protect the corrected grid-flat reset, .NET renderer blocker helpers, and archive worker lifecycle hooks. | Focused source-guard and related test groups passed where relevant. |
| CDMW-008 | 100% done | .NET mesh editor audit docs | .NET repair and authoritative renderer audit docs now describe current renderer blocking, OBJ sidecar risk, edit-operation authority, material parity gaps, and split file layout. | Docs updated and relevant .NET tests passed. |
| CDMW-009 | 100% done | Archive browser brittle source guard | The archive browser asset-understanding source guard was corrected to allow the current multiline enhanced index call shape instead of enforcing the old one-line shape. | `tests/test_archive_*.py` and `tests/test_archive_browser_*.py` passed after the fix. |
| CDMW-011 | 100% done | Focused validation coverage | New and updated tests cover the changed mesh, texture, archive, .NET, and transform behavior. | See validation section below. |
| CDMW-012 | 100% done | Renderer import safety and status propagation | Embedded .NET renderer blocked states and material parity problems are surfaced in the host UI and prevent unsafe output import. | .NET build and focused .NET lifecycle tests passed. |

## Partially done, not 100%

### CDMW-003, broad exception and silent failure cleanup

Status: partially done.

What is done:

- New archive, prefetch, render lifecycle, texture worker, and native texture failure paths now record structured runtime events instead of silently passing failures.
- Focused tests were added around those new explicit lifecycle/failure events.
- `cdmw/ui/mesh_editor/builder_host.py` no longer has broad `except Exception` catches; drag/drop event fallbacks now catch expected Qt/duck-typing failures and include explicit best-effort comments.
- Several `cdmw/ui/mesh_editor/tab.py` silent/broad fallback paths were narrowed, documented as best-effort UI sync, or changed to record .NET diagnostics/evaluation write failures.
- Remaining broad catches in `cdmw/ui/mesh_editor/tab.py` were audited in this pass. They are not silent: each remaining catch is user-visible, event-recorded, cleanup-and-reraise, or explicitly best-effort derived UI state.
- `cdmw/ui/mesh_editor/native_preview_payloads.py`, `native_preview_runtime.py`, `shell_bridge.py`, and `session.py` had import/runtime/path broad catches narrowed where the expected failure types are known.
- `cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py` had formerly silent Mesh Editor callback failure paths made explicit: static-session skeleton attach failures, morph-slider native bake snapshot/dispose failures, native undo/restore exceptions, live-stroke snapshot/restore exceptions, sparse snapshot/restore/normal exceptions, D3D11 diagnostic metrics fallback, and native selection failures are now narrowed, commented, or event-recorded instead of silently returning `None`/`False`.
- `cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py` had broad catches reduced from 26 to 9. Remaining broad catches in that file are now classified in-source as user-visible, status-routed, or event-recorded paths; D3D11 status file read/parse paths were narrowed to concrete read/JSON errors.
- `cdmw/ui/archive_browser/hkx_editor_dialog.py` had broad catches reduced from 22 to 4. Non-critical HKX preview/render-settings/overlay/teardown/file-export paths now catch expected Qt/runtime/type/IO errors only, and the remaining broad catches are classified in-source as optional placement evidence or user-visible socket/preview failures.
- `cdmw/core/archive_mesh_import_preview.py` had broad catches reduced from 18 to 3. DDS metadata fallbacks, texture preview binding fallbacks, sidecar reads/classification, optional imports, and generated texture preview metadata now catch concrete file/parser/runtime failure types. The remaining broad catches are classified in-source as user-visible preview summary paths for material parser, static texture replacement, and paired LOD rebuild failures.
- Model Library inline D3D11 preview restored fast-first texture behavior by passing `high_quality_textures=False` for the initial preview package while keeping the active high-quality setting available for returned status/reporting.

What is left:

- A full audit of broad `except Exception` usage has not been completed.
- Known remaining areas to inspect include:
  - wider archive/browser/core/service paths outside the focused Mesh Editor/static replacement/HKX/archive mesh import preview passes. A repo scan currently finds about `1,118` `except Exception` matches across `262` Python files.
  - highest-density remaining unaudited files include `archive_model_textures.py`, `diagnostics_service.py`, `research_texture_analysis.py`, `texture_pipeline/preview.py`, and several archive/core preview/cache helpers. `static_replacement_dialog_mesh_edit_callbacks.py` still has broad catches, but the obvious silent native Mesh Editor fallback paths were converted to explicit telemetry in the latest pass. `hkx_editor_dialog.py`, `static_replacement_dialog_callback_factories.py`, and `archive_mesh_import_preview.py` now have only classified broad catches left.
  - remaining legacy UI guard/fallback paths that still catch broadly
- Do not mark CDMW-003 as 100% complete until every remaining broad catch has one of these outcomes:
  - narrowed exception type,
  - logged/recorded failure reason,
  - explicit safe best-effort comment where failure is intentionally non-fatal,
  - test coverage for the intended behavior.

Recommended next validation for CDMW-003:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/mesh_editor/tab.py cdmw/ui/mesh_editor/builder_host.py
.venv/Scripts/python.exe -m pytest tests/test_mesh_editor_dotnet_lifecycle.py tests/test_mesh_dotnet_experiment.py tests/test_mesh_editor_builder_host.py tests/test_static_replacement_mesh_edit_dotnet_toggle.py -q --basetemp "$TEMP/cdmw-cdmw003"
```

### CDMW-010, oversized file splitting

Status: partially done. The .NET part is done, but the full CDMW-010 issue is not done.

100% done within CDMW-010:

- `tools/dotnet_mesh_editor_experiment/Program.cs` has been mechanically split from 5,318 lines to 478 lines.
- The .NET helper still builds cleanly after the split.
- Focused .NET Python tests still pass.
- The split is mechanical, with no intentional behavior or protocol changes.
- `cdmw/modding/mesh_native_core_payload_helpers.py` now owns pure native mesh payload/index helper functions extracted from `mesh_native_core.py` with import-compatible names preserved in `mesh_native_core.py`.
- `cdmw/modding/mesh_native_core_blend_helpers.py` now owns pure topology blend/index helper functions extracted from `mesh_native_core.py`; private helper aliases are still imported through `mesh_native_core.py` for compatibility.
- First `static_replacement_dialog_callback_factories.py` split pass is done for three low-risk whole factory groups: mesh diagnostics, source mix, and texture-detail/UV callbacks now live in separate modules and are imported by the compatibility facade.
- Second `static_replacement_dialog_callback_factories.py` split pass is done for accept-dispatch and custom-icon callback groups; the facade remains import-compatible and source guards now aggregate both modules.
- Third `static_replacement_dialog_callback_factories.py` split pass is done for source-role-tree and manual material profile runtime callback groups; the facade remains import-compatible and source guards now aggregate both modules.
- `static_replacement_dialog_prompt_setup.py` was reduced from `664` lines to the `620` line architecture limit by moving setup mesh-fit and sidecar context helpers into `static_replacement_dialog_prompt_setup_helpers.py`.
- `static_replacement_d3d11_presentation_state.py` was reduced from `810` lines to `736` lines by moving D3D11 loading/watchdog detail text helpers into `static_replacement_d3d11_loading_details.py`.
- `static_replacement_preview_models.py` was reduced from `537` lines to `434` lines by moving source-selection overlay helpers into `static_replacement_preview_selection_overlay.py`.
- `hkx_editor_dialog.py` was trimmed from `7,549` to the current `7,545` line architecture limit without behavior changes.
- `tests/test_alignment_dialog_source_guards.py` now aggregates the callback-factory facade plus the new split modules so source guards continue to validate moved callback bodies.

Current .NET split files:

- `tools/dotnet_mesh_editor_experiment/ProgramEntry.cs`
- `tools/dotnet_mesh_editor_experiment/RuntimeSupport.cs`
- `tools/dotnet_mesh_editor_experiment/NativeWindowHost.cs`
- `tools/dotnet_mesh_editor_experiment/ObjDocument.cs`
- `tools/dotnet_mesh_editor_experiment/NetEdgeTopology.cs`
- `tools/dotnet_mesh_editor_experiment/NetMaterialSet.cs`
- `tools/dotnet_mesh_editor_experiment/NetTextureSet.cs`
- `tools/dotnet_mesh_editor_experiment/GeometryPrimitives.cs`
- `tools/dotnet_mesh_editor_experiment/ExperimentForm.Controls.cs`
- `tools/dotnet_mesh_editor_experiment/ExperimentForm.Json.cs`
- `tools/dotnet_mesh_editor_experiment/ExperimentForm.Output.cs`
- `tools/dotnet_mesh_editor_experiment/ExperimentForm.Protocol.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Geometry.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Renderer.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Status.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Topology.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.SelectionCommands.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.SelectionActions.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.SelectionPicking.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Input.cs`
- `tools/dotnet_mesh_editor_experiment/MeshViewport.Painting.cs`

Remaining oversized files:

| File | Current lines | Status |
|---|---:|---|
| `cdmw/modding/mesh_native_core.py` | 12,178 | Partially split, still oversized. |
| `cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py` | 9,499 | Partially split. Mesh diagnostics, source mix, texture-detail/UV, accept-dispatch, custom-icon, source-role-tree, and manual-profile groups extracted; continue whole top-level factory groups and keep source guard aggregation updated. Broad catches reduced from 26 to 9 in the latest CDMW-003 pass. |
| `native/cdmw_mesh_core/src/main.cpp` | 21,605 | Not split yet. |
| `native/cdmw_d3d11_preview/src/main.cpp` | 9,553 | Not split yet. |

Already split from `mesh_native_core.py`:

- `cdmw/modding/mesh_native_core_constants.py`
- `cdmw/modding/mesh_native_core_diagnostics.py`
- `cdmw/modding/mesh_native_core_temp_paths.py`
- `cdmw/modding/mesh_native_core_payload_helpers.py`
- `cdmw/modding/mesh_native_core_blend_helpers.py`

Already split from `static_replacement_dialog_callback_factories.py`:

- `cdmw/ui/archive_browser/static_replacement_dialog_mesh_diagnostics_callbacks.py` (`262` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_source_mix_callbacks.py` (`208` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_texture_detail_uv_callbacks.py` (`226` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_accept_dispatch_callbacks.py` (`144` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_custom_icon_callbacks.py` (`272` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_source_role_tree_callbacks.py` (`262` lines)
- `cdmw/ui/archive_browser/static_replacement_dialog_manual_profile_callbacks.py` (`338` lines)

Other Python/UI split or size-fix files from this pass:

- `cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup_helpers.py` (`99` lines)
- `cdmw/ui/archive_browser/static_replacement_d3d11_loading_details.py` (`93` lines)
- `cdmw/ui/archive_browser/static_replacement_preview_selection_overlay.py` (`131` lines)

Do not mark CDMW-010 as complete until at least the remaining oversized Python/UI targets have been split to maintainable files and validated. Native C++ splitting can be a separate explicit milestone if preferred.

Recommended next CDMW-010 split order:

1. Continue splitting `static_replacement_dialog_callback_factories.py` by whole top-level factory groups, not nested helper fragments.
2. Keep `tests/test_alignment_dialog_source_guards.py` and any direct source guards aggregating the facade plus newly split modules.
3. Keep the original `static_replacement_dialog_callback_factories.py` as a compatibility facade to preserve public imports.
4. Next safer candidates are additional cohesive groups such as accept-build, material authority, selected-part controls, source-part assignment, source-tree selection, preview mode, preview model, or D3D11 refresh/loading/lifecycle groups, validated one batch at a time.
5. Re-run `tests/test_architecture_file_sizes.py` after size changes because it reveals blockers sequentially by file order.
6. Only after the Python/UI facade is stable, resume larger `mesh_native_core.py` extraction or plan native C++ splits separately.

## Current validation already run

Closure validation before parking this work:

```powershell
.venv/Scripts/python.exe -m compileall -q cdmw tests
```

Result: passed with no output.

```powershell
dotnet build tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj -c Release
```

Result: build succeeded with `0 Warning(s)` and `0 Error(s)`.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp "$TEMP/cdmw-close-sourceguards"
```

Result: `255 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_static_replacement_accept_state.py tests/test_static_replacement_diagnostics.py tests/test_full_import_model_replacement.py tests/test_static_replacement_preview_models.py tests/test_static_replacement_external_import_placement.py tests/test_static_replacement_startup_state.py tests/test_model_library_preview_quality.py tests/test_mesh_dotnet_experiment.py -q --basetemp "$TEMP/cdmw-close-focused"
```

Result: `94 passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area archive
```

Result: `102 passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area mesh-unit
```

Result: `720 passed, 4 deselected`

Latest validation after callback-factory split pass 3:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py cdmw/ui/archive_browser/static_replacement_dialog_source_role_tree_callbacks.py cdmw/ui/archive_browser/static_replacement_dialog_manual_profile_callbacks.py tests/test_alignment_dialog_source_guards.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_static_replacement_accept_state.py tests/test_static_replacement_diagnostics.py tests/test_full_import_model_replacement.py -q --basetemp "$TEMP/cdmw-callback-batch4"
```

Result: `118 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp "$TEMP/cdmw-sourceguards-callback-batch4"
```

Result: `255 passed, 36 subtests passed`

Latest validation after callback-factory split pass 2:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py cdmw/ui/archive_browser/static_replacement_dialog_accept_dispatch_callbacks.py cdmw/ui/archive_browser/static_replacement_dialog_custom_icon_callbacks.py tests/test_alignment_dialog_source_guards.py tests/test_full_import_model_replacement.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_static_replacement_accept_state.py tests/test_alignment_dialog_source_guards.py tests/test_static_replacement_diagnostics.py tests/test_full_import_model_replacement.py -q --basetemp "$TEMP/cdmw-callback-batch2"
```

Result: `118 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp "$TEMP/cdmw-sourceguards-callback-batch2"
```

Result: `255 passed, 36 subtests passed`

Latest validation after prompt/D3D11/preview-model size-split pass:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup_helpers.py cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py cdmw/ui/archive_browser/static_replacement_d3d11_loading_details.py cdmw/ui/archive_browser/static_replacement_preview_models.py cdmw/ui/archive_browser/static_replacement_preview_selection_overlay.py cdmw/ui/archive_browser/hkx_editor_dialog.py tests/test_alignment_dialog_source_guards.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_architecture_file_sizes.py tests/test_alignment_dialog_source_guards.py tests/test_static_replacement_preview_models.py tests/test_static_replacement_external_import_placement.py tests/test_static_replacement_startup_state.py -q --basetemp "$TEMP/cdmw-preview-models-split2"
```

Result: `133 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp "$TEMP/cdmw-sourceguards-after-size-splits"
```

Result: `254 passed, 36 subtests passed`

Latest validation after callback-factory split pass 1:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py cdmw/ui/archive_browser/static_replacement_dialog_mesh_diagnostics_callbacks.py cdmw/ui/archive_browser/static_replacement_dialog_source_mix_callbacks.py cdmw/ui/archive_browser/static_replacement_dialog_texture_detail_uv_callbacks.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_static_replacement_diagnostics.py tests/test_full_import_model_replacement.py -q --basetemp "$TEMP/cdmw-callback-factories-split-pass1"
```

Result: `175 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp "$TEMP/cdmw-callback-factories-split-sourceguards-only"
```

Result: `254 passed, 36 subtests passed`

Latest validation after this continuation:

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/mesh_editor/tab.py cdmw/ui/mesh_editor/builder_host.py cdmw/ui/mesh_editor/native_preview_payloads.py cdmw/ui/mesh_editor/native_preview_runtime.py cdmw/ui/mesh_editor/shell_bridge.py cdmw/ui/mesh_editor/session.py cdmw/ui/model_library/preview.py cdmw/modding/mesh_native_core.py cdmw/modding/mesh_native_core_payload_helpers.py cdmw/modding/mesh_native_core_blend_helpers.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_model_library_ui_source_guards.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all3
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_model_library_inline_preview_ui.py tests/test_model_library_preview.py tests/test_model_library_preview_quality.py tests/test_model_library_ui_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-model-library-current4
```

Result: `33 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all4
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_morph_slider_apply_is_native_owned_before_python_fallback tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_mesh_edit_strokes_reuse_session_topology_cache tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_subdivide_selection_is_explicit_topology_path_not_sculpt_toggle -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-mesh-edit-callback-tighten3
```

Result: `3 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all5
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_static_replacement_diagnostics.py tests/test_full_import_model_replacement.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-callback-factories-tighten
```

Result: `175 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all6
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/ui/archive_browser/hkx_editor_dialog.py cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_hkx_ui_source_guards.py tests/test_hkx_preview.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-hkx-dialog-tighten
```

Result: `73 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all7
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m py_compile cdmw/core/archive_mesh_import_preview.py
```

Result: passed with no output.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_full_import_model_replacement.py tests/test_mesh_import_preview_static_edit.py tests/test_archive_mesh_export_naming.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-archive-mesh-import-preview-tighten
```

Result: `109 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_alignment_dialog_source_guards.py tests/test_archive_browser_asset_understanding_ui_source_guards.py tests/test_archive_d3d11_renderer_ui_source_guards.py tests/test_archive_reference_preview_ui_source_guards.py tests/test_hkx_ui_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_mesh_morph_slider_ui_source_guards.py tests/test_model_library_ui_source_guards.py tests/test_texture_workflow_ui_source_guards.py tests/test_ui_responsiveness_source_guards.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-sourceguards-all8
```

Result: `254 passed, 36 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_service_editing.py tests/test_mesh_edit_operations.py tests/test_mesh_editor_builder_host.py tests/test_mesh_editor_action_bar.py tests/test_mesh_editor_controller.py tests/test_model_preview_native.py tests/test_mesh_editor_dev_harness.py::MeshEditorDevHarnessTests::test_native_mesh_core_fallback_telemetry_records_and_clears tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_live_vertex_update_bridge_is_wired tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_mesh_edit_control_changes_sync_state_without_preview_reload tests/test_static_replacement_mesh_edit_dotnet_toggle.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-mesh-continue-wide2
```

Result: `638 passed, 69 subtests passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area mesh-unit
```

Result: `720 passed, 4 deselected`

```powershell
dotnet build tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj -c Release
```

Result: `Build succeeded. 0 Warning(s). 0 Error(s).`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area smoke
```

Result: `8 passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area mesh -GameRoot "C:\games\Steam\steamapps\common\Crimson Desert"
```

Result: passed. Real PAC proof used `character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac`, selected and moved a real face cluster, had no native fallback events, and kept live stroke handler p95 about `5.76 ms` under the 16.7 ms frame budget.

Full pytest was attempted twice with `--basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-full-current-q`, but the Ratlink connector returned 502 before stdout was delivered. The orphaned pytest processes were waited out and exited; `.pytest_cache/v/cache/lastfailed` was `{}`. Treat full pytest as inconclusive because the actual pytest summary was lost.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_service_editing.py tests/test_mesh_edit_operations.py tests/test_mesh_editor_builder_host.py tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_live_vertex_update_bridge_is_wired tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_mesh_edit_control_changes_sync_state_without_preview_reload tests/test_static_replacement_mesh_edit_dotnet_toggle.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-mesh-helper-split2
```

Result: `402 passed, 66 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_dotnet_experiment.py tests/test_mesh_editor_dotnet_lifecycle.py tests/test_mesh_editor_builder_host.py tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_live_vertex_update_bridge_is_wired tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_mesh_edit_control_changes_sync_state_without_preview_reload tests/test_static_replacement_mesh_edit_dotnet_toggle.py -q --basetemp C:/Users/Ratrider/AppData/Local/Temp/cdmw-cdmw003-dotnet
```

Result: `24 passed`

Note: the same CDMW-003 pytest command failed once with `--basetemp c:/temp/cdmw-cdmw003-dotnet` because `c:/temp` did not exist. It was rerun with the user temp directory and passed.

Latest final validation after the long .NET split:

```powershell
dotnet build tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj -c Release
```

Result:

```text
Build succeeded.
0 Warning(s)
0 Error(s)
```

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_dotnet_experiment.py tests/test_mesh_editor_dotnet_lifecycle.py tests/test_mesh_editor_dev_harness.py::MeshEditorDevHarnessTests::test_native_mesh_core_fallback_telemetry_records_and_clears tests/test_mesh_edit_responsiveness_source_guards.py::MeshEditResponsivenessSourceGuardTests::test_native_mesh_fallback_telemetry_guards_long_harness tests/test_mesh_service_editing.py::MeshServiceEditingTests::test_native_submesh_snapshot_restore_strips_transient_preview_attrs -q --basetemp "$TEMP/cdmw-continue-long-final"
```

Result:

```text
22 passed
```

Broader validation already completed during this fix run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_static_replacement_transform_state.py tests/test_static_mesh_replacer_preview.py tests/test_static_replacement_combo_options.py -q --basetemp "$TEMP/cdmw-phase1"
```

Result: `102 passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_dotnet_experiment.py tests/test_mesh_editor_dotnet_lifecycle.py -q --basetemp "$TEMP/cdmw-dotnet-p1"
```

Result: `19 passed`

```powershell
dotnet build tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj -c Release
```

Result: `Build succeeded. 0 Warning(s). 0 Error(s).`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_texture_native_backend.py -q --basetemp "$TEMP/cdmw-texture-native"
```

Result: `17 passed, 2 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_texture_*.py -q --basetemp "$TEMP/cdmw-texture"
```

Result: `129 passed, 2 subtests passed`

```powershell
.venv/Scripts/python.exe -m pytest tests/test_archive_*.py tests/test_archive_browser_*.py -q --basetemp "$TEMP/cdmw-archive"
```

Result: `283 passed, 4 subtests passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area smoke
```

Result: `8 passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area archive
```

Result: `102 passed`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/codex_check.ps1 -Area mesh-unit
```

Result: `720 passed, 4 deselected`

## Tests not run yet or inconclusive

Open validation item:

```powershell
.venv/Scripts/python.exe -m pytest --basetemp "$TEMP/cdmw-full"
```

Full repo pytest was attempted earlier, but the connector returned 502 twice and lost the final pytest summary. Do not mark full repo validation complete from that attempt.

Full repo pytest was attempted again after callback-factory split pass 3:

```powershell
.venv/Scripts/python.exe -m pytest -q --basetemp "$TEMP/cdmw-full-current-risk-pass"
```

Result: the Ratlink connector returned 502 before stdout was delivered. Two pytest process trees were left running, then exited. The actual pytest summary was still not delivered, so full repo validation remains inconclusive. `.pytest_cache/v/cache/lastfailed` contained a stale node id for `tests/test_model_library_preview_quality.py::test_model_library_preview_uses_active_render_setting_for_high_quality_textures`; that exact node no longer exists, and the owning file was rerun:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_model_library_preview_quality.py -q --basetemp "$TEMP/cdmw-model-library-preview-quality-check"
```

Result: `3 passed`

Architecture file-size validation is green for the selected guarded files after the prompt-setup, D3D11 presentation, preview-model, HKX, and callback-factory split pass 3 checks. Full repo pytest remains open.

The two earlier mesh edit source-guard failures were resolved as intentional test drift from the .NET-first toggle path. The guards now assert that direct native preview transition is not run before the .NET launch attempt, while fallback paths still own `_mesh_edit_apply_preview_mode_transition(...)`.

## Current working tree notes

Expected modified tracked files include prior fixes plus the CDMW-010 split work. Expected new untracked files include the new .NET split files and the new `mesh_native_core_*` helper files.

Important untracked files that must not be lost:

- `cdmw/modding/mesh_native_core_constants.py`
- `cdmw/modding/mesh_native_core_diagnostics.py`
- `cdmw/modding/mesh_native_core_temp_paths.py`
- `cdmw/modding/mesh_native_core_payload_helpers.py`
- `cdmw/modding/mesh_native_core_blend_helpers.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_mesh_diagnostics_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_source_mix_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_texture_detail_uv_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_accept_dispatch_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_custom_icon_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_source_role_tree_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_manual_profile_callbacks.py`
- `cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup_helpers.py`
- `cdmw/ui/archive_browser/static_replacement_d3d11_loading_details.py`
- `cdmw/ui/archive_browser/static_replacement_preview_selection_overlay.py`
- all new `tools/dotnet_mesh_editor_experiment/ExperimentForm.*.cs` partial files
- all new `tools/dotnet_mesh_editor_experiment/MeshViewport.*.cs` partial files
- `tools/dotnet_mesh_editor_experiment/ProgramEntry.cs`
- `tools/dotnet_mesh_editor_experiment/RuntimeSupport.cs`
- `tools/dotnet_mesh_editor_experiment/NativeWindowHost.cs`
- `tools/dotnet_mesh_editor_experiment/ObjDocument.cs`
- `tools/dotnet_mesh_editor_experiment/NetEdgeTopology.cs`
- `tools/dotnet_mesh_editor_experiment/NetMaterialSet.cs`
- `tools/dotnet_mesh_editor_experiment/NetTextureSet.cs`
- `tools/dotnet_mesh_editor_experiment/GeometryPrimitives.cs`

## Recommended next session plan

1. Open workspace `D:\Byggverkstaden\app_restructuring`.
2. Read `AGENTS.md` and this file.
3. Run:

```powershell
git -c color.status=false status --short --untracked-files=all
```

4. Continue CDMW-010 by choosing one of these safer next targets:

   - `cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py`
     - completed batches: mesh diagnostics, source mix, texture-detail/UV, accept-dispatch, custom icon, source-role-tree, and manual-profile callbacks,
     - continue splitting by whole callback factory group,
     - keep compatibility imports/wrappers,
     - keep source guard aggregation updated for newly split modules,
     - run archive browser focused tests after each group.

   - `cdmw/modding/mesh_native_core.py`
     - continue extracting pure helper groups,
     - keep public functions import-compatible,
     - run py_compile and focused mesh service/native session tests after each group.

5. Defer native C++ splitting until Python/UI splits are stable unless explicitly asked.
6. After any split, run focused validation first, then broaden:

```powershell
.venv/Scripts/python.exe -m py_compile <changed python files>
dotnet build tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj -c Release
.venv/Scripts/python.exe -m pytest tests/test_mesh_dotnet_experiment.py tests/test_mesh_editor_dotnet_lifecycle.py -q --basetemp "$TEMP/cdmw-next"
```

7. Before claiming the whole plan is done, run real mesh validation. The two earlier source-guard failures were already resolved as intentional test drift from the .NET-first toggle path. Real PAC validation passed once after the .NET/native helper changes, but rerun it after any future Mesh Editor or native preview changes.

## Closure status for current state

This work can be parked and resumed later from this handoff. Current state has been validated with Python compile checks, the .NET helper build, broad source guards, architecture file-size guards, focused static replacement/model-library/.NET tests, archive area checks, and mesh-unit checks. Those checks are green.

Do not mark the entire deep review plan complete. The remaining oversized-file work, full repo broad-exception audit, native C++ split work, and full repo pytest summary are intentionally left open for a future session.

## Bottom line

100% done:

- CDMW-001
- CDMW-002
- CDMW-004
- CDMW-005
- CDMW-006
- CDMW-007
- CDMW-008
- CDMW-009
- CDMW-011
- CDMW-012
- CDMW-003 focused Mesh Editor tab/import/runtime pass: remaining broad catches in `cdmw/ui/mesh_editor/tab.py` have been audited as user-visible, event-recorded, cleanup-and-reraise, or explicit best-effort derived UI state.
- CDMW-003 focused static replacement Mesh Edit callback pass: formerly silent native snapshot/restore/selection and morph-slider bake callback failures in `static_replacement_dialog_mesh_edit_callbacks.py` now record runtime events or catch expected UI diagnostic failures only.
- CDMW-003 focused static replacement callback-factory pass: broad catches in `static_replacement_dialog_callback_factories.py` reduced from 26 to 9 and the remaining broad catches are classified in-source as user-visible, status-routed, or event-recorded.
- CDMW-003 focused HKX dialog pass: broad catches in `hkx_editor_dialog.py` reduced from 22 to 4 and the remaining broad catches are classified in-source as optional placement evidence or user-visible socket/preview errors.
- CDMW-003 focused archive mesh import preview pass: broad catches in `archive_mesh_import_preview.py` reduced from 18 to 3 and the remaining broad catches are classified in-source as user-visible preview summary paths.
- CDMW-010 only for the `.NET Program.cs` split subtask, extracted `mesh_native_core_payload_helpers.py`, extracted `mesh_native_core_blend_helpers.py`, `static_replacement_dialog_callback_factories.py` split passes for mesh diagnostics/source mix/texture-detail/UV/accept-dispatch/custom-icon/source-role-tree/manual-profile callback groups, prompt-setup helper split, D3D11 loading-detail split, preview selection-overlay split, and selected architecture file-size guard cleanup through `hkx_editor_dialog.py`

Still left for later:

- CDMW-003, full repo broad-exception audit outside the focused Mesh Editor/static replacement/HKX/archive mesh import preview passes
- CDMW-010, remaining oversized Python/UI/native files, including the still-oversized `static_replacement_dialog_callback_factories.py` facade, `mesh_native_core.py`, and the native C++ files
- Full repo pytest summary, because Ratlink returned 502 before delivering the final summary on full-suite attempts
