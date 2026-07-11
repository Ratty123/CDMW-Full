# Package Domain

Owns immutable export/profile policy, package layout rules, retrofit value
models, manifest summaries, and preflight rules used before package creation.

Keep filesystem writes, archive mutation, and UI confirmation outside this
package. `PackageService`, workers, and core compatibility builders coordinate
I/O while applying these rules.

Related docs: `docs/features/archive-safety-model.md`, `docs/architecture.md`.
Related tests: package, archive mutation, and architecture entries in
`docs/test-matrix.md`.
