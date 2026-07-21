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
- The first accepted shell close hides the main window immediately and starts
  one idempotent shutdown coordinator. It rejects registered modeless mesh
  builders before requesting tab/worker shutdown, then polls builders,
  `QThread`s, owned `QProcess` objects, and the archive backend asynchronously.
  It retains every owned thread/process object until teardown is confirmed;
  `finished` alone is not a safe ownership-release boundary. After eight
  seconds it force-stops only owned external process trees, never a `QThread`,
  and continues polling. Duplicate close requests do not start another flow.
- A parentless Python `QObject` worker that will be deleted by the UI must move
  back to the owning UI thread from its terminal worker-thread signal before
  `QThread.quit()`. After `wait(0)` confirms native teardown, the UI may clear
  owner references and defer-delete both objects. Deleting the Python-backed
  worker in the native QThread tail can invert Qt locks against the GUI GIL.
- Picker close handlers request cooperative cancellation and return
  immediately; the shell retains thread ownership until completion.
- Cancellable subprocesses run in an owned process group. Cancellation and
  timeout allow a bounded grace period, then stop the full descendant tree;
  forced Windows teardown waits for captured descendants to exit before it
  reports completion.
- Persistent mesh/preview helpers continuously drain stderr into a 64 KiB
  diagnostic tail. Mesh Editor QProcess shutdown is timer-driven: terminate
  first, then kill the child tree after bounded grace; UI code never waits for
  process start, writes, or finish. Archive Preview expected stops are bound to
  the exact `QProcess` object and its monotonic generation before terminate or
  kill; stale stop records cannot suppress a later process failure, and device
  loss remains diagnostic.
- Static-replacement post-preflight construction is one failure-safe lifecycle.
  The preparation overlay and partial dialog are registered together; failure
  or shutdown stops their timers, texture/package workers, and renderer before
  unregistering and deleting the dialog. Successful open transfers ownership
  to the normal modeless-dialog finished callback. Setup widgets must be added
  to a parent/layout before any `show()` or `setVisible(True)` call.
- The full archive backend is one resident, independently packaged .NET
  `QProcess` with `cdmw-full-archive-core.dll` beside it. Its first request is a
  protocol/native-ABI/index-version handshake; application work stays queued
  until that succeeds. Requests carry UI generations, cancellation is explicit,
  stale responses are rejected, and stderr is retained only as a bounded
  diagnostic tail. Protocol v3 rejects stale packaged workers at handshake.
  Normal close sends `shutdown`, gives the backend one second to exit, then uses
  one-second terminate/kill grace while the shell coordinator keeps polling. A
  user-selected legacy recovery is
  process-local: cancel bridge requests, restore the legacy model, request the
  same nonblocking shutdown, and only then schedule the legacy scan. Never
  restart or fall back invisibly after an incompatible or failed handshake.
- Shell lazy-feature callbacks verify that their Qt window owner is still alive
  before resolving or invoking provider code. Late process or worker signals
  delivered after window destruction are ignored.
- Output workers stage complete results beside the destination and publish by
  atomic rename; cancellation or write failure leaves prior output intact.

Never call blocking `thread.wait(...)` from UI close paths. `wait(0)` is the
nonblocking completion fence used by the close poller.

The clean-shutdown heartbeat phase `closed` is written only after registered
builders, owned threads/processes, resident renderers, and the archive backend
have stopped and the final `QMainWindow` close is being accepted.

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
