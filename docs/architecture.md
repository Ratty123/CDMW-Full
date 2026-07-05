# Architecture

Crimson Desert Mod Workbench is moving from a monolithic PySide window toward
small app, shell, feature, service, domain, and worker packages. Public imports
stay stable while implementation moves behind compatibility wrappers.

## Package Map

- `cdmw_app.py`: tiny command entrypoint.
- `cdmw/app/`: argument parsing, startup routing, single-instance handling,
  activation, splash startup, PyInstaller runtime cleanup, and bootstrap reports.
- `cdmw/ui/main_window.py`: compatibility facade for `MainWindow`, `run_gui`,
  and legacy public helpers.
- `cdmw/ui/shell/`: current GUI shell implementation, app context/state, tab
  registry, action/menu/status/theme/icon/activation ownership modules, and
  close/diagnostics helpers. `app_window.py` is still a legacy allowlisted
  implementation file while feature code is extracted.
- `cdmw/ui/<feature>/`: feature UI packages such as archive browser, texture
  workflow, mesh editor, model library, item icons, research, and text search.
- `cdmw/ui/tools/`: utility tools that do not belong to a feature workspace,
  currently Retrofit/Repackage Mods.
- `cdmw/domain/`: pure rules and policies for archive safety/selection/filter
  state, texture profiles/rules/semantics/policy/plans/validation, mesh session
  validation, and package manifests/preflight.
- `cdmw/services/`: business coordination boundaries with no PySide widget
  imports.
- `cdmw/workers/`: shared worker protocols, result types, cancellation, and
  worker extraction points.
- `cdmw/core/`, `cdmw/modding/`, `cdmw/rendering/`: low-level archive, texture,
  rendering, import/export, and external tool logic.
- `native/cdmw_mesh_core/`: bundled C++ mesh-edit core for resident Mesh Editor
  sessions. Python service/modding boundaries dispatch commands and report
  explicit unavailable/error states instead of silently falling back when native
  editing is required.

## Layer Rules

- Entry code imports `cdmw.app.bootstrap`, not feature tabs or core internals.
- App bootstrap does not import feature tab internals.
- UI shell can import PySide, feature tabs, services, and shared widgets.
- Feature UI packages do not import unrelated feature tabs.
- Services may import domain/core/modding/rendering but not PySide widgets.
- Domain modules must stay pure Python and must not import PySide.
- Workers must not mutate UI directly from background threads.
- UI must not directly own destructive archive mutation policy.

## Feature Ownership

Archive browser model code lives in `cdmw/ui/archive_browser/model.py`; the old
`cdmw.ui.archive_browser_model` import path is a wrapper. Texture Workflow has a
package home for setup, rules, profiles, progress, compare, preview, package, and
breadcrumb panels. Mesh Editor, Model Library, Icon Creator, Research, Text
Search, and Tools now have package homes with compatibility wrappers at old
module paths where needed.

## Services

`ServiceContainer` creates bounded service objects for archives, archive
mutation, asset authoring, texture workflow, mesh, package, diagnostics,
settings, cache, and filesystem coordination. Asset authoring discovery,
Material Maker command handoff, review-only texture-set ingest, and source
scene import reports stay in the asset authoring service. Mesh health preflight
reports, UV/tangent authoring reports, and optional OpenImageIO source image
handoff commands stay there too until cleanup/texture conversion moves into worker-backed commands. Target
compatibility stays unmapped until routed to a known Crimson asset, and DDS
rebuild authority stays with the existing CDMW/DirectXTex texture paths. Archive
mutation service methods are deliberately unwired until confirmation, preflight,
backup, apply, and restore flows are moved through it safely.

`cdmw/services/workspace_layout.py` owns app-managed local workspace paths.
Portable installs keep the config beside the executable, while generated local
folders live under `workspace/`: original DDS files, staging, outputs, extracts,
Texture Editor projects, libraries, research, sessions, cache, logs, and tools. Legacy root-level default
folders are migrated conservatively when settings are created.

## Workers

Shared worker contracts live under `cdmw/workers/`. Use `WorkerSuccess`,
`WorkerFailure`, and `CancellationToken` for new long-running work. Asset
authoring workers keep Material Maker CLI export and optional OpenImageIO
metadata/convert/diff subprocess execution out of UI code. Worker-heavy tabs
expose `request_shutdown()` and `iter_shutdown_workers()`.

## Testing

Architecture tests cover tiny public facades, target package map presence, import
boundaries, public wrapper imports, and wildcard-import prevention for refactored
packages. Existing source guards are location-aware and currently point at
`cdmw/ui/shell/app_window.py` for behavior not yet extracted.

## Performance Rules

Large archive listing stays virtualized. Filtering and previews stay debounced.
Icon/thumbnail work must prioritize visible rows and run in background workers.
Archive scan, conversion, rebuild, import/export, hashing, recursive IO, and
package build work must stay off the UI thread.
Archive cache pruning keeps the current package root's cache artifacts and only
evicts older cache files or cache directories for other package roots.

## Archive Mutation Safety

Archive mutation remains explicit, confirmed, backed up, and recoverable. Browse,
preview, extract, scan, and package build paths must not silently rewrite game
archives.

## Adding A New Tab

Create `cdmw/ui/<feature>/tab.py`, add state/controller/worker modules when
needed, register through shell tab wiring, and keep old imports as wrappers
during migration.

## Adding Long-Running Work

Put coordination in a service, execution in `cdmw/workers/`, cancellation through
`CancellationToken`, and UI updates only through Qt signals on the UI thread.

## Adding Destructive Archive Operations

Route through `ArchiveMutationService`: prepare command, validate plan, show UI
confirmation, create backup, apply patch, and expose restore.
