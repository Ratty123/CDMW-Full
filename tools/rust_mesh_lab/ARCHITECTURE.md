# Rust Mesh Lab architecture

## Isolation

The lab is a standalone Cargo workspace under `tools/rust_mesh_lab`. Production CDMW does not import it, launch it, package it, or depend on its crates. The Vortice Mesh Editor remains unchanged.

```text
cdmw_archive ──────┐
                   v
cdmw_asset_graph  cdmw_formats ──> cdmw_texture
                         |
                         v
                     cdmw_mesh
                         |
                         v
                  cdmw_interaction
                         |
                         v
                 cdmw_render_wgpu
                         |
                         v
                  cdmw_mesh_lab

cdmw_replay ──> cdmw_interaction + cdmw_mesh
cdmw_oracle ──> cdmw_formats + cdmw_mesh + cdmw_evidence
cdmw_asset_probe ──> archive/formats/texture/oracle
```

## Crate responsibilities

- `cdmw_archive`: read-only index discovery, path graph decoding, lazy PAZ reads, Stored/LZ4 decoding, bounded PATHC-backed Partial DDS reconstruction, validated Sparse DDS zero padding, supported encryption, cancellation, and source verification hooks.
- `cdmw_asset_graph`: exact/relative/unambiguous relationship resolution. Ambiguous basenames never select a target.
- `cdmw_formats`: immutable decoded PAC/PAM/PAMLOD documents and structural fingerprints.
- `cdmw_texture`: bounded material-sidecar texture-reference and typed/unknown parameter parsing, with original attributes/raw values and explicit/incomplete confidence, plus DDS metadata, format, role-authoritative color-space, mip planning, and resource-limit contracts.
- `cdmw_mesh`: the separate editable working document, generational handles, explicit edges/faces, invariants, generated provenance, revisioned draw snapshots, and bounded history.
- `cdmw_interaction`: modal operator ownership, exact snapshot correlation, deterministic selection shapes, selection operations, transforms, and sculpt algorithms.
- `cdmw_render_wgpu`: Direct3D 12 adapter/device/surface ownership, persistent mesh buffers, immutable snapshot upload, depth-aware solid/wire/point pipelines, camera uniforms, and egui composition.
- `cdmw_replay`: ordinal-addressed deterministic edit replays independent of runtime slot-map keys.
- `cdmw_oracle`: versioned neutral manifests, typed binary descriptors, staged new-directory publication, structural comparison, and reparsed OBJ/MTL export of the edited working copy.
- `cdmw_evidence`: SHA-256, redaction, source fingerprints, command evidence, and atomic new-file JSON publication.

## Source and working documents

Decoders produce immutable `MeshDocument` values. `WorkingMesh::from_document_lod` creates separate generational slot maps for one decoded LOD; `from_document` retains the first-LOD contract for existing callers. Each independently constructed working mesh gets an in-process identity that survives its draft/history clones and travels with draw snapshots; this identity does not enter deterministic geometry fingerprints. PAC decoding pairs sections 4, 3, 2, and 1 only with descriptor levels 0, 1, 2, and 3, requires a proven LOD0, and reports unsupported declared levels rather than relabeling a lower LOD. Source positions, faces, submesh identity, and element ordinals become explicit provenance. Topology operations create `Generated { operation }` provenance and never alter source bytes.

The current editable model is an explicit triangular face/edge graph. Every operation rebuilds reciprocal edge incidence, removes unreferenced vertices, rejects stale generational handles, validates face and edge invariants, and publishes a new topology/geometry revision. A position deformation recomputes normals only for vertices in faces incident to a changed vertex, including all adjacent-face contributions for that one-ring; disconnected and otherwise out-of-scope decoded normals stay byte-exact. Topology-only Delete, Subdivide, and Duplicate preserve normals on surviving source vertices, while subdivision interpolates generated midpoint normals. Source non-manifold edges retain their complete incident-face list; more than two faces is not itself an invalid handle graph. Empty incidence, repeated face vertices, and references to missing elements remain errors.

## Modal transactions and history

