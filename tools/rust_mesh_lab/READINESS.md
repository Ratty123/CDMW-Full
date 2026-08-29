# Rust Mesh Lab readiness

## Result

**PARTIALLY READY**

The isolated lab builds, launches a responsive Windows window, selects a Direct3D 12 adapter, renders validated geometry and a supported explicit 2D DDS reference through `wgpu`, opens archive roots read-only, virtualizes archive results, loads direct/archive PAC/PAM/PAMLOD candidates, and supports camera navigation plus pointer-driven selection, transform, sculpt, and history workflows on an in-memory generational mesh.

It is not LAB READY because private real-game parity, complete texture reconstruction/material composition, PAC skinning/appearance, representative stress/performance evidence, cache, versioned lab projects, fuzzing, and source fingerprint sessions remain incomplete.

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
- Interactive Move, Rotate, Scale, Grab, Smooth, Inflate, and Pinch plus atomic face Delete, Subdivide, Duplicate, Undo, and Redo; topology failures leave the complete working state unchanged and generated subdivision/duplicate faces become the deterministic selection.
- One modal gesture owner and one committed history entry per confirmed gesture.
- Deterministic click/brush/rectangle/lasso query predicates, stale-snapshot rejection, and a persistent 32-pixel screen grid that bounds local candidate inspection in the interaction crate.
- User-selectable depth-aware Visible and X-Ray selection. Visible candidates query a projected-triangle BVH with interpolated depth; sculpt brushes always use that surface-only route, and no synchronous GPU readback is used.
- Viewport-aligned Vertex/Edge/Face Click, Brush, Rectangle, and Lasso selection with visible overlays in either depth mode and Replace/Add/Subtract/Toggle operations.
- Bounded raw pointer sampling that retains press, intermediate movement, and release when Windows coalesces redraws; long lassos compact deterministically while retaining their final release point, one completed gesture creates one history entry, and Esc/resize/focus loss restores the pre-gesture mesh.
- Orbit, pan, zoom, frame-selected/all, six standard views, and one aspect-aware camera generation shared by rendering and interaction snapshots.
- Direct3D 12 `wgpu` surface, depth target, persistent revisioned mesh buffers, and Textured/Solid/Solid+Wire/Wireframe/Vertices/Wire+Vertices/X-Ray modes.
- egui archive/assets, viewport, inspector, selection/edit, and status surfaces.
- Bounded cancellable latest-wins loader/search worker with stale-result rejection.
- Versioned neutral binary package and manifest comparison.
- Explicit neutral OBJ/MTL export of the edited working copy with staging, cancellation checks, reparse, structural comparison, atomic new-directory publication, and no source texture embedding.
- Synthetic unit tests, formatting, Clippy, and visible Release interaction smoke.
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
| Lab project | Incomplete | Camera/tool/history persistence is not published yet |
| Neutral export | OBJ/MTL implemented | GLB, skinning/material preservation, and private corpus re-import parity remain incomplete |
| Persistent cache | Incomplete | No cold/warm cache timing |
| Interaction stress | Partial | 100 lasso variants, 100 cancellations, 1,000 mixed events, bounded fast-pointer retention, 10,000-point lasso compaction, and a 100,000-element local-query candidate bound pass; per-tool long high-rate/focus-loss/resize and bounded-memory soaks remain unrun |
| Performance targets | Partial instrumentation | The live inspector now reports last/p95 CPU query and operator cost plus indexed candidates inspected, but no representative PAC latency, FPS, GPU, or memory claim has been measured |
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

## Visible synthetic interaction proof

A Release build on 2026-08-29 loaded the redistributable 3-vertex PAM and 2×2
DDS fixture through Direct3D 12 and exercised the actual Windows event path.
The live viewport switched among textured, wireframe, and X-Ray rendering, changed
standard camera views, zoomed with the wheel, retained both endpoints of a fast
Brush drag, selected a face with Rectangle, displayed and applied the Move and
Rotate gizmos, applied Grab sculpting, and restored a Move through Undo. Window
resize kept equal world-space X/Y spans equal in screen pixels; the automated
projection test covers both wide and tall viewport shapes. This is synthetic
interaction proof, not real-PAC usability or representative latency/FPS. The
depth-aware Visible route has deterministic synthetic unit proof but was added
after this live capture and has not yet been exercised through the visible Windows path.

## Production boundary

Do not describe this lab as replacing or superseding the production Mesh Editor. Synthetic or visible lab results do not establish the canonical CDMW production proof (`d3d11_vortice_shader` with `cdmw_mesh_core_0.1`) and do not authorize a production backend switch.
