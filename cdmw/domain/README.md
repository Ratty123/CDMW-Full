# Domain

Owns pure rules and policies that should be testable without PySide widgets,
worker threads, or archive writes. Current domains cover archives, mesh,
packages, and textures.

Keep side effects, UI presentation, long-running work, and external tool calls
outside this package. Services, core modules, workers, and UI features should
call domain rules instead of duplicating policy decisions.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: domain-specific tests plus architecture boundary guards in
`docs/test-matrix.md`.
