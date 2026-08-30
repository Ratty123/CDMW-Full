# CDMW Rust Mesh Lab

CDMW Rust Mesh Lab is a separate Windows-first diagnostic application for testing a native Rust archive, mesh, editing, and `wgpu` architecture. It does not replace the production Mesh Editor and is not linked from CDMW startup.

The current readiness state is **PARTIALLY READY**. The lab builds and launches, opens PA archive roots read-only, browses a virtualized result list, reads archive entries lazily, reconstructs bounded supported 2D Partial DDS entries from sibling `meta/0.pathc` metadata and Sparse DDS entries by validated zero padding, loads supported PAC/PAM/PAMLOD layouts, resolves same-stem material sidecars and authoritative per-submesh DDS relationships for base color, normal, packed material, separate roughness/metalness/occlusion, emissive, specular/glossiness, and opacity preview roles, preserves typed and unknown material parameters, applies uniquely owned explicit roughness/metalness/specular factors to their material ranges, emissive color/intensity when an emissive texture is bound, and explicit alpha-test enable state as an approximate cutout policy, renders geometry through Direct3D 12, provides a navigable aspect-correct viewport, routes X-Ray and depth-aware Visible selection plus interactive editing through an in-memory generational mesh, and exports the edited copy as a validated neutral OBJ/MTL directory. Its app flow, archive reconstruction boundary, relationship failures, material-parameter Inspector, multi-role DDS upload, and offscreen D3D12 renderer can also be exercised without creating a window. Partial PAR, DDS arrays/cubes and fallback transcoding, layered/dye and blended-alpha material composition, remaining scalar/vector sampling, PAC skin/appearance parity, versioned lab projects, representative performance evidence, and private real-game parity remain incomplete. See [READINESS.md](READINESS.md).

## Asset-safety notice

Crimson Desert files are user-supplied local assets. The lab opens archive indexes, PAZ payloads, and direct meshes read-only. Editing occurs only in a separate in-memory working document. It does not write PAC, PAM, PAMLOD, PAMT, or PAZ files, does not upload data, and contains no telemetry.

## Build

From the repository root:

```powershell
.\scripts\build_rust_mesh_lab.ps1 -Release
```

Direct Cargo equivalent:

```powershell
Set-Location .\tools\rust_mesh_lab
cargo build --workspace --release
```

Rust 1.95.0 with the MSVC target is pinned in `rust-toolchain.toml`. Dependencies are locked by `Cargo.lock`.

## Launch

Launch the empty lab:

```powershell
.\scripts\run_rust_mesh_lab.ps1
```

Open an archive root:

```powershell
.\scripts\run_rust_mesh_lab.ps1 -ArchiveRoot "D:\Games\Crimson Desert"
```

Open an extracted mesh:

```powershell
.\scripts\run_rust_mesh_lab.ps1 -MeshPath "D:\Assets\example.pac"
```

The application shows the actual executable path before launch. It does not require administrator rights.

## User interface

