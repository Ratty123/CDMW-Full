---
name: cdmw-validate-change
description: Select and report the smallest correct validation for Crimson Desert Mod Workbench changes. Use when choosing verification commands, preparing a handoff, reviewing a validation claim, or mapping task-owned paths to docs/test-matrix.md. Do not auto-trigger for pure navigation or when another CDMW skill fully owns the workflow unless validation selection is also needed. Use the project virtualenv and system temp, and never start visual, real-game, release, or publishing gates without explicit scope.
---

# Validate a CDMW change

## Establish scope

1. Read `AGENTS.md` and inspect `git status --short`.
2. Separate files owned by the current task from unrelated dirty-tree changes.
   Never broaden validation merely because unrelated files are modified.
3. Map task-owned paths through `docs/project-map.md`.
4. Search the relevant heading in `docs/test-matrix.md`; do not load unrelated
   validation sections.

## Choose the smallest sufficient checks

Run checks in this order and stop when the requested confidence bar is met:

1. Focused tests for changed behavior and direct contracts.
2. Compile/import or architecture guards when imports, boundaries, facades,
   generated manifests, or owner sizes changed.
3. The matching `scripts/codex_check.ps1 -Area <area>` gate when the change spans
   that feature area.
4. Full nonvisual QA only for broad cross-cutting work, release confidence, or
   an explicit request.
5. Packaging, visible UI, licensed assets, real-game archives, and external
   publication only when explicitly authorized.

Prefer behavior, protocol, import-order, AST-boundary, and golden-corpus tests.
Do not compensate for a missing configured test by silently choosing an easier
check; report the missing gate.

## Run safely

- Use `.\.venv\Scripts\python.exe` from the repository root.
- For pytest, disable its repo cache when useful and place `--basetemp` under
  `$env:TEMP`; never add test output to the repository.
- Run independent read-only checks concurrently only when their output is small
  and they do not contend for build or temp paths.
- Summarize large output; retain the decisive command, exit result, and failure.

## Report

Return:

- task-owned files used to select validation;
- exact commands run and observed results;
- relevant gates not run and why;
- remaining confidence gap or risk.

Update `docs/test-matrix.md` only when test ownership or authoritative commands
actually change.
