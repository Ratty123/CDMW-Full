# Text Search

Owns Text Search UI, results presentation, archive-picker search, and preview
coordination. Keep long-running searches cancellable and off the UI thread.
Search, preview, and export each use shell-owned workers. Export requests use
monotonic IDs, reject stale signals, bound queued progress, and atomically
publish each extracted/copied file after cancellation checks.

Preview Find retains every match for its count and next/previous navigation,
but draws a bounded set of highlights around the active match. Cursor positions
account for UTF-16 offsets so emoji and supplementary characters do not shift
selection. Shared code previews follow the same rules.

With the standalone archive backend, archive searches stream bounded match
batches from the resident catalogue service. Results retain only session and
entry IDs; preview prepares one entry and archive-result export sends entry IDs
back to the worker. Loose-folder search and the legacy `set_archive_entries`
compatibility path remain unchanged during the shadow release.
