# Worker Lifecycle

New worker code uses shared contracts in `cdmw/workers/`.

- Return `WorkerSuccess[T]` or `WorkerFailure`.
- Accept cancellation through `CancellationToken` or an equivalent stop event.
- Emit progress through signals/callbacks, not direct widget mutation.
- Report diagnostic names and elapsed time where practical.
- Worker-heavy tabs implement `request_shutdown()` and
  `iter_shutdown_workers()`.
- Shell close flow requests tab shutdowns, asks tracked threads to quit, waits
  asynchronously, and force-stops only after timeout.

Never call blocking `thread.wait(...)` from UI close paths.
