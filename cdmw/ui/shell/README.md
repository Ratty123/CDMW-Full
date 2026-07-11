# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.

Keep this package focused on application frame behavior. Feature tabs belong in
`cdmw/ui/<feature>/`; business coordination belongs in `cdmw/services/`; slow
work belongs in `cdmw/workers/`. `MainWindow` has only `QMainWindow` as a base;
shell/archive/texture/mesh behavior is supplied by owned controllers and the
compatibility provider registry.

Related docs: `docs/runbooks/startup-flow.md`, `docs/architecture.md`.
Related tests: `tests/test_shell_*.py`, architecture guards, and shell entries
in `docs/test-matrix.md`.
