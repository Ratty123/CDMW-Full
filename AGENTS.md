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
- After each coherent, completed, and sufficiently verified change, commit only
  the task-owned files locally with a descriptive message. Never push unless
  explicitly asked. Stage explicit paths only; never use `git add -A`.
- Never include unrelated or pre-existing user changes in an automatic commit.
  If an owned edit cannot be isolated safely from user changes in the same
  file, leave it uncommitted and report why.

## Navigation

Do not preload the repository documentation set. Start with the cheapest source
that can identify the owning area, then widen only when evidence requires it:

- Search `docs/project-map.md` and read only the relevant section for ownership
  and nearby tests/docs.
- Read the nearest feature README or nested `AGENTS.md`, when present.
- Search `docs/architecture.md` and read only the relevant section when an
  ownership boundary, dependency rule, or stable contract is unclear.
- Search `docs/test-matrix.md` only after the touched area is known and read only
  that area's validation commands.
- Read `docs/release-confidence-plan.md` only for release/readiness work, broad
  QA ordering, or historical confidence evidence.
- Read `docs/README.md` only when documentation placement or ownership is part
  of the task.
- Use `docs/project-map-detailed.md` only when the compact map and targeted code
  searches cannot resolve package boundaries.
- Read targeted sections of `docs/ai/PROJECT_MEMORY.md` only for cross-session
  continuation, durable decisions/pitfalls, or a required near-handoff update.
  Do not duplicate context already supplied by injected Codex memory.

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
- Keep status, diff, search, build, and test output scoped and bounded. Use
  counts, `--stat`/`--name-only`, exact pathspecs, quiet modes, and targeted
  line ranges before requesting full output.
- Do not combine several potentially verbose commands into one result. If any
  output is truncated, rerun the smallest command that exposes the decisive
  evidence; never treat truncated output as a passing check.
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

- An escaped runtime regression is not closed until a focused reproducer catches
  the pre-fix behavior, passes with the repair, and is registered in the owning
  `scripts/codex_check.ps1` gate.
- Do not use source-string assertions as the sole proof for executable UI
  wiring. Exercise the smallest real headless construction or behavior path.
- Changes to the static-replacement prompt shell, state callbacks, preview
  controls, or presentation wiring must run the offscreen Import Mesh and
  Modify Original Builder construction gate documented under **Mesh Editor
  Suite**.

## Workflow skills

- Use `$cdmw-validate-change` to select the smallest sufficient validation for
  code changes.
- Use `$cdmw-async-ui-work` when changing long-running UI, worker, thread,
  subprocess, cancellation, stale-result, or shutdown behavior.
- Use `$cdmw-safe-archive-mutation` for archive write, patch, backup, rollback,
  or restore paths.
- Use `$cdmw-verify-mesh-editor` for Mesh Editor validation. Visible and
  real-game gates require explicit user authorization.

## Final response format

End coding tasks with:

- Files changed
- Tests run
- Tests not run and why
- Behavior preserved
- Remaining risks
