# Archive Safety Model

Archive mutation must be explicit, backed up, and recoverable.

Safe read-only operations:

- Browse archive indexes.
- Preview archive entries.
- Extract files.
- Scan archives and build caches.
- Build loose mod packages.

Mutation requirements:

- User-visible command summary.
- Preflight validation.
- Explicit confirmation.
- Backup before write.
- Apply step with clear error handling.
- Restore path for backups.
- Runtime/report logs that do not hide failures.

UI code must not directly call destructive low-level archive mutation functions.
Move destructive coordination through `ArchiveMutationService` as migration
continues.
