# Project Instructions for Codex

## Core rules

- Do not restart the restructure.
- Continue from the current repository state.
- Keep `cdmw_app.py` thin.
- Keep `cdmw/ui/main_window.py` thin.
- Do not add feature logic to `cdmw/ui/main_window.py`.
- Do not add startup logic to `cdmw_app.py`.
- Preserve public imports with compatibility wrappers when moving modules.
- Put UI shell behavior under `cdmw/ui/shell/`.
- Put feature UI under `cdmw/ui/<feature>/`.
- Put business operations under `cdmw/services/`.
- Put pure rules under `cdmw/domain/`.
- Put long-running work under `cdmw/workers/`.
- Do not run slow work on the UI thread.
- Do not mutate archives directly from UI code.
- Add or update tests with behavior changes.
- Do not commit local game assets, extracted archives, DDS payloads, build output, crash reports, restore points, or `graphify-out/`.
- Do not commit unless asked. Stage explicit files only; never use `git add -A`.

## Navigation

Before broad exploration, read:

- `docs/ai/PROJECT_MAP.md`
- `docs/ai/TEST_MATRIX.md`
- nearest feature README or nested `AGENTS.md`, when present

## Token rules

- Search before opening large files.
- Do not read build output, generated files, caches, crash reports, vendored dependencies, or local workspace data unless required.
- Use Graphify summaries for navigation only, not as proof.

## Validation

Use `docs/ai/TEST_MATRIX.md`.

## Final response format

End coding tasks with:

- Files changed
- Tests run
- Tests not run and why
- Behavior preserved
- Remaining risks