- **Archive / Assets** opens an archive root or extracted mesh, searches virtual paths off the UI thread, and virtualizes the displayed rows.
- **Viewport** uses `wgpu` with Direct3D 12 on Windows, an aspect-aware shared camera matrix, and a depth target. Persistent GPU line buffers provide optional cyan vertex normals and an always-readable amber mesh-bounds box. For direct files it checks an adjacent or `modelproperty` same-stem sidecar; for archive files it derives the same family path and resolves it through the asset index. Archive DDS payloads pass through the bounded Stored/LZ4/Partial/Sparse decoder before DDS metadata validation and upload. Explicit sidecar parameters outrank decoded-name fallback. Each triangle retains its material owner, noncontiguous faces are batched by owner, and distinct supported 2D DDS files bind only to the matching submesh ranges for the active LOD. The explicitly labelled approximate shader samples base color, reconstructs tangent-space normal Z, reads `_materialTexture` G as roughness and B as metalness, lets separate roughness and metalness R channels override only those packed values, applies occlusion R to its ambient terms, and multiplies bound emissive texture data by a uniquely resolved explicit hex emissive color and finite 0–32 intensity when present. A bound linear Specular or legacy Glossiness/Smoothness texture enters the production preview's one shared response slot, raises only metallic reflectance, and contributes exactly nothing to a dielectric; Glossiness keeps its source provenance and is not reinterpreted as an inverted roughness channel because the production selector declares no such component contract. Explicit roughness factors nudge rather than flatten source-map variation, metalness factors may raise the metal response, and specular factors follow the same metallic-only boundary. An authoritative linear Opacity texture supplies approximate red-channel coverage when an explicit `AlphaTest`/`AlphaClip`/`AlphaCutout`/`Cutout` family parameter is enabled; otherwise base-color alpha supplies coverage. The current production-preview threshold for an explicit alpha-test material is 0.08. Binding the same Opacity texture to an opaque material has no render effect, and true blend transparency remains unimplemented. Float and packed Byte4 values follow the current native parameter-name families, clamp to 0–1, retain authored-zero presence, and bind by material owner on every LOD. Missing, duplicate, ambiguous, unmatched, or same-preview-slot conflicting relationships keep only the affected roles on defaults; conflicting factor values leave only that factor unbound. Blended alpha, layered/dye, and remaining scalar/vector parameters are preserved and reported but not sampled. Role-aware upload maps base/emissive data to sRGB and technical data to linear even when a DDS header disagrees. It does not claim exact game-shader, layered-material, general scalar/vector, or transparency parity.
- **Inspector** reports format, editable/declared LOD counts, parser, warnings, archive flags, entry sizes, the archive decode method (Stored, Partial raw, Partial DDS, Sparse DDS, or LZ4), and every loaded material texture's role, requested reference, sidecar parameter/path, resolution method, owning material ranges by LOD, format, color space, and mip count. It also reports prepared emissive, roughness/metalness/specular, and alpha-cutout factors and provides a collapsed list of all preserved typed or unknown parameters with original tag, name, raw value, attributes, wrapper/material owner, explicit/incomplete confidence, LOD ownership, and sampled-versus-unbound status. **Editable LOD** switches between worker-prepared LODs while preserving each LOD's geometry, selection, and Undo/Redo history; texture and factor ownership are remapped by submesh name for that LOD, and the active counts follow the edited mesh rather than summing every source LOD. The existing 512 MiB history budget is divided across the loaded LOD sessions.
- **Selection** routes Click, Brush, Rectangle, and Lasso gestures through the same revision-stamped projection for Vertex, Edge, and Face domains. **Visible** depth-tests candidates against a projected-triangle BVH while **X-Ray** includes occluded candidates; both use a persistent 32-pixel screen grid so local queries inspect bounded cells instead of rescanning every projected element. Replace, Add, Subtract, and Toggle apply once to the complete gesture, including fast drags retained by the bounded raw-input queue; pathological long lassos are deterministically compacted while preserving the press and release points. Dense face selections keep their translucent fill but stop outlining every triangle after 128 faces, avoiding radiating overlay clutter.
- **Interactive Edit / Sculpt** provides Move, Rotate, and Scale gizmos plus Grab, Smooth, Inflate, and Pinch brushes. Pinch uses the pointer as its center on a camera-facing plane through the affected vertices' mean depth, so even one eligible vertex moves toward the visible brush. Each drag previews locally, mouse release commits one undo entry, and Esc, resize, or focus loss rolls the gesture back. Position edits leave every out-of-scope position exact and recompute normals only for the affected one-ring; face deletion, midpoint subdivision, and duplication preserve decoded normals on surviving source vertices while validating a private working draft before replacing the live mesh. Subdivision and duplication select their generated faces. Undo and Redo remain one-shot commands. Disabled controls state why they are unavailable, and the Inspector scrolls independently after a shorter-window resize.
- **Export Neutral OBJ…** asks for a parent folder, refuses the selected game/archive root, stages and reparses the active LOD's edited mesh on the worker, verifies its structural fingerprint, then publishes a new `cdmw-rust-mesh-export` directory atomically. Existing output is never replaced and source textures are not embedded.

