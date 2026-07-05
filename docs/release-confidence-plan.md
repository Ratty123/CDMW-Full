# Release Confidence Plan

Last reviewed: 2026-06-21

## Goal

Prove the restructured app still imports, starts, packages, and keeps core user
workflows working. Do not start more large source splits unless validation shows
one is required.

## Read First

1. `AGENTS.md`
2. `docs/README.md`
3. `docs/architecture.md`
4. `docs/project-map.md`
5. `docs/test-matrix.md` when choosing validation
6. `docs/project-map-detailed.md` only when package boundaries are unclear

## Current Focus

- Keep `cdmw_app.py` and `cdmw/ui/main_window.py` thin.
- Preserve compatibility facades and public imports.
- Fix concrete import, startup, source-guard, packaging, or workflow failures.
- Prefer focused behavior fixes over new architecture cleanup.
- Use `%TEMP%` for pytest `--basetemp` if `.pytest-tmp` is locked.

## Validation Order

1. Compile/import smoke over touched restructure surfaces and public facades.
2. Architecture guards:
   `tests/test_architecture_file_sizes.py`,
   `tests/test_architecture_public_facades.py`,
   `tests/test_architecture_import_boundaries.py`,
   `tests/test_architecture_no_wildcard_imports.py`.
3. Runtime/startup smoke from `docs/test-matrix.md`.
4. Focused archive, static replacement, texture, shell, worker, and packaging
   groups from `docs/test-matrix.md`.
5. Full suite only after focused groups are green or remaining failures are
   understood as external-data or environment problems.

## Done

- Relevant focused tests pass.
- Runtime/startup smoke passes.
- Packaging smoke passes or the exact blocker is documented.
- Remaining failures, if any, are classified with owner, command, and reason.

## Latest Validation

2026-07-05:

- Mesh area gate: `.\scripts\codex_check.ps1 -Area mesh` passed with
  647 passed / 4 deselected.
- Release onefile package built, native helpers rebuilt, 483 embedded archive
  members validated, and packaged startup smoke passed with
  `QT_QPA_PLATFORM=offscreen` and `CDMW_GUI_STARTUP_SMOKE=1`.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  SHA256 `E65ED0336F132D1E992EADAAB3495EB1283B215AA08917A5AAC32DA7A8A9F58F`.

2026-06-21:

- Architecture guards: 13 passed.
- Startup/runtime stability: 55 passed, 5 subtests passed.
- Responsiveness/source guards: 49 passed.
- Archive/static replacement matrix: 342 passed.
- Texture workflow matrix: 253 passed.
- Supporting feature tabs: 81 passed.
- Services/domain/workers: 37 passed.
- Full pytest suite: 2846 passed, 6 skipped, 68 subtests passed.
- Fast onedir package built and startup-smoked.
- Release onefile package built, native helpers rebuilt, 482 embedded archive
  members validated, and startup-smoked.
- Release artifact:
  `dist/CrimsonDesertModWorkbench-0.10.0-alpha.2-windows-portable.exe`
  SHA256 `37B9E8455C71A1C5A744E82E120ED17556B354C3A2FB521FDA376CF3BB3EBC0A`.
