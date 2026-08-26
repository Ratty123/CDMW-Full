# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.

`compact/` owns the restart-selected Compact Workspace presentation around the
same authoritative tool widgets. Classic remains the default. Compact mode
hides the existing tab bars, routes its rail through the shared activation
path, reuses the existing actions and status widgets, and never constructs a
second tool/controller/worker tree. Its independent theme and category state
are documented in `docs/features/compact-workspace.md`.
`archive_backend_client.py` owns the resident, bounded `QProcess` protocol and
nonblocking shutdown lifecycle for the independent full archive worker;
`archive_backend_resources.py` owns packaged and development worker discovery.
The shell defaults to v2, validates protocol/native ABI/index compatibility
before dispatch, and never silently falls back. A catalogue-publication failure
offers retry, cancel, or a legacy scan for the current process only. Explicit
session fallback cancels tracked requests, restores the legacy tree model, and
requests nonblocking worker shutdown without persisting a setting.

Keep this package focused on application frame behavior. Feature tabs belong in
`cdmw/ui/<feature>/`; business coordination belongs in `cdmw/services/`; slow
work belongs in `cdmw/workers/`. `MainWindow` has only `QMainWindow` as a base;
shell/archive/texture/mesh behavior is supplied by owned controllers and the
compatibility provider registry.

Settings font sizes are exact user preferences; responsive screen scaling may
compact spacing and control metrics, but it does not rewrite the chosen UI or
list font size. The seven-page Settings navigation is a top-aligned,
content-sized rail whose width follows its translated labels instead of taking
a fixed sidebar width and full-window height.

Related tests: `tests/test_shell_*.py`, architecture guards, and shell entries
under `tests/`.
