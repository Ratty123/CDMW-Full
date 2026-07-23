# Startup Flow

`cdmw_app.py` delegates to `cdmw.app.bootstrap.main`.

1. Parse arguments in `cdmw.app.args`.
2. Route startup-splash host mode before normal app startup.
3. Validate mutually exclusive CLI/GUI/legacy renderer flags.
4. For GUI mode, acquire the single-instance guard. Normal launches request
   activation if another instance is running; startup smokes report the
   collision as failure.
5. Write the PyInstaller runtime marker and start external splash when enabled.
6. Schedule startup maintenance for stale PyInstaller runtime and temp cache
   cleanup.
7. Import and run GUI through `cdmw.app.gui`.
8. On bootstrap failure, write a bootstrap report.
9. Always close startup splash and release the single-instance guard on GUI exit.

CLI mode runs startup maintenance synchronously and then calls the pipeline CLI.

## Cold-start deferral

- The public `run_gui()` facade imports its implementation only when called.
- `MainWindow` has one direct base and binds legacy feature methods through the
  generated provider manifest; provider modules are resolved on first use.
- Optional tool tabs are stable lazy containers. Heavy feature widgets are
  created once on first display or explicit feature-method use.
- Collapsed Texture Workflow sections create their bodies on first expansion,
  and Settings helper/service discovery waits until the owning control is used.
- Full archive mode releases the splash and shows the shell after UI
  construction, then schedules the resident-backend load on the next event-loop
  turn. Its first query, refresh, and lazy Finder catalogue work never hold the
  main window or run Python archive-tree walks on the UI thread. Legacy mode
  retains its existing startup/cache behavior. Global sidecar and folder-filter
  indexes still start only from their owning control or a maximum-throughput
  profile.
- The .NET Mesh Editor helper emits `protocol_ready` before D3D device setup so
  launcher readiness does not wait for renderer initialization.

Keep the provider manifest synchronized with:

```powershell
.\.venv\Scripts\python.exe scripts\generate_window_feature_provider_members.py --check
```

Release packaging regenerates the provider manifest, verifies the generated
metadata, and only then starts PyInstaller. Lazy method callbacks are stable
methods on a QObject receiver owned by `MainWindow`, so
signals emitted by worker threads arrive on the UI thread without importing the
provider early. Do not replace these callbacks with lambdas or plain callable
objects across a thread boundary; connection flags alone do not give those
objects UI-thread affinity.

External splash launch never spin-waits for a readiness file. The parent writes
one atomic command file, starts a passive monitor that reaps the host, and
continues startup immediately. Splash release deletes command/legacy-ready/temp
artifacts synchronously, while a background watchdog gives the host a bounded
grace period before terminate/kill. The host also deletes its artifacts on every
exit path; background startup maintenance prunes stale artifacts from crashed
older sessions without touching a live owner PID. Both splash windows are
input-transparent and cannot retain mouse or keyboard focus over the shell.

Neither splash implementation imposes a minimum display duration. Once UI
construction is ready, the main window is shown immediately. Full mode does not
wait for archive discovery or the initial query; legacy archive startup may keep
its prior first-paint/one-second fallback. Both paths retain the same
splash-artifact cleanup.

Full's top-right progress bar belongs only to archive load/refresh. Backend
progress maps `completed`, `total`, `phase`, and `current_item`; unknown totals
are indeterminate and successful publication ends at `Archive ready 100%`.
Preview readiness stays inside the preview pane. Refresh keeps the published
session usable and atomically replaces it only after the next session/query is
ready. After a Full archive session is published, the Item Finder builds or
loads its archive-fingerprint catalogue in the resident backend, caches the
restored first page, and prepares that page's icons before continuing the
durable all-icon thumbnail warmup at low priority. None of this work blocks the
splash or main-window first paint, and opening Item Finder consumes any ready
page/images instead of starting the pipeline.

The initial archive-path dialog runs package-root discovery and path validation
through `startup_path_task_controller.py`. Requests are cancellable and
latest-wins; closing the dialog only requests cancellation and never waits on
the UI thread. The controller applies a result only when its request ID and
current path still match.

## Startup-smoke contract

Automated GUI smokes must set all three variables:

- `CDMW_GUI_STARTUP_SMOKE=1`
- `CDMW_GUI_STARTUP_SMOKE_RESULT=<absolute temporary JSON path>`
- `CDMW_SINGLE_INSTANCE_SCOPE=<unique test-run identifier>`

Exit code zero alone is not proof of GUI startup. Success requires the result
JSON to contain `ok: true` and `stage: post_construction`; the marker is written
atomically only after the main window and any requested smoke target are
verified. A guard collision writes `ok: false`, reports
`stage: single_instance_guard`, and exits with code 3. Production launches must
leave `CDMW_SINGLE_INSTANCE_SCOPE` unset so the normal application-wide guard
is unchanged.

The configured-archive release gate uses `CDMW_STARTUP_BENCHMARK=1` and
`CDMW_BENCHMARK_PACKAGE_ROOT=<game-root>`. Add a no-match
`CDMW_BENCHMARK_SEARCH_TEXT` when validating worker delivery: success requires
`archive_scan_complete`, `main_window_shown`, `first_paint`,
`startup_benchmark_search_complete`, and a heartbeat with
`clean_shutdown: true`.
Archive extension input is canonicalized before filtering: `All files` becomes
`*`, and malformed `All files.pac` becomes `.pac` rather than a literal suffix.
