# Text Search

Owns Text Search UI, results presentation, archive-picker search, and preview
coordination. Keep long-running searches cancellable and off the UI thread.
Search, preview, and export each use shell-owned workers. Export requests use
monotonic IDs, reject stale signals, bound queued progress, and atomically
publish each extracted/copied file after cancellation checks.