One `OperatorController` owns one gesture. Begin snapshots the working mesh. Provisional calls use the same transform/sculpt algorithms committed by Confirm. Pinch projects the pointer onto a camera-facing plane through the eligible vertices' mean depth; positive strength therefore reduces their distance from the visible brush center instead of pulling toward their own centroid. Cancel restores the exact snapshot and creates no history. Confirm validates invariants and contributes one history entry. Topology commands mutate a private pre-operation clone, swap it into the live session only after invariant validation, and commit once; failure leaves geometry, topology, selection, revisions, and operation sequence unchanged. Subdivision and duplication select their generated faces deterministically. The history budget counts the full retained snapshot estimate across both Undo and Redo stacks; moving an entry between them does not make its memory disappear, while a new commit subtracts the Redo entries it actually discards.

The loader prepares every decoded LOD's working mesh before adoption. The app keeps one active mesh/history pair and parks the other LOD sessions without cloning them on a switch. A switch cancels an unfinished gesture, preserves each LOD's selection and history, retains the camera, invalidates interaction projection, and publishes the new snapshot. The 512 MiB retained-history budget is divided across the loaded sessions, not multiplied by the LOD count.

## Renderer ownership

`WindowRenderer` owns the `wgpu` instance, D3D12 surface, adapter, device, queue, surface configuration, depth target, render pipelines, mesh buffers, camera uniform, uploaded material textures, validated optional preview factors, fixed role defaults, the active LOD's material-to-bind-group map, and egui renderer. It consumes `DrawSnapshot` plus the application-owned view-projection matrix; it does not own topology, selection semantics, tools, history, relationship rules, parameter-name interpretation, camera input, or source-output policy. The shared DDS upload helper maps each supported storage format together with the resolved role's color space: color roles select an sRGB view, technical roles select linear, and a requested sRGB view with no native format fails closed. Switching LODs rebuilds only the owner/role/factor bind sets from loader-proven submesh names; it does not re-upload DDS bytes.

`OrbitCamera` is the single camera owner shared by renderer submission and interaction projection. Mesh vertices remain in working-document coordinates. Orbit, pan, zoom, framing, standard views, and viewport aspect changes increment the camera or viewport generation so stale selection snapshots cannot apply. Resizing recreates the depth target but never rescales mesh axes independently.

Each immutable interaction snapshot constructs a 32-pixel screen-space grid and a projected-triangle BVH once for its geometry/camera/viewport generation. Click and brush queries visit only cells intersecting their shape; larger rectangle and lasso queries use the same index and fall back to iterating occupied cells when a coordinate range would be pathological. Visible mode queries only BVH leaves whose bounds contain the candidate point, interpolates the nearest triangle depth, and rejects occluded vertex, edge, or face representatives; X-Ray skips that filter. Candidate and triangle indices are restored to stable source order before predicates run. Query statistics expose inspected elements, total elements, and depth triangles without changing selection operations. No synchronous GPU readback occurs.

Each draw snapshot carries a material owner parallel to its triangles. The renderer groups even noncontiguous triangle indices into deterministic owner ranges, derives one tangent/handedness basis from the current positions, normals, UVs, and topology, builds unique wire indices beside that material-batched triangle buffer, and retains persistent normal-line and bounds-line vertex buffers. Textured Solid switches fixed base/normal/packed-material/roughness/metalness/occlusion/emissive bind sets per owner range. The explicit approximation reconstructs tangent-space normal Z, reads `_materialTexture` G roughness and B metalness, then lets separate roughness and metalness R channels override only their corresponding packed value. Occlusion R modulates the simple ambient diffuse/metal terms, roughness controls direct and environment-specular terms, and a bound emissive texture is multiplied by the loader-proven optional emissive color/intensity factor. The loader recognizes the same explicit emissive parameter-name families as the current native material semantics, accepts hex RGB/RGBA color and finite float intensity clamped to 0–32, maps them by submesh/material identity for every LOD, and leaves only a conflicting or invalid factor unbound. A role with no authoritative binding uses its neutral default, while a completely unresolved owner keeps the normal-colored placeholder. Specular, gloss, alpha, layered/dye, and other scalar/vector parameters remain preserved but unsampled rather than being reinterpreted as packed data. Same-owner texture conflicts are isolated by role in the loader, and renderer-level duplicate-role/factor conflicts clear the active map rather than retaining bindings from the previous LOD. Solid Faces, Solid + Wire, Wireframe, Vertices, Wire + Vertices, and X-Ray keep their existing untextured draw paths. Normal and bounds toggles submit their dedicated cyan/amber line pipelines independently of the base view mode. Face selections use translucent triangle fills; per-triangle outline strokes stop after 128 selected faces so a dense Brush result cannot turn hundreds of shared edges into radiating overlay clutter. Working-mesh identity plus geometry/topology revisions suppress unchanged GPU mesh uploads, so loading another file or switching LODs cannot reuse buffers merely because both meshes have revision 1. Camera-only and overlay changes update uniforms or draw choices without rebuilding geometry.

