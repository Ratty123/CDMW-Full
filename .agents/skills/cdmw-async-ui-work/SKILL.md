---
name: cdmw-async-ui-work
description: Implement or review safe cancellable PySide6 and Qt background work in CDMW. Use when changing QThread or worker ownership, long-running UI operations, subprocesses, archive or model scans, import/export, hashing, preview preparation, request IDs, stale-result handling, progress, cancellation, atomic output, dialog close, or application shutdown. Do not use for synchronous pure UI state changes with no I/O or expensive work.
---

# Build asynchronous CDMW UI work

## Trace ownership first

1. Read `docs/runbooks/worker-lifecycle.md` and the relevant sections of
   `docs/architecture.md` and `docs/test-matrix.md`.
2. Trace the existing UI caller, service, worker, result delivery, and shutdown
   path before editing.
3. Reuse an existing task controller, utility slot, worker contract, or owner
   before creating another abstraction.

## Preserve the lifecycle contract

- Capture an immutable request before starting work.
- Put coordination and I/O in services/workers, never in widget callbacks.
- Accept cooperative cancellation and use a monotonic request or generation ID.
- Deliver through queued Qt signals to an owning-thread `QObject`; reject stale
  results before UI publication.
- Create `QImage` off-thread when useful, but create `QPixmap` on the UI thread.
- Stage complete output beside its destination and publish atomically.
- Expose `request_shutdown()` and `iter_shutdown_workers()` for worker-owning UI.
- Retain each `QThread` until nonblocking `wait(0)` proves native teardown.
- For subprocesses, allow bounded cooperative grace, then terminate the owned
  process tree. Never block UI close waiting for process or thread completion.

Keep progress bounded and avoid large mutable payloads crossing threads. Closing
a dialog must invalidate late results, request cancellation, and return promptly;
the shell or owning controller retains cleanup ownership.

## Validate

Run the smallest focused behavior tests plus relevant responsiveness, shutdown,
and stale-result guards from `docs/test-matrix.md`. Validate success, failure,
cancellation, close-during-work, and stale-completion paths when changed.

Report exact tests, thread/process ownership preserved, atomic-publication
behavior, and any shutdown or cancellation path not exercised.
