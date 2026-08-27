# Workers

Owns shared long-running worker contracts, cancellation, result payloads, Qt
worker runner glue, and extracted archive, asset authoring, preview, package,
texture, utility, Model Library, Mesh Editor topology edit, and D3D11 package
workers.

Workers must not mutate UI widgets directly. Report progress and results through
typed payloads, Qt signals, and cancellation-aware execution. Keep business
policy in services/domain and keep UI rendering decisions in UI packages.
`CancellationToken.raise_if_cancelled()` raises the shared
`cdmw.domain.cancellation.RunCancelled`, also exposed by legacy
`cdmw.models` and core compatibility imports.
Asset authoring workers cover Material Maker export plus OpenImageIO metadata,
convert, and diff tasks.
Mesh Editor topology workers execute Delete/Subdivide/Refine through service
bridges off the UI thread; the normal edit math path is native-first through
`native/cdmw_mesh_core`.
`new_item_workers.py` shapes the New Item Studio's snapshot, plan, export and
install as `(log, stop_event)` tasks for the utility runner; the service does
the work and the tab only sees results. Effect catalogue and resident package
preparation use separate cancellable latest-wins lanes. Imported model roots are
leased by readers and retired through `new_item_cleanup_worker.py` only after
those leases finish, so replacement, discard, failure, and shutdown never block
the UI thread on recursive cleanup.

Related tests: `tests/test_workers.py` and worker entries under `tests/`.
