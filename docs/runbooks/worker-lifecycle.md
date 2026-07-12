# Worker Lifecycle

New worker code uses shared contracts in `cdmw/workers/`.

- Return `WorkerSuccess[T]` or `WorkerFailure`.
- Accept cancellation through `CancellationToken` or an equivalent stop event.
- Cooperative cancellation raises the shared
  `cdmw.domain.cancellation.RunCancelled`; `CancellationToken`, legacy
  `cdmw.models`, and core compatibility imports expose that same class.
- Emit progress through signals/callbacks, not direct widget mutation.
- Report diagnostic names and elapsed time where practical.
- Worker-heavy tabs implement `request_shutdown()` and
  `iter_shutdown_workers()`.
- Shell close flow requests tab shutdowns, asks tracked threads to quit, waits
  asynchronously, and force-stops only after timeout. It retains every owned
  `QThread` until nonblocking `wait(0)` confirms native teardown; `finished`
  alone is not a safe ownership-release boundary.
- Picker close handlers request cooperative cancellation and return
  immediately; the shell retains thread ownership until completion.
- Cancellable subprocesses run in an owned process group. Cancellation and
  timeout allow a bounded grace period, then stop the full descendant tree;
  forced Windows teardown waits for captured descendants to exit before it
  reports completion.
- Persistent mesh/preview helpers continuously drain stderr into a 64 KiB
  diagnostic tail. Mesh Editor QProcess shutdown is timer-driven: terminate
  first, then kill the child tree after bounded grace; UI code never waits for
  process start, writes, or finish.
- Output workers stage complete results beside the destination and publish by
  atomic rename; cancellation or write failure leaves prior output intact.

Never call blocking `thread.wait(...)` from UI close paths. `wait(0)` is the
nonblocking completion fence used by the close poller.

Model Library ZIP resolution/extraction and shell scene import/companion scans
stay in their existing task/utility workers. Recolor analysis and DDS preview
generation share one cancellable operation worker; every result is request-ID
checked before UI publication. Image decode may produce `QImage` in the worker,
while `QPixmap` creation remains on the UI thread.

Static-replacement texture-folder discovery runs as a bounded, cancellable
shell utility task. Closing its dialog invalidates the request and requests
cooperative stop; the shell continues to own the worker through cleanup.

Source-mix loose/mod scans, archive-target resolution, and scene imports use
frozen request/result payloads through the same shell-owned utility slot.
Dialog close or shell shutdown invalidates late results and requests stop.

Mesh rebuild-report saves use a tracked output worker. The UI serializes the
already-computed immutable report, then the worker stages, flushes, and
atomically publishes it; cancellation before publication preserves the prior
destination.

Archive Item Finder warmup owns persistent-cache lookup and image decode. It
returns `QImage`; the UI only creates `QPixmap` and scales an in-memory cache
entry. Static-replacement icon capture likewise detaches a `QImage`, then uses
the shell output worker for formatting and atomic PNG publication.

Material-sidecar live-preview package validation, manifest cloning, override
application, and staging writes run inside the cancellable preview task.
Closing the dialog invalidates its generation and stops that owned task.

Retrofit/Repackage owns cancellable scan and conversion threads through its
lazy tool widget (or the transient-dialog registry). Scan results are
latest-wins. A conversion request stages every selected package under the
destination filesystem, then publishes complete folders/ZIPs by rename; stale,
cancelled, or failed work cannot expose partial output.

Texture Research debounces mip/normal detail selection into a latest-wins
worker lane. Its separate report lane receives frozen rows and performs both
serialization and atomic publication off the UI thread; both lanes are exposed
through the tab shutdown contract.
