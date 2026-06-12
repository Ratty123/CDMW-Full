# Prompt Templates

## Midpoint Audit

```text
Read AGENTS.md, docs/ai/PROJECT_MAP.md, docs/ai/TEST_MATRIX.md, docs/ai/KNOWN_PITFALLS.md, and docs/ai/RESTRUCTURE_MIDPOINT_AUDIT.md.
Audit the current repository state without editing production source files.
Report completed, partial, and not-started restructure areas; public wrappers; source guard risks; tests to run; and the safest next source-refactor task.
```

## Safe Refactor

```text
Read AGENTS.md and docs/ai/TEST_MATRIX.md first.
Move only the requested behavior from the current module to the appropriate cdmw/ui/<feature>, cdmw/services, cdmw/domain, or cdmw/workers location.
Preserve public imports with wrappers.
Do not change behavior except as required by the requested refactor.
Run targeted tests before continuing.
```

## Bugfix

```text
Reproduce or inspect the bug first.
Make the smallest source change that fixes behavior.
Avoid unrelated refactors.
Add or update a behavior test when feasible.
Run the narrowest relevant tests from docs/ai/TEST_MATRIX.md.
```

## Source Guard Migration

```text
Find the source guard and identify the behavior it protects.
Confirm the behavior's new owner module.
Update the guard to inspect the new module plus compatibility facade only when needed.
Run that guard test and any behavior tests for the feature.
```

## Graphify Summary Update

```text
Run or inspect Graphify output only if available.
Do not commit graphify-out/.
Update docs/ai/GRAPHIFY_MIDPOINT_SUMMARY.md with curated findings, not raw output.
Cross-check high-coupling findings against source search and tests before treating them as actionable.
```

## Continue Restructure Phase

```text
Read docs/ai/RESTRUCTURE_MIDPOINT_AUDIT.md.
Pick exactly one next source-refactor task from the safest-next list.
Do not touch cdmw_app.py or cdmw/ui/main_window.py except to preserve wrappers if explicitly required.
Run targeted tests before continuing to another task.
Stop and report if public imports or source guards conflict.
```
