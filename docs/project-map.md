# Project Map

Last reviewed: 2026-07-08

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
- `cdmw/ui/shell/`: shell window, tab wiring, actions, settings, theme,
  startup, close, diagnostics, and app context.
- `cdmw/ui/tools/`: utility tool workspaces such as Retrofit/Repackage Mods.
- `build_gui.py`, `build.bat`, `build_pyside6_app.ps1`,
  `CrimsonDesertModWorkbench.spec`: build/package entry points.

## Primary Ownership

| Concern | Primary code | Supporting code | Tests | Docs |
|---|---|---|---|---|
| Startup and GUI launch | `cdmw/app/`, `cdmw/ui/shell/` | `cdmw_app.py`, `cdmw/ui/main_window.py` | `tests/test_shell_*.py`, `tests/test_runtime_dependency_smoke.py` | `docs/runbooks/startup-flow.md` |
| Archive browser and preview | `cdmw/ui/archive_browser/` | `cdmw/core/archive*.py`, `cdmw/workers/archive_*.py` | `tests/test_archive_*.py`, `tests/test_archive_browser_*.py` | `docs/features/archive-safety-model.md` |
| Prefab JSON import | `cdmw/core/prefab_json.py`, `cdmw/core/prefab_corpus.py`, `cdmw/ui/archive_browser/prefab_json_actions.py` | `cdmw/core/crimson_formats.py`, `cdmw/core/archive_attachment_patches.py`, `cdmw/ui/archive_browser/actions.py`, `tools/report_prefab_json_import_corpus.py` | `tests/test_prefab_json_import.py`, `tests/test_prefab_corpus.py`, `tests/test_prefab_corpus_tool.py`, `tests/test_prefab_json_actions_source.py`, `tests/test_crimson_formats.py` | `docs/features/prefab-json-import.md` |
| Mesh Editor and replacement builder | `cdmw/ui/mesh_editor/`, `cdmw/ui/archive_browser/static_replacement_*.py`, `cdmw/ui/archive_browser/mesh_launch_flow.py` | `cdmw/modding/static_mesh_*.py`, dormant `cdmw/modding/full_import_model_replacement.py`, `cdmw/rendering/native_preview_*.py`, `native/cdmw_mesh_core/`, `tools/dotnet_mesh_editor_experiment/`, `schemas/mesh/` | `tests/test_mesh_*.py`, `tests/test_static_replacement_*.py`, `tests/test_full_import_model_replacement.py` | `docs/features/mesh-editing-pipeline.md`, `docs/mesh_editor_net_repair_audit.md`, `docs/mesh_editor_net_authoritative_renderer_audit.md` |
| Texture workflow and editor | `cdmw/ui/texture_workflow/` | `cdmw/core/texture_pipeline/`, `cdmw/domain/textures/` | `tests/test_texture_*.py`, `tests/test_static_texture_replacement.py` | `docs/architecture.md` |
| Asset authoring helpers | `cdmw/services/asset_authoring_service.py`, `cdmw/workers/asset_authoring_workers.py` | `cdmw/ui/texture_workflow/asset_authoring_panel.py`, `native/cdmw_mesh_core/` | `tests/test_asset_authoring_*.py`, asset-authoring harness scenarios | `docs/features/asset-authoring-integrations.md` |
| Supporting feature tabs | `cdmw/ui/research/`, `cdmw/ui/model_library/`, `cdmw/ui/item_icons/`, `cdmw/ui/text_search/`, `cdmw/ui/replace_assistant/` | `cdmw/core/research*.py`, `cdmw/core/model_catalogue.py`, `cdmw/core/item_icon.py`, `cdmw/services/model_library_preview.py` | matching `tests/test_*` files | feature READMEs when present |
| Utility tools | `cdmw/ui/tools/` | `cdmw/core/mod_package_retrofit.py`, `cdmw/core/mod_package.py` | `tests/test_mod_package_retrofit.py`, `tests/test_restructure_runtime_regression_smoke.py` | `cdmw/ui/tools/README.md` |
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

## Current Priority

The restructure is in app-readiness mode. Prefer fixing concrete runtime,
import, startup, and test failures over more large-file splitting. Current
evidence from crash reports showed Mesh Editor `Modify Original` failed before
builder mount when `_archive_entry_identity_key` was used as a bound method.

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
