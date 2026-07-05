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

- `docs/release-confidence-plan.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/test-matrix.md` only after the touched area is known
- `docs/project-map.md` for navigation
- `docs/project-map-detailed.md` only when package boundaries are unclear
- nearest feature README or nested `AGENTS.md`, when present

## Docs structure

- `docs/architecture.md`: stable architecture, package boundaries, ownership,
  and safety rules.
- `docs/project-map.md`: compact navigation map and owning docs/tests per area.
- `docs/project-map-detailed.md`: longer historical ownership map; update only
  when detailed package/file ownership changes or the compact map is not enough.
- `docs/test-matrix.md`: authoritative validation commands by area.
- `docs/release-confidence-plan.md`: release/readiness validation order and
  latest broad confidence evidence.
- `docs/features/`: long-lived feature/topic docs, such as archive safety,
  asset authoring, and mesh skeleton discovery notes.
- `docs/runbooks/`: short operational flows, such as startup and worker
  lifecycle.
- `docs/reference/`: cross-cutting notes and pitfalls.
- `docs/plans/active/<slug>.md`: one current implementation plan per active
  goal. Delete superseded/completed handoff plans instead of leaving them active.
- `docs/ai/PROJECT_MEMORY.md`: curated durable AI handoff notes under 200 lines.
- Feature-specific docs belong beside the owning feature when code-local, or in
  `docs/features/` when they are project-level. Do not duplicate content already
  owned elsewhere.

## Token rules

- Search before opening large files.
- Do not read build output, generated files, caches, crash reports, vendored dependencies, or local workspace data unless required.
- Use Graphify summaries for navigation only, not as proof.

## Cleanup safety

- Do not run blanket `git clean -fd`, `git clean -fdX`, or `git clean -xdf`.
- Current untracked files include restructure source, docs, and tests.
- Remove only targeted cache/build output unless the user explicitly approves broader cleanup.
- Keep `docs/plans/active/` for current plans only. Delete superseded,
  completed, one-off handoff, and new-chat bootstrap notes instead of leaving
  them active.
- Keep durable project state in `docs/ai/PROJECT_MEMORY.md` curated; do not
  append chat logs, raw command output, or stale temporary todos.
- Targeted root cleanup may remove ignored cache/temp folders such as
  `.pytest_cache/`, `.pytest-tmp*/`, and `__pycache__/`. Do not delete `.venv/`,
  `.tools/`, `build/`, `dist/`, `workspace/`, assets, or local game/corpus data
  unless explicitly requested by name.

## Validation

Use `docs/test-matrix.md`.

## Final response format

End coding tasks with:

- Files changed
- Tests run
- Tests not run and why
- Behavior preserved
- Remaining risks
