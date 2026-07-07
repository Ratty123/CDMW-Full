# Documentation Index

Use this file to choose the right doc before opening everything.

## Root Docs

- `architecture.md`: stable architecture, package boundaries, ownership, and
  safety rules.
- `project-map.md`: compact navigation map for code owners, tests, and docs.
- `project-map-detailed.md`: long historical/file-level ownership map. Use it
  only when `project-map.md` is not enough.
- `test-matrix.md`: validation commands by area.
- `release-confidence-plan.md`: release/readiness validation order and latest
  broad confidence evidence.
- `mesh_editor_v2_plan.md`: Phase 0 implementation map and staged integration
  points for the strict MeshAsset editing pipeline.
- `mesh_editor_net_repair_audit.md`: working audit for the embedded .NET Mesh
  Editor UI, bridge, and commit lifecycle repair.
- `mesh_editor_net_authoritative_renderer_audit.md`: working audit for the
  .NET renderer authority, material/texture, and local edge-selection gap.

## Subfolders

- `features/`: long-lived feature/topic docs broader than one code package.
  - `archive-safety-model.md`: archive mutation safety rules.
  - `asset-authoring-integrations.md`: optional authoring tool integrations and
    where they plug into services/workers.
  - `mesh-editing-pipeline.md`: mesh parser/rebuilder/editor map, metadata loss
    risks, and the first no-edit round-trip harness slice.
  - `mesh-editor-skeleton-discovery.md`: read-only reverse-engineering notes for
    Crimson skeleton, animation, sequence, socket, and pose binding. Keep it
    because Mesh Editor rigging/animation smoke tests and future native mesh
    authoring work need the discovered binding rules.
- `runbooks/`: short operational flows.
  - `startup-flow.md`: app startup sequence and ownership.
  - `worker-lifecycle.md`: worker/thread shutdown rules.
- `reference/`: cross-cutting notes.
  - `known-pitfalls.md`: durable repo pitfalls and boundary traps.
- `plans/active/`: current implementation plans only. Delete superseded,
  completed, handoff, and new-chat bootstrap notes.
- `ai/PROJECT_MEMORY.md`: compact durable AI handoff facts, not chat logs.

## Rules

- Update the nearest owning doc when behavior, APIs, commands, dependencies,
  config, data flow, architecture, operations, or validation commands change.
- Do not duplicate the same guidance in multiple files. Link to the owning doc.
- Keep root `docs/` for navigation/control docs; put topic docs in a subfolder.
