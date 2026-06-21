# Package Domain

Owns package manifest and preflight rules used before final package creation or
export.

Keep filesystem writes, archive mutation, and UI confirmation outside this
package. Services and core package builders apply these rules during execution.

Related docs: `docs/archive_safety_model.md`, `docs/architecture.md`.
Related tests: package, archive mutation, and architecture entries in
`docs/test-matrix.md`.
