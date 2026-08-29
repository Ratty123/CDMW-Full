# CDMW Rust Mesh Lab

CDMW Rust Mesh Lab is a separate Windows-first diagnostic application for testing a native Rust archive, mesh, editing, and `wgpu` architecture. It does not replace the production Mesh Editor and is not linked from CDMW startup.

The current readiness state is **PARTIALLY READY**. The lab builds and launches, opens PA archive roots read-only, browses a virtualized result list, reads archive entries lazily, loads supported PAC/PAM/PAMLOD layouts, renders geometry and a supported explicit 2D DDS reference through Direct3D 12, provides a navigable aspect-correct viewport, routes pointer selection and interactive editing through an in-memory generational mesh, and exports the edited copy as a validated neutral OBJ/MTL directory. Full multi-material/Partial DDS appearance, PAC skin/appearance parity, depth-aware visible-only picking, versioned lab projects, representative performance evidence, and private real-game parity remain incomplete. See [READINESS.md](READINESS.md).

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
- **Viewport** uses `wgpu` with Direct3D 12 on Windows, an aspect-aware shared camera matrix, and a depth target. An explicit decoded DDS reference is uploaded directly when its supported 2D layout is unambiguous; the shader remains an explicit material approximation and currently binds one texture.
- **Inspector** reports format, LOD, counts, parser, warnings, archive flags, and entry sizes.
- **Selection** routes Click, Brush, Rectangle, and Lasso gestures through the same revision-stamped X-Ray projection for Vertex, Edge, and Face domains. A persistent 32-pixel screen grid limits local queries to intersecting cells instead of rescanning every projected element. Replace, Add, Subtract, and Toggle apply once to the complete gesture, including fast drags retained by the bounded raw-input queue; pathological long lassos are deterministically compacted while preserving the press and release points.
- **Interactive Edit / Sculpt** provides Move, Rotate, and Scale gizmos plus Grab, Smooth, Inflate, and Pinch brushes. Each drag previews locally, mouse release commits one undo entry, and Esc, resize, or focus loss rolls the gesture back. Face deletion, midpoint subdivision, and duplication validate a private working draft before replacing the live mesh; subdivision and duplication select their generated faces. Undo and Redo remain one-shot commands. Disabled controls state why they are unavailable.
- **Export Neutral OBJ…** asks for a parent folder, refuses the selected game/archive root, stages and reparses the edited mesh on the worker, verifies its structural fingerprint, then publishes a new `cdmw-rust-mesh-export` directory atomically. Existing output is never replaced and source textures are not embedded.

### Viewport controls

- Hold **RMB** and drag to orbit.
- Hold **MMB** and drag to pan.
- Use the **mouse wheel** to zoom.
- Press **F** to frame the selection, or the complete mesh when nothing is selected.
- Use **Frame All**, **Frame Selected**, or Front/Back/Left/Right/Top/Bottom for exact camera placement.
- Choose Textured, Solid Faces, Solid + Wire, Wireframe, Vertices, Wire + Vertices, or X-Ray from **Preview mode**.
- Choose Click, Brush, Rectangle, or Lasso, then drag in the viewport. Brush radius and sculpt strength are adjustable in the inspector.
- Select Move, Rotate, or Scale and drag the visible axis/ring/center gizmo. Select Grab, Smooth, Inflate, or Pinch and drag over eligible vertices.
- Press **Esc** to cancel an active selection or edit gesture.
- The inspector reports the last and rolling 256-sample p95 CPU selection/edit time. Selection also reports how many indexed candidates were inspected out of the complete projected element count; these are CPU callback measurements, not frame time or GPU latency.

Selection is currently X-Ray: element candidates behind the visible surface remain eligible. The asynchronous depth-aware visible-only route is still incomplete and is not represented as working.

## Asset probe

The pure-Rust probe can inspect an index, decode a mesh into a neutral binary package, inspect DDS metadata, and compare two neutral manifests:

```powershell
Set-Location .\tools\rust_mesh_lab
cargo run --release -p cdmw_asset_probe -- inventory "D:\Game\pack\archive.pamt"
cargo run --release -p cdmw_asset_probe -- decode-mesh "D:\Assets\example.pam" "$env:TEMP\cdmw-rust-oracle"
cargo run --release -p cdmw_asset_probe -- inspect-texture "D:\Assets\example.dds"
cargo run --release -p cdmw_asset_probe -- compare expected\manifest.json actual\manifest.json
```

Neutral packages keep numeric arrays in binary files, include typed descriptors and SHA-256 hashes, and never require absolute source paths in the manifest.

## Cache and evidence

No persistent decoded-asset cache is published yet. Build output stays under `tools/rust_mesh_lab/target/` and is ignored. Oracle output is written only to a destination explicitly selected by the caller and refuses to replace an existing package.

Use a system temporary directory for private evidence. Do not place game assets, decoded buffers, screenshots, or private path lists in the repository.

## Validation

```powershell
.\scripts\test_rust_mesh_lab.ps1
```

This runs formatting, Clippy with warnings denied, workspace tests, and a Release workspace build. `cargo deny`, `cargo audit`, and fuzzing are separate optional gates when installed.

## Troubleshooting

- **No D3D12 adapter:** update the display driver or run on a Windows device with Direct3D 12. The lab currently fails closed rather than silently switching the production proof class.
- **Mesh layout unsupported:** the parser did not find a locally proven layout. The source is not treated as decoded and remains unchanged.
- **Archive open fails:** select the archive package root containing `.pamt` indexes and numbered `.paz` files. `cdmods` is deliberately excluded.
- **Partial DDS:** metadata inspection works, but Partial/Sparse DDS reconstruction and GPU fallback decode are not complete in Rust yet.
- **Large archive search:** submit the query with **Search**. Filtering runs on the bounded worker and the UI shows at most 20,000 matching row identities while reporting the full match count.
