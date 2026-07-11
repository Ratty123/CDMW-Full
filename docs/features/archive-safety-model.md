# Archive Safety Model

Archive mutation must be explicit, backed up, and recoverable.

Safe read-only operations:

- Browse archive indexes.
- Preview archive entries.
- Extract files.
- Scan archives and build caches.
- Build loose mod packages.

Before scanning, CDMW warns when `.pamt` files exist outside the canonical
root-level, `NNNN/`, `game_files/`, or `game_files/NNNN/` layouts. The warning
offers cancel, open-folder, and explicit scan-anyway actions; CDMW never deletes
or silently excludes suspected backup archives.

Mutation requirements:

- User-visible command summary.
- Preflight validation.
- Explicit confirmation.
- Backup before write.
- Apply step with clear error handling.
- Restore path for backups.
- Runtime/report logs that do not hide failures.

UI code must not directly call destructive low-level archive mutation functions.
`ArchiveMutationService` owns the confirmed mutation plan and routes preflight,
backup creation, patch apply, backup listing, and restore to
`cdmw.core.archive_patching`. Core remains the only PAMT/PAZ writer.

Patch cancellation is checked before writes and at low-level progress boundaries.
If cancellation arrives after the backup is complete, the service restores that
backup before reporting cancellation. Backup publication and multi-file restore
finish once started because interrupting either can leave an unusable recovery
set or checksum chain.
