# Core

Owns low-level archive, DDS, texture workflow, package, catalog, research,
texture editor, native-helper integration, and compatibility orchestration that
has not moved to narrower packages yet.

Keep PySide widget code out of core. Preserve legacy public imports while moving
new policy to `cdmw/domain/`, coordination to `cdmw/services/`, long-running
execution to `cdmw/workers/`, mesh/material operations to `cdmw/modding/`, and
preview packaging to `cdmw/rendering/`.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: focused feature tests and architecture guards in
`docs/test-matrix.md`.