## Headless ownership

Headless verification does not substitute a mock renderer or a second edit implementation. `cdmw_mesh_lab` tests construct the real `LabApplication` and drive its camera, selection, edit, topology, cancel, per-LOD adoption/switch/history, and egui-frame methods without constructing a winit window. A painted-UI fixture takes control coordinates from egui's clipped output, feeds UI actions after the frame at the same boundary as the runtime, and mirrors pointer events through the bounded capture queue. It covers short-window scrolling, controls and menus, preview/LOD state, texture/material-parameter provenance, all selection and edit tools, high-DPI camera input, topology, history, disabled states, resize/Esc cancellation, and the dense-face fill-without-outline draw contract. Loader fixtures exercise real temporary archive/PATHC/sidecar/DDS layouts and require bounded Partial DDS reconstruction through the application boundary, unchanged source files, visible archive-decode provenance, explicit-over-fallback, missing, same-role conflict isolation, seven-role preview resolution, typed/unknown parameter preservation, unique emissive factor resolution, factor-conflict isolation, unsupported-role warnings, distinct-owner multi-texture, and reordered-LOD behavior. The archive crate additionally compares reconstructed Partial and Sparse DDS bytes with exact current-CDMW SHA-256 oracles and rejects missing PATHC, truncated chunks, excessive record counts, and active output-limit violations. Its opt-in serial stress module uses the same private application entry points for the complete lasso matrix, per-tool commit/cancel/high-rate/interruption cases, and repeatable mixed sessions while asserting queue, latency, history, topology, and operator bounds at every checkpoint. `cdmw_render_wgpu::run_headless_render_smoke` creates a D3D12 adapter/device without a surface, uploads eight synthetic DDS files through the same helper as `WindowRenderer`, composes seven roles on one range beside a second base-colored range, switches both through the live draw dispatcher, checks device validation scopes, and compares CPU readbacks from unresolved, base-only, one-extra-role, explicit-emissive-factor, and fully composed passes. It fails unless base color, normal, packed material, roughness, metalness, occlusion, and emissive each change rendered pixels independently and the explicit emissive color/intensity factor changes pixels again. `cdmw_asset_probe headless-mesh` decodes one caller-selected PAC/PAM/PAMLOD read-only and executes all eight replay/controller edit families on every decoded LOD. Each scenario starts from an untouched baseline and rejects out-of-scope position or normal changes before checking exact operation, Undo, and Redo fingerprints. These paths remain proof harnesses; they do not own application behavior or establish visible real-game appearance parity.

## UI and worker ownership

The application event thread owns winit, egui, dialogs, current UI state, camera, renderer submission, and immutable result adoption. The Inspector owns an independent vertical scroll area so window height does not remove lower authoring controls. A bounded raw-pointer queue preserves press, intermediate movement, and release across redraw coalescing. Lasso input starts with a 2-pixel sample threshold and deterministically halves retained intermediate points at the 4,096-point ceiling while preserving the first and newest point. One selection or edit gesture owns that stream; high-rate mesh changes publish one final GPU snapshot per drained event batch. Rolling CPU timing windows retain at most 256 samples. A named worker thread owns archive discovery, index parsing, payload reads, sibling `meta/0.pathc` parsing and archive DDS reconstruction under the caller's active byte limit, mesh decode, working-document construction, archive filtering, material-sidecar parsing, asset-relation resolution, and DDS reads. Direct files check only deterministic adjacent/`modelproperty` same-stem paths and bounded ancestors of an explicit relative DDS path; they do not recursively scan an arbitrary user directory. Archive lookups build targeted indexes for the requested basename, and a duplicate or ambiguous result never selects a payload.

Requests use:

- a monotonically increasing generation;
- a cooperative cancellation token;
- a bounded request queue;
- a bounded result/progress queue;
- stale-result rejection before UI adoption.

A new request cancels the previous token. Progress uses nonblocking publication. Closing drops the sender, requests cancellation, and does not block the window close path waiting for the worker.

## Cache and output

Persistent cache publication is not implemented yet. Neutral oracle packages write binary arrays to a sibling staging directory, write a versioned manifest last, and rename the complete directory to a previously absent destination. Existing output is never overwritten.
