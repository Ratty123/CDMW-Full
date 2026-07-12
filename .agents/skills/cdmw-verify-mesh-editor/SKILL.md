---
name: cdmw-verify-mesh-editor
description: Choose and evaluate trustworthy validation for CDMW Mesh Editor, static replacement, native preview, mesh services, mesh harness, or .NET/Vortice changes. Use when a task needs focused mesh tests, mesh-unit, native or .NET builds, GPU soak, visual proof, or real-game PAC evidence. Never treat synthetic or protocol coverage as user-facing visual proof, and never launch visible or licensed real-game gates without explicit authorization.
---

# Verify the CDMW Mesh Editor

## Read the owning contracts

Read only the relevant portions of:

- `AGENTS.md`;
- `docs/test-matrix.md` under **Mesh Editor Suite**;
- `docs/features/mesh-editing-pipeline.md`;
- `docs/release-confidence-plan.md` when release-level evidence is requested.

## Classify the required proof

1. **Focused behavior:** run the exact Python/native/.NET tests owning the
   changed contract.
2. **Nonvisual mesh regression:** run
   `.\scripts\codex_check.ps1 -Area mesh-unit`. This is unit/protocol coverage
   and must not open a window.
3. **Native or .NET integration:** run only the affected Release build,
   self-test, hidden-window smoke, or GPU soak named by `docs/test-matrix.md`.
4. **User-facing visual proof:** require explicit authorization, then run
   `.\scripts\codex_check.ps1 -Area mesh -GameRoot <path>` against the real
   archive. Do not infer authorization from a game path already being present.

The canonical production proof must report renderer
`d3d11_vortice_shader` and edit backend `cdmw_mesh_core_0.1`. Treat legacy
D3D11, checker, synthetic geometry, service smoke, and protocol scenarios as
compatibility or regression evidence only.

## Validate evidence

For real-game proof, require:

- versioned JSON evidence under a system temporary root;
- real PAC/archive/texture provenance and no forbidden fallback;
- unchanged source PAMT/PAZ fingerprints;
- required selection, transform, material, texture, UV, topology, undo/export,
  and readback gates for the requested scenario;
- recorded backend, capture/input ownership, timings, and frame/heartbeat
  budgets from the current test contract.

Abort rather than inject input when the expected foreground renderer ownership
cannot be proven. Never claim visual success from a passing synthetic test,
protocol result, or screenshot without the required evidence fields.

## Report

State proof class, commands, observed results, evidence path, archive fingerprint
result, fallback state, skipped higher gates, and residual user-facing risk.
