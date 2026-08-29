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

- `cdmw_archive`: read-only index discovery, path graph decoding, lazy PAZ reads, supported decompression/encryption, bounds, cancellation, and source verification hooks.
- `cdmw_asset_graph`: exact/relative/unambiguous relationship resolution. Ambiguous basenames never select a target.
- `cdmw_formats`: immutable decoded PAC/PAM/PAMLOD documents and structural fingerprints.
- `cdmw_texture`: DDS metadata, format, color-space, role, and resource-limit contracts.
- `cdmw_mesh`: the separate editable working document, generational handles, explicit edges/faces, invariants, generated provenance, revisioned draw snapshots, and bounded history.
- `cdmw_interaction`: modal operator ownership, exact snapshot correlation, deterministic selection shapes, selection operations, transforms, and sculpt algorithms.
- `cdmw_render_wgpu`: Direct3D 12 adapter/device/surface ownership, persistent mesh buffers, immutable snapshot upload, depth-aware solid/wire/point pipelines, camera uniforms, and egui composition.
- `cdmw_replay`: ordinal-addressed deterministic edit replays independent of runtime slot-map keys.
- `cdmw_oracle`: versioned neutral manifests, typed binary descriptors, staged new-directory publication, structural comparison, and reparsed OBJ/MTL export of the edited working copy.
- `cdmw_evidence`: SHA-256, redaction, source fingerprints, command evidence, and atomic new-file JSON publication.

## Source and working documents

Decoders produce immutable `MeshDocument` values. `WorkingMesh::from_document` creates separate generational slot maps. Source positions, faces, submesh identity, and element ordinals become explicit provenance. Topology operations create `Generated { operation }` provenance and never alter source bytes.

The current editable model is an explicit triangular face/edge graph. Every operation rebuilds reciprocal edge incidence, removes unreferenced vertices, recomputes normals where needed, rejects stale generational handles, validates face and edge invariants, and publishes a new topology/geometry revision.

## Modal transactions and history

One `OperatorController` owns one gesture. Begin snapshots the working mesh. Provisional calls use the same transform/sculpt algorithms committed by Confirm. Cancel restores the exact snapshot and creates no history. Confirm validates invariants and contributes one history entry. Topology commands mutate a private pre-operation clone, swap it into the live session only after invariant validation, and commit once; failure leaves geometry, topology, selection, revisions, and operation sequence unchanged. Subdivision and duplication select their generated faces deterministically. The history budget counts the full retained snapshot estimate across both Undo and Redo stacks; moving an entry between them does not make its memory disappear, while a new commit subtracts the Redo entries it actually discards.

## Renderer ownership

`WindowRenderer` owns the `wgpu` instance, D3D12 surface, adapter, device, queue, surface configuration, depth target, render pipelines, mesh buffers, camera uniform, and egui renderer. It consumes `DrawSnapshot` plus the application-owned view-projection matrix; it does not own topology, selection semantics, tools, history, relationship rules, camera input, or source-output policy.

`OrbitCamera` is the single camera owner shared by renderer submission and interaction projection. Mesh vertices remain in working-document coordinates. Orbit, pan, zoom, framing, standard views, and viewport aspect changes increment the camera or viewport generation so stale selection snapshots cannot apply. Resizing recreates the depth target but never rescales mesh axes independently.

Each immutable interaction snapshot constructs a 32-pixel screen-space grid and a projected-triangle BVH once for its geometry/camera/viewport generation. Click and brush queries visit only cells intersecting their shape; larger rectangle and lasso queries use the same index and fall back to iterating occupied cells when a coordinate range would be pathological. Visible mode queries only BVH leaves whose bounds contain the candidate point, interpolates the nearest triangle depth, and rejects occluded vertex, edge, or face representatives; X-Ray skips that filter. Candidate and triangle indices are restored to stable source order before predicates run. Query statistics expose inspected elements, total elements, and depth triangles without changing selection operations. No synchronous GPU readback occurs.

The renderer builds unique edge indices beside the triangle index buffer plus persistent normal-line and bounds-line vertex buffers, then selects among Textured, Solid Faces, Solid + Wire, Wireframe, Vertices, Wire + Vertices, and X-Ray pipelines without rebuilding the working mesh. Normal and bounds toggles submit their dedicated cyan/amber line pipelines independently of the base view mode. Geometry/topology revisions suppress unchanged GPU mesh uploads; camera-only and overlay changes update uniforms or draw choices without rebuilding geometry.

## Headless ownership

Headless verification does not substitute a mock renderer or a second edit implementation. `cdmw_mesh_lab` tests construct the real `LabApplication` and drive its camera, selection, edit, topology, cancel, history, and egui-frame methods without constructing a winit window. Its opt-in serial stress module uses the same private application entry points for the complete lasso matrix, per-tool commit/cancel/high-rate/interruption cases, and repeatable mixed sessions while asserting queue, latency, history, topology, and operator bounds at every checkpoint. `cdmw_render_wgpu::run_headless_render_smoke` creates a D3D12 adapter/device without a surface, calls the same mesh draw dispatcher as `WindowRenderer`, checks device validation scopes, and reads an offscreen texture back to the CPU. `cdmw_asset_probe headless-mesh` decodes one caller-selected PAC/PAM/PAMLOD read-only and executes the replay/controller edit path on fresh working documents so operation, Undo, and Redo fingerprints cannot pass by sharing mutated state. These paths remain proof harnesses; they do not own application behavior or establish visible appearance parity.

## UI and worker ownership

The application event thread owns winit, egui, dialogs, current UI state, camera, renderer submission, and immutable result adoption. A bounded raw-pointer queue preserves press, intermediate movement, and release across redraw coalescing. Lasso input starts with a 2-pixel sample threshold and deterministically halves retained intermediate points at the 4,096-point ceiling while preserving the first and newest point. One selection or edit gesture owns that stream; high-rate mesh changes publish one final GPU snapshot per drained event batch. Rolling CPU timing windows retain at most 256 samples. A named worker thread owns archive discovery, index parsing, payload reads, mesh decode, working-document construction, and archive filtering.

Requests use:

- a monotonically increasing generation;
- a cooperative cancellation token;
- a bounded request queue;
- a bounded result/progress queue;
- stale-result rejection before UI adoption.

A new request cancels the previous token. Progress uses nonblocking publication. Closing drops the sender, requests cancellation, and does not block the window close path waiting for the worker.

## Cache and output

Persistent cache publication is not implemented yet. Neutral oracle packages write binary arrays to a sibling staging directory, write a versioned manifest last, and rename the complete directory to a previously absent destination. Existing output is never overwritten.