### Viewport controls

- Hold **RMB** and drag to orbit.
- Hold **MMB** and drag to pan.
- Use the **mouse wheel** to zoom.
- Press **F** to frame the selection, or the complete mesh when nothing is selected.
- Use **Frame All**, **Frame Selected**, or Front/Back/Left/Right/Top/Bottom for exact camera placement.
- Use **Editable LOD** to inspect and edit another proven LOD without losing the previous LOD's changes. Switching keeps the camera and cancels any unfinished gesture before parking that LOD's session. PAC levels use only the proven section 4→LOD0 through section 1→LOD3 mapping; no PAC/PAM/PAMLOD writeback is implied.
- Choose Textured, Solid Faces, Solid + Wire, Wireframe, Vertices, Wire + Vertices, or X-Ray from **Preview mode**, then independently toggle **Normals** and **Bounds**. **Bones** remains visibly disabled with its missing-skeleton reason until PAB/PAC binding is decoded.
- Choose Click, Brush, Rectangle, or Lasso, then drag in the viewport. Brush radius and sculpt strength are adjustable in the inspector.
- **Visible** is the default and rejects candidates behind the nearest projected triangle at their representative point; choose **X-Ray** to include occluded candidates. Sculpt brushes always use the visible-only route so a surface stroke does not also modify the back side.
- Select Move, Rotate, or Scale and drag the visible axis/ring/center gizmo. Select Grab, Smooth, Inflate, or Pinch and drag over eligible vertices.
- Press **Esc** to cancel an active selection or edit gesture.
- The inspector reports the last and rolling 256-sample p95 CPU selection/edit time. Selection also reports how many indexed candidates were inspected out of the complete projected element count; these are CPU callback measurements, not frame time or GPU latency.

Visible selection is CPU-local and nonblocking with respect to GPU readback: each candidate queries a bounded projected-triangle BVH and compares interpolated depth. It uses the current point-based vertex/edge/face selection representatives and double-sided triangle occlusion; a pixel-ID selection pass and full region/triangle overlap semantics are not implemented.

## Asset probe

The pure-Rust probe can inspect an index, decode a mesh into a neutral binary package, inspect DDS metadata, and compare two neutral manifests:

```powershell
Set-Location .\tools\rust_mesh_lab
cargo run --release -p cdmw_asset_probe -- inventory "D:\Game\pack\archive.pamt"
cargo run --release -p cdmw_asset_probe -- decode-mesh "D:\Assets\example.pam" "$env:TEMP\cdmw-rust-oracle"
cargo run --release -p cdmw_asset_probe -- headless-mesh "D:\Assets\example.pac"
cargo run --release -p cdmw_asset_probe -- inspect-texture "D:\Assets\example.dds"
cargo run --release -p cdmw_asset_probe -- compare expected\manifest.json actual\manifest.json
```

Neutral packages keep numeric arrays in binary files, include typed descriptors and SHA-256 hashes, and never require absolute source paths in the manifest.

`headless-mesh` decodes the supplied file read-only, then runs Move, Grab, Smooth, Inflate, Pinch, face Delete, Subdivide, and Duplicate on fresh working meshes for every decoded LOD. Every scenario names its `lod_level`, must make the intended change, preserve positions and normals outside the operation's permitted scope, create one history entry, pass mesh invariants, restore the exact baseline through Undo, and reproduce the exact edited fingerprint through Redo. Top-level vertex/face counts retain the first decoded LOD's counts. Its JSON timings measure CPU decode/edit/history work; they are not pointer-latency, frame-rate, or visual-parity measurements.

## Cache and evidence

