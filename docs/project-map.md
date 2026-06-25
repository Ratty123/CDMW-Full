# Project Map

Last reviewed: 2026-06-21

Use this file for navigation. Use `docs/project-map-detailed.md` only when
you need historical ownership detail.

## Read Order

1. `AGENTS.md`
2. `docs/release-confidence-plan.md`
3. `docs/architecture.md`
4. `docs/test-matrix.md`
5. This map
6. `docs/project-map-detailed.md` only when package boundaries are unclear

## Cleanup Rule

Do not run blanket `git clean -fd`, `git clean -fdX`, or `git clean -xdf` in
this repo right now. Current untracked files include restructure source, docs,
and tests. Use targeted deletion for cache/build output only.

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
| Startup and GUI launch | `cdmw/app/`, `cdmw/ui/shell/` | `cdmw_app.py`, `cdmw/ui/main_window.py` | `tests/test_shell_*.py`, `tests/test_runtime_dependency_smoke.py` | `docs/startup_flow.md` |
| Archive browser and preview | `cdmw/ui/archive_browser/` | `cdmw/core/archive*.py`, `cdmw/workers/archive_*.py` | `tests/test_archive_*.py`, `tests/test_archive_browser_*.py` | `docs/archive_safety_model.md` |
| Prefab JSON import | `cdmw/core/prefab_json.py`, `cdmw/core/prefab_corpus.py`, `cdmw/ui/archive_browser/prefab_json_actions.py` | `cdmw/core/crimson_formats.py`, `cdmw/core/archive_attachment_patches.py`, `cdmw/ui/archive_browser/actions.py`, `tools/report_prefab_json_import_corpus.py` | `tests/test_prefab_json_import.py`, `tests/test_prefab_corpus.py`, `tests/test_prefab_corpus_tool.py`, `tests/test_prefab_json_actions_source.py`, `tests/test_crimson_formats.py` | `docs/plans/active/prefab-json-import.md` |
| Mesh Editor and replacement builder | `cdmw/ui/mesh_editor/`, `cdmw/ui/archive_browser/static_replacement_*.py`, `cdmw/ui/archive_browser/mesh_launch_flow.py` | `cdmw/modding/static_mesh_*.py`, dormant `cdmw/modding/full_import_model_replacement.py`, `cdmw/rendering/native_preview_*.py` | `tests/test_mesh_*.py`, `tests/test_static_replacement_*.py`, `tests/test_full_import_model_replacement.py` | `docs/architecture.md`, `docs/plans/active/full-import-model-replacement.md` |
| Texture workflow and editor | `cdmw/ui/texture_workflow/` | `cdmw/core/texture_pipeline/`, `cdmw/domain/textures/` | `tests/test_texture_*.py`, `tests/test_static_texture_replacement.py` | `docs/architecture.md` |
| Supporting feature tabs | `cdmw/ui/research/`, `cdmw/ui/model_library/`, `cdmw/ui/item_icons/`, `cdmw/ui/text_search/`, `cdmw/ui/replace_assistant/` | `cdmw/core/research*.py`, `cdmw/core/model_catalogue.py`, `cdmw/core/item_icon.py`, `cdmw/services/model_library_preview.py` | matching `tests/test_*` files | feature READMEs when present |
| Utility tools | `cdmw/ui/tools/` | `cdmw/core/mod_package_retrofit.py`, `cdmw/core/mod_package.py` | `tests/test_mod_package_retrofit.py`, `tests/test_restructure_runtime_regression_smoke.py` | `cdmw/ui/tools/README.md` |
| Services/domain/workers | `cdmw/services/`, `cdmw/domain/`, `cdmw/workers/` | feature callers | `tests/test_services.py`, `tests/test_workers.py`, architecture tests | `docs/worker_lifecycle.md` |
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

## Where Not To Edit

- Generated output, caches, build/dist output, crash reports, local game payloads,
  restore points, and `graphify-out/`.
- `.venv/`, `.tools/`, `workspace/`, legacy root workspace folders such as
  `input_dds/`, `dds_final/`, `archive_cache/`, and `app_restore_points/`
  unless the user explicitly asks for broader local cleanup.
