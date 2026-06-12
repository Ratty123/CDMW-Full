# Project Map

Last reviewed: 2026-06-12

## Entry Points

- `cdmw_app.py`: thin executable wrapper that delegates to `cdmw.app.bootstrap.main`.
- `cdmw/app/bootstrap.py`: current application bootstrap and top-level startup path.
- `cdmw/app/gui.py`: GUI launch bridge; still imports `run_gui` from the public `cdmw.ui.main_window` facade.
- `build_gui.py`, `build.bat`, `build_pyside6_app.ps1`, and `CrimsonDesertModWorkbench.spec`: packaging/build entry points.

## Current App Bootstrap Location

- Primary bootstrap code now lives under `cdmw/app/`.
- `cdmw_app.py` should remain a minimal compatibility executable.
- Do not add startup, crash reporting, PyInstaller, or single-instance logic to `cdmw_app.py`.

## Current GUI Shell Location

- Shell window and application wiring live under `cdmw/ui/shell/`.
- Public compatibility facade: `cdmw/ui/main_window.py`.
- Important shell modules include:
  - `cdmw/ui/shell/app_window.py`
  - `cdmw/ui/shell/run_gui.py`
  - `cdmw/ui/shell/signal_wiring.py`
  - `cdmw/ui/shell/tool_tabs.py`
  - `cdmw/ui/shell/tab_registry.py`
  - `cdmw/ui/shell/startup_controller.py`
  - `cdmw/ui/shell/responsiveness_controller.py`

## Current Feature Packages

- `cdmw/ui/archive_browser/`: archive browser UI, previews, filters, patching, mesh workflows, attachment tools, and static replacement UI. This package is still very broad.
- `cdmw/ui/texture_workflow/`: texture workflow panels, controller, state, profiles UI, and editor handoff. Has a local `README.md`.
- `cdmw/ui/mesh_editor/`: mesh editor tab, controller, session, builder host, shell bridge, and empty state. Has a local `README.md`.
- `cdmw/ui/item_icons/`: item icon tab support. Exact split status: TBD.
- `cdmw/ui/model_library/`: model library tab support. Exact split status: TBD.
- `cdmw/ui/research/`: research tab support; `cdmw/ui/research/tab.py` remains large.
- `cdmw/ui/text_search/`: text search tab support. Exact split status: TBD.

## Legacy Compatibility Wrappers

These public imports are intentionally preserved while internals move:

- `cdmw/ui/main_window.py` re-exports `MainWindow`, `mesh_import_mode_availability`, and `run_gui`.
- `cdmw/ui/archive_browser_model.py` re-exports `cdmw.ui.archive_browser.model`.
- `cdmw/ui/item_icons_tab.py` re-exports `ItemIconLibraryTab`.
- `cdmw/ui/mesh_editor_tab.py` re-exports `MeshEditorTab` and `MeshEditorSessionRequest`.
- `cdmw/ui/model_library_tab.py` re-exports `ModelLibraryTab` plus legacy helper names.
- `cdmw/ui/research_tab.py` re-exports `ResearchTab`.
- `cdmw/ui/text_search_tab.py` re-exports `TextSearchTab`.

## Services, Domain, And Workers Status

- `cdmw/services/`: service container plus archive, cache, diagnostics, filesystem, mesh, package, settings, and texture workflow services.
- `cdmw/domain/`: pure-ish rules under `archives`, `mesh`, `packages`, and `textures`.
- `cdmw/workers/`: Qt worker runner, archive scan/preview/filter workers, package workers, texture workers, D3D11 package workers, and shared results/protocol helpers.
- Boundary status: improving, but archive browser UI still appears to own too much workflow coordination.

## Highest-Risk Files

- Graphify code-only midpoint hotspots:
  - `cdmw/models.py`
  - `cdmw/core/archive.py`
  - `cdmw/core/archive_modding.py`
  - `cdmw/modding/material_replacer.py`
  - `cdmw/ui/shell/app_window.py`
  - `cdmw/ui/research/tab.py`
  - `cdmw/ui/archive_browser/static_replacement_dialog.py`
- `cdmw/core/archive_modding.py`
- `cdmw/ui/archive_browser/static_replacement_dialog.py`
- `cdmw/core/archive.py`
- `cdmw/modding/material_replacer.py`
- `cdmw/ui/texture_editor_tab.py`
- `cdmw/ui/archive_browser/hkx_editor_dialog.py`
- `cdmw/core/pipeline.py`
- `cdmw/core/final_package_preview.py`
- `cdmw/ui/research/tab.py`
- `cdmw/rendering/native_preview_package.py`

## Where Not To Edit

- Do not add logic to `cdmw_app.py`.
- Do not add feature logic to `cdmw/ui/main_window.py`.
- Do not mutate archives from UI code.
- Do not edit generated output, caches, crash reports, local game payloads, or `graphify-out/`.

## Unknowns

- Whether every compatibility wrapper has exhaustive public parity: TBD by targeted tests.
- Whether all source guards point to the best new module locations: partially unknown; many still include old facade files by design.
- Whether Graphify detects all dynamic PySide signal/runtime wiring: TBD; source and tests remain authoritative.
- Graphify midpoint output is code-only and unclustered because no LLM API key was configured for docs/images.