No persistent decoded-asset cache is published yet. Build output stays under `tools/rust_mesh_lab/target/` and is ignored. Oracle output is written only to a destination explicitly selected by the caller and refuses to replace an existing package.

Use a system temporary directory for private evidence. Do not place game assets, decoded buffers, screenshots, or private path lists in the repository.

## Validation

```powershell
.\scripts\codex_check.ps1 -Area rust-mesh-lab-unit
.\scripts\codex_check.ps1 -Area rust-mesh-lab-gpu
.\scripts\codex_check.ps1 -Area rust-mesh-lab-stress
```

The unit gate runs formatting, Clippy with warnings denied, workspace tests, and a Release workspace build. Its no-window UI fixture discovers coordinates from egui's clipped draw output, then uses the real painted controls plus the live bounded raw-pointer route for menus, preview and camera settings, LOD switching, texture and material-parameter provenance, selection, every edit tool, topology, history, high-DPI navigation, resize, and cancellation. The GPU gate creates no window: it requires a D3D12 adapter, uploads twelve synthetic DDS files through the windowed renderer's live helper, composes ten sampled roles across two independently based material ranges, reuses the mesh draw path for all seven preview modes plus Normals and Bounds, renders wide, tall, and 4:3 targets, checks `wgpu` validation scopes, and reads back unresolved, base-only, one-extra-role, metallic and dielectric Specular-map, metallic and dielectric Glossiness-map, opaque and cutout Opacity-map, emissive-factor, roughness-factor, metalness-factor, metalness-plus-specular-factor, and fully composed frames during a 40-frame pass. It fails unless geometry is visible; base color, normal, packed material, separate roughness, separate metalness, occlusion, emissive, Specular, Glossiness, and cutout Opacity each change rendered pixels independently where applicable; both Specular and Glossiness comparisons change metallic pixels while leaving dielectric pixels identical; the Opacity comparison removes visible pixels only when cutout is enabled and leaves the opaque frame byte-identical; explicit emissive color/intensity changes pixels again; and roughness, metalness, and specular factors each produce another independent pixel difference. The stress gate also creates no window and serially drives the real `LabApplication` through 16,800 lasso gestures, 400 committed and 400 cancelled sculpt strokes, long and 5,000-sample high-rate strokes, tool/mode/resize/focus interruptions, and two deterministic 1,000-gesture mixed sessions. It asserts mesh invariants, idle operators, bounded pointer/latency queues, exact cancellation, and the configured total Undo/Redo history budget. These gates prove CPU/offscreen execution and control routing, not visible usability, OS working-set stability, or real-game appearance parity. `cargo deny`, `cargo audit`, and fuzzing are separate optional gates when installed.

## Troubleshooting

- **No D3D12 adapter:** update the display driver or run on a Windows device with Direct3D 12. The lab currently fails closed rather than silently switching the production proof class.
- **Mesh layout unsupported:** the parser did not find a locally proven layout. The source is not treated as decoded and remains unchanged.
- **Archive open fails:** select the archive package root containing `.pamt` indexes and numbered `.paz` files. `cdmods` is deliberately excluded.
- **No skin texture:** the supplied PAC may not contain texture names. Keep its `.pac_xml` material sidecar and referenced DDS files in their extracted virtual-path layout, or open the archive root. If no sidecar exists, an owner cannot match a decoded submesh, or different paths claim the same material range, the Inspector intentionally keeps that range on the approximation and explains why.
- **Partial or Sparse DDS fails:** supported 2D archive DDS entries reconstruct only when their validated header, dimensions, mip plan, declared sizes, and active byte limits agree. Partial DDS also requires the exact virtual path in the sibling `meta/0.pathc`; missing, ambiguous, truncated, oversized, array/cube, or otherwise unsupported data fails closed without changing either source file. Partial PAR and GPU fallback transcoding are not implemented.
- **Large archive search:** submit the query with **Search**. Filtering runs on the bounded worker and the UI shows at most 20,000 matching row identities while reporting the full match count.
