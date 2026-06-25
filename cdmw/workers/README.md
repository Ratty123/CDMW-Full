# Workers

Owns shared long-running worker contracts, cancellation, result payloads, Qt
worker runner glue, and extracted archive, preview, package, texture, utility,
Model Library, and D3D11 package workers.

Workers must not mutate UI widgets directly. Report progress and results through
typed payloads, Qt signals, and cancellation-aware execution. Keep business
policy in services/domain and keep UI rendering decisions in UI packages.

Related docs: `docs/worker_lifecycle.md`, `docs/architecture.md`.
Related tests: `tests/test_workers.py` and worker entries in
`docs/test-matrix.md`.
