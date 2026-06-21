# Texture Pipeline

Owns no-UI texture workflow helpers: runtime config, workspace paths, DDS/PNG
inspection, discovery, planning, preflight summaries, preview generation,
manifest tracking, logging, package export defaults, and cancellable `texconv`
execution.

Keep PySide controls and user interaction outside this package. Pure texture
rules belong in `cdmw/domain/textures/`; UI panels belong in
`cdmw/ui/texture_workflow/`; background execution belongs in services and
workers.

Related docs: `docs/architecture.md`, `cdmw/ui/texture_workflow/README.md`.
Related tests: texture entries in `docs/test-matrix.md`.
