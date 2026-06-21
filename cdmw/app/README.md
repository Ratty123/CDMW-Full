# App Startup

Owns command-line parsing, process activation, single-instance handling,
PyInstaller runtime cleanup, splash startup, bootstrap reports, and CLI/GUI
dispatch. `cdmw_app.py` stays a thin executable wrapper around
`cdmw.app.bootstrap.main`.

Keep startup and process-lifetime behavior here. Do not import feature tabs or
feature workflow internals from bootstrap code. GUI startup crosses into the UI
through `cdmw/app/gui.py` and the public `cdmw.ui.main_window` facade.

Related docs: `docs/startup_flow.md`, `docs/release-confidence-plan.md`.
Related tests: `tests/test_shell_app_startup.py`,
`tests/test_runtime_dependency_smoke.py`, and startup entries in
`docs/test-matrix.md`.
