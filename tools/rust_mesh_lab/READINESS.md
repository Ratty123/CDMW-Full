# Rust Mesh Lab readiness

## Result

**PARTIALLY READY**

The isolated lab builds, launches a responsive Windows window, selects a Direct3D 12 adapter, renders validated geometry and a supported explicit 2D DDS reference through `wgpu`, opens archive roots read-only, virtualizes archive results, loads direct/archive PAC/PAM/PAMLOD candidates, and supports an in-memory generational edit/history workflow.

It is not LAB READY because private real-game parity, complete texture reconstruction/material composition, PAC skinning/appearance, viewport pointer routing, stress/performance evidence, cache, versioned lab projects, fuzzing, and source fingerprint sessions remain incomplete.

## Implemented and locally proven

- Isolated Cargo workspace; production CDMW has no dependency on it.
- Pinned Rust 1.95.0 and locked dependencies.
- Read-only `.pamt` index discovery and parsing with PAZ range validation.
- Stored and LZ4 entry decode; filename-derived ChaCha20 type 3 support.
- PAC/PAM/PAMLOD geometry foundations with fail-closed layout validation.
- DDS legacy/DX10 metadata, common format/color-space classification, bounded mip planning, and direct supported 2D `wgpu` upload.
- Exact/relative/unambiguous asset relation resolver.
- Immutable decoded source document and separate editable working document.
- Generational vertex/edge/face handles and topology generation.
- Move, Grab, Smooth, Inflate, Pinch, face Delete, Subdivide, Duplicate, Undo, and Redo.
- One modal gesture owner and one committed history entry per confirmed gesture.
- Deterministic click/brush/rectangle/lasso query predicates and stale-snapshot rejection in the interaction crate.
- Viewport-aligned Vertex/Edge/Face click selection with visible X-Ray overlay and Replace/Add/Subtract/Toggle operations.
- Direct3D 12 `wgpu` surface and persistent revisioned mesh buffers.
- egui archive/assets, viewport, inspector, selection/edit, and status surfaces.
- Bounded cancellable latest-wins loader/search worker with stale-result rejection.
- Versioned neutral binary package and manifest comparison.
- Explicit neutral OBJ/MTL export of the edited working copy with staging, cancellation checks, reparse, structural comparison, atomic new-directory publication, and no source texture embedding.
- Synthetic unit tests, formatting, Clippy, and visible launch smoke.
- Deterministic synthetic stress covering 100 lasso winding variants, 100 cancelled/restored gestures, and 1,000 mixed replay events with repeatable fingerprints and invariant validation.

## Incomplete gates

| Gate | State | Consequence |
|---|---|---|
| Private archive corpus | Not run | Archive READY cannot be claimed |
| Real PAC/PAM/PAMLOD parity | Not run | Geometry support remains partial |
| Partial/Sparse DDS reconstruction | Incomplete | Some archive textures cannot decode |
| Native texture/material binding | Partial | One explicit supported 2D DDS can render; multi-material binding, arrays/cubes, reconstruction, and fallback transcode remain incomplete |
| PAC skin palette/PAB/PABC/morph | Incomplete | Character appearance parity not proven |
| LOD1+ PAC editing | Unsupported | LOD0 diagnostic slice only |
| Pointer-to-selection UI routing | Partial | X-Ray Vertex/Edge/Face click is routed; rectangle/brush/lasso and gesture buffering remain incomplete |
| Visible-only GPU ID readback | Incomplete | No asynchronous depth-aware picking proof |
| Camera/orbit/pan/zoom | Incomplete | Current mesh normalization is diagnostic only |
| Lab project | Incomplete | Camera/tool/history persistence is not published yet |
| Neutral export | OBJ/MTL implemented | GLB, skinning/material preservation, and private corpus re-import parity remain incomplete |
| Persistent cache | Incomplete | No cold/warm cache timing |
| Interaction stress | Partial | 100 lasso variants, 100 cancellations, and 1,000 mixed events pass; per-tool high-rate/focus-loss/resize and bounded-memory soak remain unrun |
| Performance targets | Not measured | No latency/FPS claim |
| Fuzzing | Not run | Parser robustness proof incomplete |
| `cargo deny` / `cargo audit` | Not run yet | License/advisory gate unproven |

## Synthetic Release measurement

One local Release-mode microbenchmark on 2026-08-29 used the redistributable
3-vertex PAM plus 2×2 RGBA8 DDS fixture:

| Operation | Work | Observed total | Observed mean |
|---|---:|---:|---:|
| PAM decode | 1,000 iterations | 1.5522 ms | 0.0015522 ms |
| DDS inspect/mip plan | 10,000 iterations | 2.0298 ms | 0.00020298 ms |
| Mixed edit replay | 1,000 events | 2.5209 ms | 0.0025209 ms/event |

This is a synthetic CPU microbenchmark, not representative asset, archive,
GPU-frame, UI-latency, memory, or real-game proof. It does not satisfy the
33 ms interaction or stable-60-FPS readiness targets by itself.

## Production boundary

Do not describe this lab as replacing or superseding the production Mesh Editor. Synthetic or visible lab results do not establish the canonical CDMW production proof (`d3d11_vortice_shader` with `cdmw_mesh_core_0.1`) and do not authorize a production backend switch.
