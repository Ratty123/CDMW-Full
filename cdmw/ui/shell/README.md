# UI Shell

Owns the main window shell, workspace layout, tab registry, actions, menus,
toolbar, status bar, settings/theme/language wiring, startup/close controllers,
activation handling, diagnostics, and app-level dialogs.

Keep this package focused on application frame behavior. Feature tabs belong in
`cdmw/ui/<feature>/`; business coordination belongs in `cdmw/services/`; slow
work belongs in `cdmw/workers/`. `app_window.py` is still a legacy allowlisted
implementation file while shell responsibilities continue to shrink.

Related docs: `docs/startup_flow.md`, `docs/architecture.md`.
Related tests: `tests/test_shell_*.py`, architecture guards, and shell entries
in `docs/test-matrix.md`.
