# Domain

Owns pure rules and policies that should be testable without PySide widgets,
worker threads, or archive writes. Current domains cover archives, libraries,
mesh, new-item authoring, packages, research, and textures.

Keep side effects, UI presentation, long-running work, and external tool calls
outside this package. Services, core modules, workers, and UI features should
call domain rules instead of duplicating policy decisions.

`new_item/` owns the draft specification, collision-free identity allocation,
equipment-fit classification, effect values, placement transforms, and stable
validation findings. It knows no archive paths beyond immutable facts supplied
by the service snapshot and never performs a read or write itself.

Related tests: domain-specific tests plus architecture boundary guards under `tests/`.
