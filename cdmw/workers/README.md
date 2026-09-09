# Workers

Owns shared long-running worker contracts, cancellation, result payloads, Qt
worker runner glue, and extracted archive, asset authoring, preview, package,
texture, utility, Model Library, Mesh Editor topology edit, and Rust preview package
workers.

Workers must not mutate UI widgets directly. Report progress and results through
typed payloads, Qt signals, and cancellation-aware execution. Keep business
policy in services/domain and keep UI rendering decisions in UI packages.
`CancellationToken.raise_if_cancelled()` raises the shared
`cdmw.domain.cancellation.RunCancelled`, also exposed by legacy
`cdmw.models` and core compatibility imports.
Asset authoring workers cover OpenImageIO metadata, convert, and diff tasks.
Mesh Editor topology workers execute Delete/Subdivide/Refine through service
bridges off the UI thread; the normal edit math path is native-first through
`native/cdmw_mesh_core`.
`new_item_workers.py` shapes Create New Item's snapshot, plan, export and
overlay install as `(log, stop_event)` tasks for the utility runner; the service does
the work and the tab only sees results. `mod_merge_workers.py` scans selected mod
folders and exports their reviewed composition on the same serialized utility runner.
Effect catalogue and resident package
preparation use separate cancellable latest-wins lanes. Imported model roots are
leased by readers and retired through `new_item_cleanup_worker.py` only after
those leases finish, so replacement, discard, failure, and shutdown never block
the UI thread on recursive cleanup.

Related tests: `tests/test_workers.py` and worker entries under `tests/`.
