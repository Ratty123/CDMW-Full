# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.
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

Related docs: `docs/runbooks/startup-flow.md`, `docs/architecture.md`.
Related tests: `tests/test_shell_*.py`, architecture guards, and shell entries
in `docs/test-matrix.md`.
