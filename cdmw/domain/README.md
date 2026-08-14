# Domain

Owns pure rules and policies that should be testable without PySide widgets,
worker threads, or archive writes. Current domains cover archives, libraries,
mesh, packages, research, and textures.

Keep side effects, UI presentation, long-running work, and external tool calls
outside this package. Services, core modules, workers, and UI features should
call domain rules instead of duplicating policy decisions.

Related tests: domain-specific tests plus architecture boundary guards under `tests/`.
