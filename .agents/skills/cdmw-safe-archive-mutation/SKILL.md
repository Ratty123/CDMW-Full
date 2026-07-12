---
name: cdmw-safe-archive-mutation
description: Plan, implement, review, or validate safe CDMW archive writes, patches, backups, restores, and destructive PAMT or PAZ operations. Use whenever code may mutate game archives or recovery sets, including UI commands, ArchiveMutationService, archive_patching, cancellation, rollback, or restore. Do not trigger for browse, preview, extract, scan, cache, or loose-package work that is provably read-only.
---

# Mutate CDMW archives safely

## Classify before editing

Read `docs/features/archive-safety-model.md`, the archive ownership section in
`docs/project-map.md`, and relevant archive tests in `docs/test-matrix.md`.

Classify the path as read-only or mutating. Browse, preview, extract, scan,
cache, and loose-package build paths must remain read-only. If a supposedly
read-only path reaches a writer, stop and report the boundary violation.

## Enforce the mutation sequence

For every mutation, require this order:

1. Build an exact user-visible command and target summary.
2. Validate the plan and affected archive set.
3. Obtain explicit confirmation for the named mutation.
4. Create and verify the backup or recovery set.
5. Apply through `ArchiveMutationService` and `cdmw.core.archive_patching`.
6. Report failures without hiding partial progress.
7. Provide and validate the matching restore path.

UI code must not call low-level archive writers. Core remains the PAMT/PAZ
writer; the service owns preflight, backup, apply, backup listing, and restore.
Do not substitute another archive, game root, backup location, or credential.

Check cancellation before writes and at supported progress boundaries. If
cancellation arrives after backup completion, restore that backup before
reporting cancellation. Do not interrupt backup publication or multi-file
restore after either begins.

## Validate without risking source data

- Test only against copies or owned temporary fixtures.
- Fingerprint every source archive before and after validation.
- Exercise preflight rejection, confirmation boundary, backup failure, apply
  failure, cancellation before write, cancellation after backup, and restore
  behavior relevant to the change.
- Run `tests/test_archive_mutation_service.py`,
  `tests/test_archive_patch_preflight.py`, and narrower owning tests as relevant.

Stop and ask when the target, destructive scope, backup destination, or restore
expectation is materially ambiguous.

Report the exact target class, mutation sequence, tests, fingerprints, rollback
evidence, and any unverified recovery risk.
