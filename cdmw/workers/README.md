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

Related docs: `docs/runbooks/worker-lifecycle.md`, `docs/architecture.md`.
Related tests: `tests/test_workers.py` and worker entries in
`docs/test-matrix.md`.
