# Project Map

Last reviewed: 2026-07-11

Use this file for navigation. Use `docs/project-map-detailed.md` only when
you need historical ownership detail.

## Read Order

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/release-confidence-plan.md`
4. `docs/architecture.md`
5. `docs/test-matrix.md`
6. This map
7. `docs/project-map-detailed.md` only when package boundaries are unclear

## Cleanup Rule

Do not run blanket `git clean -fd`, `git clean -fdX`, or `git clean -xdf` in
this repo right now. Current untracked files include restructure source, docs,
and tests. Use targeted deletion for obsolete active-plan docs and ignored
cache/temp output only. Keep build/dist/workspace/local asset folders unless the
user explicitly names them.

## Docs Structure

| File or folder | Purpose |
|---|---|
| `docs/architecture.md` | Stable architecture, layer rules, ownership, and safety boundaries. |
| `docs/project-map.md` | Compact repo navigation map, owners, tests, and docs per area. |
| `docs/project-map-detailed.md` | Historical/file-level ownership detail; use only when compact map is not enough. |
| `docs/test-matrix.md` | Validation commands by feature area and release scope. |
| `docs/release-confidence-plan.md` | Release/readiness validation order and latest broad confidence evidence. |
| `docs/features/` | Long-lived feature/topic docs that are broader than one code package. |
| `docs/runbooks/` | Short operational flows for startup, workers, packaging, and similar procedures. |
| `docs/reference/` | Cross-cutting pitfalls, conventions, and lookup notes. |
| `docs/plans/active/<slug>.md` | Current implementation plans only. Remove superseded, completed, handoff, and new-chat notes. |
| `docs/ai/PROJECT_MEMORY.md` | Curated durable AI handoff notes, not chat logs or raw output. |
| Feature-local `README.md` files | Package-local usage and ownership notes next to the code they describe. |

## Entry Points

- `cdmw_app.py`: thin executable wrapper for `cdmw.app.bootstrap.main`.
- `cdmw/app/`: argument parsing, startup routing, splash/single-instance
  handling, PyInstaller cleanup, bootstrap reports, CLI/GUI dispatch.
- `cdmw/ui/main_window.py`: public compatibility facade for `MainWindow`,
  `run_gui`, and legacy imports.
- `cdmw/ui/theme_schemes.py`: app-theme palette data; `cdmw/ui/themes.py`
  keeps public theme lookup plus Qt palette and stylesheet generation.
- `cdmw/ui/shell/`: one-base shell window, composed controller/provider
  registry, tab wiring, actions, settings, theme, startup, close, diagnostics,
  and app context.
- `cdmw/ui/tools/`: utility tool workspaces such as Retrofit/Repackage Mods.
- `build_gui.py`, `build.bat`, `build_pyside6_app.ps1`,
  `CrimsonDesertModWorkbench.spec`: build/package entry points.

## Primary Ownership

| Concern | Primary code | Supporting code | Tests | Docs |
|---|---|---|---|---|
| Startup and GUI launch | `cdmw/app/`, `cdmw/ui/shell/` | `cdmw/services/startup_splash_service.py`, `cdmw/core/startup_splash_protocol.py`, `cdmw/ui/shell/startup_path_task_controller.py`, `cdmw_app.py`, `cdmw/ui/main_window.py` | `tests/test_shell_*.py`, `tests/test_startup_splash_lifecycle.py`, `tests/test_startup_archive_path_async.py`, `tests/test_runtime_dependency_smoke.py` | `docs/runbooks/startup-flow.md` |
| Archive browser and preview | `cdmw/ui/archive_browser/`; standalone v2 worker under `tools/dotnet_archive_backend/`; native mmap/decode core under `native/cdmw_full_archive_core/` | `cdmw/domain/archives/` protocol/catalogue contracts; resident client/resource discovery in `cdmw/ui/shell/archive_backend_*.py`; `archive_catalogue_service.py`; remote paged model/controller/providers; focused `cdmw/core/archive_*.py` compatibility owners; retained legacy scan/cache workers for the transition release | `tests/test_archive_backend_*.py`, `tests/test_archive_catalogue_service.py`, `tests/test_archive_remote_*.py`, native self-test and `Cdmw.FullArchive.Tests`, `tests/test_archive_workflow_boundary.py`, `tests/test_release_packaging.py` | `tools/dotnet_archive_backend/README.md`, `docs/runbooks/worker-lifecycle.md`, `docs/features/archive-safety-model.md`, `docs/architecture.md` |
| PAC XML structured editing | `cdmw/domain/pac_xml_editor.py`, `cdmw/domain/pac_xml_graph.py`; `cdmw/ui/archive_browser/pac_xml_editor_*.py` behind `material_sidecar_editor_dialog.py` | `cdmw/core/material_sidecar_editor.py`, `cdmw/core/material_sidecar_package.py`, `cdmw/services/material_sidecar_document_service.py`; existing archive indexes, Asset Family evidence, and material preview service | `tests/test_pac_xml_editor_*.py`, `tests/test_material_sidecar_editor.py`, `tests/test_material_sidecar_editor_async.py`, `tests/test_archive_material_sidecar_actions.py` | Archive Browser in-app help, `docs/test-matrix.md` |
| HKX/Havok documents | `cdmw/core/archive_hkx.py` direct-export facade; bounded parsing/types/summary/collision/edit/XML owners plus focused record-layout, converter, fixup, readiness, editor-model, relationship, Havok-view, edit-gate, XML-metadata, editable-XML, descriptor, role, geometry, overlay, preview, corpus, and `hkx_native.py` owners | Thin Archive Browser `hkx_editor_dialog.py` facade over registry-ordered `hkx_editor_dialog_*_part_*.py` UI owners; bounded parsing, fixup, layout, schema/evidence, graph/readiness, writer, editing, and JSON modules behind `native/cd_hkx/src/lib.rs` | `tests/test_archive_hkx_decomposition.py`, `tests/test_archive_hkx_helper_decomposition.py`, `tests/test_native_hkx_decomposition.py`, `tests/test_hkx_editor_dialog_decomposition.py`, `tests/test_hkx_preview.py`, `tests/test_hkx_native_backend.py`, `tests/test_hkx_ui_source_guards.py` | `docs/architecture.md`, `native/cd_hkx/README.md` |
| Prefab JSON import | `cdmw/core/prefab_json.py` and `prefab_corpus.py` facades; focused `prefab_json_*.py` and `prefab_corpus_*.py` owners; Archive Browser actions | `cdmw/core/crimson_formats.py`, attachment patches, `tools/report_prefab_json_import_corpus.py` | `tests/test_prefab_json_import.py`, `tests/test_prefab_corpus*.py`, `tests/test_prefab_decomposition.py`, source guards | `docs/features/prefab-json-import.md` |
| Mesh Editor and replacement builder | `cdmw/ui/mesh_editor/tab.py` and `workspace.py` public classes over bounded `tab_*.py` and `workspace_*.py` UI owners; thin static-replacement callback/section facades over bounded `static_replacement_dialog_{callbacks,sections}_*_part_*.py` owners; thin mesh-edit factory over bounded `static_replacement_mesh_edit_*.py` state/action/history/stroke owners; `cdmw/ui/archive_browser/mesh_launch_flow.py` | `cdmw/services/mesh_service.py` plus focused service owners; `mesh_workflow_service.py`; bounded `cdmw/modding/mesh_native_*.py` client/session/payload/kernel/report owners behind `mesh_native_core.py`; `cdmw/modding/static_mesh_*.py`; `cdmw/rendering/native_preview_*.py`; resident `native/cdmw_mesh_core/`; production .NET/Vortice renderer under `tools/dotnet_mesh_editor_experiment/`; compatibility-only `native/cdmw_d3d11_preview/`; `tools/mesh_harness/` behind `tools/mesh_editor_dev_harness.py`; mesh schemas | `tests/test_static_replacement_dialog_factory_decomposition.py`, `tests/test_static_replacement_mesh_edit_decomposition.py`, `tests/test_mesh_editor_tab_decomposition.py`, `tests/test_mesh_editor_workspace_decomposition.py`, `tests/test_mesh_service_decomposition.py`, `tests/test_mesh_native_core_decomposition.py`, `tests/test_native_mesh_core_decomposition.py`, `tests/test_native_d3d11_preview_decomposition.py`, `tests/test_mesh_harness_scenario_registry.py`, `tests/test_mesh_harness_real_dotnet_evidence.py`, `tests/test_mesh_dotnet_live_stroke_dispatch.py`, `tests/test_mesh_*.py`, `tests/test_static_replacement_*.py` | `docs/features/mesh-editing-pipeline.md`, `docs/features/mesh-editor-visual-material-parity-audit.md`, `docs/mesh_editor_net_repair_audit.md`, `docs/mesh_editor_net_authoritative_renderer_audit.md` |
| Texture workflow and editor | `cdmw/ui/texture_workflow/` | `cdmw/services/texture_workflow_service.py`, `cdmw/core/texture_pipeline/`, `cdmw/core/texture_native.py`, `cdmw/core/texture_decode_cache.py`, `cdmw/core/texture_native_preview_cache.py`, `native/cd_texture_dx/`, `tools/texture_replacer_headless_harness.py`, `cdmw/domain/textures/` | `tests/test_texture_*.py`, `tests/test_static_texture_replacement.py` | `docs/architecture.md`, `docs/test-matrix.md` |
| Asset authoring helpers | `cdmw/services/asset_authoring_service.py`, `cdmw/workers/asset_authoring_workers.py` | `cdmw/ui/texture_workflow/asset_authoring_panel.py`, `native/cdmw_mesh_core/` | `tests/test_asset_authoring_*.py`, asset-authoring harness scenarios | `docs/features/asset-authoring-integrations.md` |
| Research | `cdmw/ui/research/`, `cdmw/services/research_service.py`, `cdmw/domain/research/` | focused `cdmw/core/research_*.py` owners; cached `cdmw/core/research.py` facade; research workers | `tests/test_research_*.py`, import-order and architecture boundary tests | `cdmw/ui/research/README.md`, `docs/architecture.md` |
| Supporting feature tabs | `cdmw/ui/model_library/`, `cdmw/ui/item_icons/`, `cdmw/ui/text_search/`, `cdmw/ui/replace_assistant/` | focused Item Icon/Model Library/text-search/Replace Assistant services; compatibility core owners | matching `tests/test_*` files | feature READMEs when present |
| Diagnostic bundle export | `cdmw/services/diagnostic_bundle_service.py`, `cdmw/ui/shell/profile_controller.py` | shell utility worker, diagnostics service | `tests/test_diagnostic_bundle_async.py`, `tests/test_diagnostics_service.py` | `docs/architecture.md`, `docs/runbooks/worker-lifecycle.md` |
| Localization files | `cdmw/services/localization_file_service.py`, `cdmw/workers/localization_workers.py` | `cdmw/ui/localization.py`, `cdmw/ui/shell/language_controller.py` | `tests/test_localization_async_io.py`, `tests/test_localization_translations.py` | `docs/architecture.md` |
| Utility tools | `cdmw/ui/tools/` | `cdmw/core/mod_package_retrofit.py`, `cdmw/core/mod_package.py`; lazy `tools/headless_feature_stress.py` facade over `tools/headless_stress/` | `tests/test_mod_package_retrofit.py`, `tests/test_restructure_runtime_regression_smoke.py`, `tests/test_headless_feature_stress.py` | `cdmw/ui/tools/README.md`, `docs/test-matrix.md` |
| Services/domain/workers | `cdmw/services/`, `cdmw/domain/`, `cdmw/workers/` | feature callers | `tests/test_services.py`, `tests/test_workers.py`, architecture tests | `docs/runbooks/worker-lifecycle.md` |
| App-managed workspace folders | `cdmw/services/workspace_layout.py` | `cdmw/core/texture_pipeline/workspace.py`, shell settings/startup | `tests/test_services.py`, startup/crash guards | `docs/architecture.md` |

## Boundary Rules

- Do not add logic to `cdmw_app.py`.
- Do not add feature logic to `cdmw/ui/main_window.py`.
- Put UI shell behavior under `cdmw/ui/shell/`.
- Put feature UI under `cdmw/ui/<feature>/`.
- Put business coordination under `cdmw/services/`.
- Put pure rules under `cdmw/domain/`.
- Put long-running work under `cdmw/workers/`.
- Do not mutate archives directly from UI code.
- Preserve public imports through compatibility wrappers while moving internals.

## Validated Baseline

The whole-codebase repair closed on 2026-07-11; current canonical headless QA
passes 5,107 tests. Release onedir packaging/startup, packaged Vortice GPU smoke,
and the explicit read-only .NET/Vortice real-game proof passed. No implementation
plan is active.
Keep the one-base composed `MainWindow`, cached compatibility facades,
dependency direction, and lowered size ratchets intact.

Model Library auto-preview and Preview Here prepare local models through
`cdmw/services/model_library_preview.py` inside the Model Library task worker,
then show them in the inline native D3D11 host. Manual Archive Browser preview
stays routed through `preview_mesh_requested`.
Local Model Library scans compute texture status in `cdmw/core/model_catalogue.py`
while the scan task is already off the UI thread; result population reads the
payload field and must not rescan ZIPs or folders from UI code.

## Where Not To Edit

- Generated output, caches, build/dist output, crash reports, local game payloads,
  restore points, and `graphify-out/`.
- `.venv/`, `.tools/`, `workspace/`, legacy root workspace folders such as
  `input_dds/`, `dds_final/`, `archive_cache/`, and `app_restore_points/`
  unless the user explicitly asks for broader local cleanup.
