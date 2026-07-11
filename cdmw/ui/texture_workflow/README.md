# Texture Workflow

Owns setup, asset-authoring handoff controls, rule editing, profile selection,
progress, compare preview, and mod-package panels for texture workflows. Pure
profile and policy rules belong in `cdmw/domain/textures/`; execution belongs
in services or workers.

Related docs: `docs/features/asset-authoring-integrations.md`.

Mesh-linked base/albedo documents defer resident dirty-region production until
after the edit handler returns. The producer uses the composite cache, emits a
tight BGRA8 patch, and leases the emitted composite read-only until the Mesh
Editor worker copies it. A racing dirty edit uses copy-on-write, while the
session's original flattened RGBA remains immutable.
