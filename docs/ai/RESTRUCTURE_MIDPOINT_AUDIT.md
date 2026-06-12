# Restructure Midpoint Audit

## Current state

The repository is in a partial restructure state with many pre-existing modified files and many new untracked architecture modules. `cdmw_app.py` is now a thin executable wrapper, and `cdmw/ui/main_window.py` is now a thin public facade. The main GUI shell has moved under `cdmw/ui/shell/`, while several feature packages, services, domain modules, and workers exist.

Baseline validation:

- `python -m pytest tests/test_runtime_dependency_smoke.py` failed because the active Python 3.13 environment has no `pytest` module.
- `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py` passed: 8 tests.

Graphify status:

- `graphify` was not initially on PATH.
- `graphifyy` was installed into the project `.venv`, not globally.
- `.\.venv\Scripts\graphify.exe .` failed because no LLM API key was configured for docs/images.
- `.\.venv\Scripts\graphify.exe update . --no-cluster` succeeded and wrote `graphify-out/graph.json`.

## Completed phases

- App entry point extraction: `cdmw_app.py` delegates to `cdmw.app.bootstrap.main`.
- GUI shell extraction: `cdmw/ui/main_window.py` re-exports shell-owned `MainWindow` and `run_gui`.
- Shell package creation: `cdmw/ui/shell/` contains app window, runtime state, startup, settings, diagnostics, tabs, menus, toolbar, and controller modules.
- Feature package creation for archive browser, texture workflow, mesh editor, item icons, model library, research, and text search.
- Service, domain, and worker package creation under `cdmw/services/`, `cdmw/domain/`, and `cdmw/workers/`.
- Public facade tests exist for migrated entry points and legacy feature imports.
- Architecture guard tests exist for file sizes, import boundaries, wildcard imports, and public facades.

## Partially completed phases

- Archive browser split: many modules exist, but `cdmw/ui/archive_browser/` has over 100 Python files and still contains very large coordination surfaces.
- Static replacement split: helper modules exist, but `cdmw/ui/archive_browser/static_replacement_dialog.py` remains a high-coupling UI coordinator.
- Research split: `cdmw/ui/research/tab.py` exists but remains large and core-coupled.
- Model library, item icons, text search, and texture workflow splits: package skeletons exist, but exact boundary completeness remains TBD.
- Worker/service/domain boundaries: improved, but Graphify/source search show worker-to-UI and domain-to-modding dependencies.
- Source guard migration: many guards now include new files, but some still read old facades or broad legacy paths by design.

## Not started phases

- Deep decomposition of `cdmw/core/archive.py`, `cdmw/core/archive_modding.py`, and `cdmw/modding/material_replacer.py`.
- Broad shared model split from `cdmw/models.py`.
- Full Graphify clustered report with doc/image semantic extraction.
- Source-code refactor tasks for this run; intentionally not started.

## Broken imports or wrappers

- No broken public compatibility import was confirmed during this audit.
- `tests/test_architecture_public_facades.py` explicitly verifies public imports from `cdmw.ui.main_window`, `cdmw.ui.archive_browser_model`, `cdmw.ui.item_icons_tab`, `cdmw.ui.mesh_editor_tab`, `cdmw.ui.model_library_tab`, `cdmw.ui.research_tab`, and `cdmw.ui.text_search_tab`.
- Suspicious but currently intentional: `cdmw/app/gui.py` imports `run_gui` from `cdmw.ui.main_window`, and `tests/test_crash_reporting_guards.py` expects that facade path.
- Suspicious but currently intentional: `cdmw/ui/archive_browser_model.py` uses a wildcard re-export for compatibility.

## Test status

- Passed: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py`
- Failed due environment: `python -m pytest tests/test_runtime_dependency_smoke.py` because `pytest` is not installed for the active Python.
- Not run in this docs-only checkpoint: full suite and broad architecture guard suite.

## Graphify-informed risks

- `cdmw_app.py` is not central in the code-only graph.
- `cdmw/ui/main_window.py` is not central in the code-only graph.
- New central nodes include `cdmw/ui/shell/app_window.py`, especially `MainWindow`.
- Existing central hotspots remain `cdmw/models.py`, `cdmw/core/archive.py`, `cdmw/core/archive_modding.py`, `cdmw/modding/material_replacer.py`, `cdmw/ui/research/tab.py`, and `cdmw/ui/archive_browser/static_replacement_dialog.py`.
- Boundary leaks to investigate: workers importing `cdmw.ui.archive_browser.filters`, and domain texture policy importing `cdmw.modding.material_replacer`.

## Safest next three tasks

1. Move archive filter/index helpers used by workers out of `cdmw/ui/archive_browser/filters.py` only if tests confirm the pure helper boundary; run archive filter and worker tests.
2. Extract one pure helper slice from `cdmw/ui/archive_browser/static_replacement_dialog.py` to an existing helper/domain/service module; run static replacement and architecture file-size tests.
3. Update one source guard at a time to point at the current owner module after confirming the protected behavior moved.

## Do not redo

- Do not rebuild the app bootstrap from scratch.
- Do not put startup logic back into `cdmw_app.py`.
- Do not put shell or feature logic back into `cdmw/ui/main_window.py`.
- Do not remove compatibility wrappers for public imports.
- Do not repeat broad archive-browser package creation; continue from the current split.
- Do not commit generated `graphify-out/` output.
