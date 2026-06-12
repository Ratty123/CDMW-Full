# Test Matrix

Last reviewed: 2026-06-12

Use the project virtualenv when the active Python lacks test dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest <tests>
```

The plain `python` on this machine reported no `pytest` module during the midpoint audit.

## Smoke

```powershell
python -m pytest tests/test_runtime_dependency_smoke.py
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependency_smoke.py
.\scripts\codex_check.ps1 -Area smoke
```

## Startup, Crash Reporting, And Packaging Guards

```powershell
python -m pytest tests/test_runtime_dependency_smoke.py tests/test_crash_reporting_guards.py tests/test_pyinstaller_temp_cleanup.py
.\scripts\codex_check.ps1 -Area stability
```

## UI Responsiveness And Source Guards

```powershell
python -m pytest tests/test_ui_responsiveness_source_guards.py tests/test_mesh_edit_responsiveness_source_guards.py tests/test_texture_workflow_ui_source_guards.py
.\scripts\codex_check.ps1 -Area responsiveness
```

## Archive Browser And Archive Services

```powershell
python -m pytest tests/test_archive_browser_virtual_model.py tests/test_archive_browser_filters.py tests/test_archive_caches.py tests/test_progressive_archive_preview.py tests/test_archive_extract_progress.py
.\scripts\codex_check.ps1 -Area archive
```

## Texture Workflow

```powershell
python -m pytest tests/test_texture_workflow_ui_source_guards.py tests/test_texture_domain_profiles.py tests/test_texture_workflow_unavailable_editor.py tests/test_static_texture_replacement.py
.\scripts\codex_check.ps1 -Area texture
```

## Architecture Boundary Guards

```powershell
python -m pytest tests/test_architecture_file_sizes.py tests/test_architecture_import_boundaries.py tests/test_architecture_no_wildcard_imports.py tests/test_architecture_public_facades.py
```

## Services, Domain, And Workers

```powershell
python -m pytest tests/test_services.py tests/test_diagnostics_service.py tests/test_workers.py tests/test_shell_context.py
```

## Full Suite

```powershell
python -m pytest
.\scripts\codex_check.ps1 -Area full
```

## Notes

- Prefer targeted tests before broader suites.
- Source guard tests are expected in this codebase for large PySide wiring surfaces.
- Update this matrix when tests move, split, or stop being authoritative for a change type.
