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

Both searches read the query and filters the same way. A path filter without
`*` or `?` matches anywhere in the path, ignoring case. With a wildcard it
matches the file name (`*.xml`), or, when it contains a slash, the path from
any folder (`object/*`); a leading slash anchors it at the archive root. Regex
`^` and `$` apply to each line, CRLF line ends included, and empty matches are
skipped. `cdmw/core/text_search.py` and the worker's `ArchiveTextSearchService`
own these rules; `text_search_matching_rules` and the parity cases in
`tests/test_text_search_async_io.py` keep them aligned.

With the standalone archive backend, archive searches stream bounded match
batches from the resident catalogue service. Results retain only session and
entry IDs; preview prepares one entry and archive-result export sends entry IDs
back to the worker. Loose-folder search and the legacy `set_archive_entries`
compatibility path remain unchanged during the shadow release.
