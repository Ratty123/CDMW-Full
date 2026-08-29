# Rust Mesh Lab readiness

## Result

**PARTIALLY READY**

The isolated lab builds, launches a responsive Windows window, selects a Direct3D 12 adapter, renders validated geometry and a supported explicit 2D DDS reference through `wgpu`, opens archive roots read-only, virtualizes archive results, loads direct/archive PAC/PAM/PAMLOD candidates, and supports camera navigation plus pointer-driven selection, transform, sculpt, and history workflows on an in-memory generational mesh. The same app-owned workflows now have no-window construction and behavior coverage, and the shared renderer draw path has an opt-in offscreen D3D12 validation/readback gate.

It is not LAB READY because private real-game parity, complete texture reconstruction/material composition, PAC skinning/appearance, representative stress/performance evidence, cache, versioned lab projects, fuzzing, and source fingerprint sessions remain incomplete.

## Implemented and locally proven

- Isolated Cargo workspace; production CDMW has no dependency on it.
- Pinned Rust 1.95.0 and locked dependencies.
- Read-only `.pamt` index discovery and parsing with PAZ range validation.
- Stored and LZ4 entry decode; filename-derived ChaCha20 type 3 support.
- PAC/PAM/PAMLOD geometry foundations with fail-closed layout validation.
- Proven PAC section-to-LOD decoding and an **Editable LOD** selector. The worker prepares every decoded LOD, and switching preserves independent geometry, selection, and Undo/Redo state without multiplying the 512 MiB history budget. Non-manifold source edges retain all incident faces rather than rejecting an otherwise valid lower LOD.
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
- Direct3D 12 `wgpu` surface, depth target, persistent revisioned mesh/normal/bounds buffers, Textured/Solid/Solid+Wire/Wireframe/Vertices/Wire+Vertices/X-Ray modes, and independent Normals/Bounds overlays. Bones is visibly disabled until skeleton context exists.
- egui archive/assets, viewport, inspector, selection/edit, and status surfaces.
- No-window `LabApplication` construction and egui-frame coverage plus direct app-method tests for every selection shape/domain, Visible/X-Ray routing, camera operation and aspect, all preview modes/overlays, transform/sculpt/topology tools, exact cancel, and Undo/Redo.
- Offscreen D3D12 renderer coverage using the live mesh draw dispatcher for all seven preview modes with Normals and Bounds across 4:3, portrait, and widescreen targets; a validation error scope and CPU readback reject invalid or all-background output without constructing a window.
- Read-only `headless-mesh` probe for caller-selected PAC/PAM/PAMLOD files, with fresh-working-mesh operation/Undo/Redo fingerprints and invariants for Move, Grab, Smooth, Inflate, Pinch, face Delete, Subdivide, and Duplicate on every decoded LOD.
- Bounded cancellable latest-wins loader/search worker with stale-result rejection.
- Versioned neutral binary package and manifest comparison.
- Explicit neutral OBJ/MTL export of the edited working copy with staging, cancellation checks, reparse, structural comparison, atomic new-directory publication, and no source texture embedding.
- Synthetic unit tests, formatting, Clippy, Release workspace build, no-window app coverage, opt-in offscreen GPU coverage, and visible Release interaction smoke.
- Deterministic synthetic stress covering 16,800 real-app lasso gestures across every domain/depth/operation/shape combination; 400 committed and 400 cancelled sculpt strokes; four 2,048-update and four bounded 5,000-sample strokes; tool, mode, resize, and focus-loss interruption cases; and two repeatable 1,000-gesture mixed app sessions. Every checkpoint requires valid geometry, idle operators, bounded latency/pointer queues, exact cancellation, and total Undo-plus-Redo retained history within its configured budget.

## Incomplete gates

