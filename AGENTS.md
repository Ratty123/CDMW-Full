# Project Instructions for Codex

Global `~/.codex/AGENTS.md` applies in full. This file adds project facts and
overrides the global where they conflict. It does not restate global rules.

## Architecture rules

- Do not restart the restructure. Continue from the current repository state.
- Keep `cdmw_app.py` thin: no startup logic.
- Keep `cdmw/ui/main_window.py` thin: no feature logic.
- UI shell behavior goes in `cdmw/ui/shell/`, feature UI in
  `cdmw/ui/<feature>/`, business operations in `cdmw/services/`, pure rules in
  `cdmw/domain/`, and long-running work in `cdmw/workers/`.
- Preserve public imports with compatibility wrappers when moving modules.
- Never run slow work on the UI thread.
- Never mutate archives directly from UI code.
- Add or update tests with behavior changes.
- Do not commit local game assets, extracted archives, DDS payloads, build
  output, crash reports, restore points, or `graphify-out/`.

## Large local artifacts

Generated evidence in this repo runs to megabytes. Never read one whole; size it
first, then bound the read or query it with `rg`/`jq`. The families that bite:

- `workspace/mesh-editor-visual-audit/**/dotnet-capture.json` and
  `dotnet-batch-report.json`, routinely 3-5 MB each.
- `*-parity.json` material authority dumps, several hundred KB.
- `.codex/restore-points/**`, which contains multi-MB historical copies of
  source files, including a `main_window.py` far larger than the live one. Never
  mistake a restore-point copy for the file you are editing.
- `docs/project-map-detailed.md` and `docs/release-confidence-plan.md`; search
  these and read the matching section only.

`rg` honors `.gitignore`, so ignored trees stay out of searches. That protection
does not extend to a direct read.

## Blast radius in this repository

This codebase resolves most cross-module wiring at runtime, so a broken consumer
fails when a user clicks, not when a test imports. There are roughly 9,100
`getattr`/`hasattr` sites and 700 `objectName`/`findChild` sites under `cdmw/`.
A green focused test says nothing about the callers you did not enumerate.

Apply the global change safety loop, and treat these as consumers that static
checks will not find for you:

- Qt signal and slot names, `connect` targets, and keyword arguments.
- `objectName` strings, `findChild` lookups, and widget lookup keys.
- `getattr`/`hasattr` probes against the symbol you are renaming or removing.
- Settings keys, JSON/manifest field names, and evidence-report field names.
- Compatibility re-export shims left behind by earlier module moves.

Search each of these by literal string, not only by symbol, before and after the
edit. When a rename is unavoidable, update every hit in the same change.

## Definition of done

A change is done when all of these hold, and not before:

- The stated behavior works, and the diff contains nothing the task did not
  require.
- Every consumer from the change safety loop is updated, verified unaffected, or
  reported.
- The pre-existing tests that covered the touched contract pass, alongside any
  new test.
- An escaped runtime regression has a focused reproducer that fails before the
  fix, passes after it, and is registered in the owning `scripts/codex_check.ps1`
  gate.
- A user-visible change carries its `CHANGELOG.md` entry in the same commit.

## Changelog and versioning

The global changelog rules apply. Project specifics:

- `CHANGELOG.md` uses `Added` / `Changed` / `Fixed` / `Docs`, newest first
  within a section, one paragraph per entry. Entries name the affected surface
  by its in-app label (`Archive Browser`, `Mesh Editor`, `Edit Mesh`,
  `Item Finder`, `Material Authority`), state the root cause when it explains
  the symptom, and carry measured numbers for any performance claim.
- Everything unreleased goes under `## [Unreleased]`. The version sections below
  it are shipped history: never append to one, even when the work extends a
  feature it introduced.
- Ask before every version bump. The version is stated in four places and all of
  them move together: `APP_VERSION` in `cdmw/constants.py`, `README.md`,
  `SECURITY.md`, and the tuple in `tests/test_build_metadata.py`. Find them with
  `rg` on the outgoing version string, because packaging metadata and workspace
  logs also carry it and only the first four are sources of truth.
- Mesh Editor, Archive Browser, and preview work usually touches user-visible
  behavior even when the commit reads as internal. A change that alters what a
  preview renders, what a control reports, or how long an open takes belongs in
  the changelog.

## Navigation

Do not preload the documentation set. Start with the cheapest source that can
identify the owning area and widen only when evidence requires it:

- Search `docs/project-map.md` and read only the relevant section for ownership
  and nearby tests and docs.
- Read the nearest feature README or nested `AGENTS.md` when one exists.
- Search `docs/architecture.md` and read only the relevant section when an
  ownership boundary, dependency rule, or stable contract is unclear.
- Search `docs/test-matrix.md` only after the touched area is known, and read
  only that area's validation commands.
- Read `docs/release-confidence-plan.md` only for release or readiness work,
  broad QA ordering, or historical confidence evidence.
- Read `docs/README.md` only when documentation placement is part of the task.
- Use `docs/project-map-detailed.md` only when the compact map and targeted code
  searches cannot resolve package boundaries.
- Read targeted sections of `docs/ai/PROJECT_MEMORY.md` only for cross-session
  continuation or a required near-handoff update.

`docs/project-map.md` owns the documentation layout table. Place feature docs
beside the owning feature when code-local, or in `docs/features/` when they are
project-level, and do not duplicate content owned elsewhere.

## Validation

`docs/test-matrix.md` is authoritative for commands. Use the global validation
budget to decide how far up the tiers to go, with these project specifics:

- Tier 3 in this repo is `scripts/codex_check.ps1 -Area <area>`. Valid areas are
  `smoke`, `stability`, `responsiveness`, `archive`, `texture`, `mesh`,
  `mesh-unit`, and `full`.
- Run checks with `.\.venv\Scripts\python.exe` from the repository root, and put
  pytest `--basetemp` under `$env:TEMP`. Never write test output into the repo.
- A full `python -m pytest` run can end through a native crash. Confirm the
  process exit path and the collected-test count, not just the printed summary,
  before treating a broad run as evidence.
- Source-string assertions are never sole proof for executable UI wiring.
  Exercise the smallest real headless construction or behavior path instead.
- Changes to the static-replacement prompt shell, state callbacks, preview
  controls, or presentation wiring must run the offscreen Import Mesh and
  Modify Original Builder construction gate under **Mesh Editor Suite**.
- `mesh` and any visual or real-game gate require explicit user authorization.
  A game path already being present is not authorization.

## Cleanup safety

- Never run blanket `git clean -fd`, `git clean -fdX`, or `git clean -xdf`.
  Untracked files here include restructure source, docs, and tests.
- Targeted root cleanup may remove ignored cache and temp folders such as
  `.pytest_cache/`, `.pytest-tmp*/`, and `__pycache__/`. Never delete `.venv/`,
  `.tools/`, `build/`, `dist/`, `workspace/`, assets, or local game data unless
  the user names them.
- Keep `docs/plans/active/` for current plans only. Delete superseded,
  completed, and one-off handoff notes rather than leaving them active.

## Workflow skills

- `$cdmw-validate-change` selects the smallest sufficient validation.
- `$cdmw-async-ui-work` covers long-running UI, worker, thread, subprocess,
  cancellation, stale-result, and shutdown behavior.
- `$cdmw-safe-archive-mutation` covers archive write, patch, backup, rollback,
  and restore paths.
- `$cdmw-verify-mesh-editor` covers Mesh Editor validation.

## Final response format

End coding tasks with:

- Files changed
- Consumers checked, and any left unverified
- Tests run
- Tests not run and why
- Remaining risks
- Out-of-scope problems noticed, listed and not fixed