| Gate | State | Consequence |
|---|---|---|
| Private archive corpus | Not run | Archive READY cannot be claimed |
| Real PAC/PAM/PAMLOD parity | All four LODs of one supplied PAC exercised; corpus parity not run | Geometry support remains partial |
| Partial/Sparse DDS reconstruction | Incomplete | Some archive textures cannot decode |
| Native texture/material binding | Partial | One explicit supported 2D DDS can render; multi-material binding, arrays/cubes, reconstruction, and fallback transcode remain incomplete |
| PAC skin palette/PAB/PABC/morph | Incomplete | Character appearance parity not proven |
| Lab project | Incomplete | Camera/tool/history persistence is not published yet |
| Neutral export | OBJ/MTL implemented | GLB, skinning/material preservation, and private corpus re-import parity remain incomplete |
| Persistent cache | Incomplete | No cold/warm cache timing |
| Interaction stress | Synthetic app gate passes; representative soak still partial | The complete deterministic synthetic interaction matrix passes with bounded app containers and history; long-duration real-PAC input, OS working-set, UI-thread frame pacing, repeated window lifecycle, and GPU/device-loss soaks remain unrun |
| Performance targets | Partial instrumentation | The live inspector reports last/p95 CPU query and operator cost plus indexed candidates inspected, and one supplied PAC has CPU headless-edit timings; no representative corpus latency, FPS, GPU, or memory claim has been measured |
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

## Headless D3D12 renderer proof

The opt-in no-window GPU gate on 2026-08-30 created a Direct3D 12 `wgpu`
adapter/device and rendered a synthetic triangle through the same mesh draw
dispatcher used by the live viewport. It submitted Textured, Solid Faces,
Solid + Wire, Wireframe, Vertices, Wire + Vertices, and X-Ray with Normals and
Bounds across 640×480, 480×640, and 1280×720 targets, then submitted and read
back a final Solid + Wire frame: 22 frames total. The D3D12 validation scope was
empty and the readback contained non-background pixels. The same gate also
checks the live GPU-cache predicate: a different working-mesh identity with
equal geometry/topology revisions must not reuse the previous buffers. That
regression failed under the old revision-only predicate and passes with the
identity-aware key. No winit window or
surface was created. This proves offscreen command encoding, pipeline/resource
compatibility, aspect-dependent camera framing, and observable output; it is
not visual appearance, pointer latency, frame pacing, or real-PAC GPU proof.

## Headless interaction stress proof

The opt-in serial stress gate on 2026-08-30 ran 16,800 lasso gestures covering
Vertex/Edge/Face, Visible/X-Ray, Replace/Add/Subtract/Toggle, winding reversal,
self-intersection, repeated points, tiny/large polygons, and polygons leaving
the viewport. It also ran 100 committed and 100 cancelled strokes for each of
Grab, Smooth, Inflate, and Pinch, plus 2,048-update strokes, bounded
5,000-sample pointer streams, tool/mode changes, resize cancellation, and
focus-loss cancellation. Two independent 1,000-gesture mixed app sessions
finished with identical fingerprints and history metrics. The gate requires
valid topology after every checkpoint, no active gesture, an idle operator,
256-sample latency bounds, a 4,096-event pointer bound, exact cancelled-state
restoration, and retained Undo-plus-Redo history within a 4 KiB synthetic
budget. Building this proof found that moving an entry from Undo to Redo
subtracted it from the reported retained bytes even though the snapshots stayed
resident; accounting now covers both stacks and releases Redo bytes only when a
new commit discards them. This is deterministic synthetic app stress, not an OS
working-set, visible input, real-PAC, frame-pacing, or device-loss soak.

## Supplied PAC headless edit proof

A Release `headless-mesh` run on 2026-08-30 decoded one user-supplied PAC as
`rust_pac_section_4_pac40`. All four declared LODs were decoded using the same
section-to-LOD mapping as the production parser, and their counts matched:

| LOD | Vertices | Faces | Edit families passed |
|---|---:|---:|---:|
| 0 | 13,740 | 25,158 | 8/8 |
| 1 | 1,938 | 3,030 | 8/8 |
| 2 | 609 | 778 | 8/8 |
| 3 | 337 | 429 | 8/8 |

Move, Grab, Smooth, Inflate, Pinch, face Delete, Subdivide, and Duplicate each
ran on fresh working meshes for every LOD. Every operation changed the expected
fingerprint, created one history entry, passed invariants, restored the exact
baseline with Undo, and reproduced the exact edited fingerprint with Redo.
The single warm decode took 3.81 ms and all 32 complete operation/Undo/Redo
scenarios took 623.22 ms. LOD3 contains three source edges shared by four faces;
the production parser confirmed those incidences, and the Rust graph now
preserves them instead of imposing an unsupported two-face limit. A focused
synthetic regression failed under the old limit and passed after the correction.
SHA-256 and timestamp comparisons before and after the run confirmed the source
file was unchanged. These are single-file CPU edit/history measurements, not
full PAC/PAM/PAMLOD parity, visible selection or LOD-switch proof, live pointer
latency, FPS, GPU, or memory evidence.

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
