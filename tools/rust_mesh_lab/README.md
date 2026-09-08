# CDMW Rust Mesh Lab

Product labels use Preview and Mesh Editor, with neutral Layer, Morph Profile,
Morph and Preset defaults. Internal renderer and protocol identities remain unchanged.
Particle BC4/R8 masks use linear sampling; RGB mask coverage is converted back from
sRGB only when the uploaded view actually uses sRGB. The synthetic particle pixel
check covers BC4 half-intensity and authored colour alongside the existing RGBA cases.

`cdmw_mesh_lab.exe` has standalone diagnostic and CDMW-managed modes. The default standalone
**Rust Mesh Lab** is a Windows-first diagnostic application for testing the
native Rust archive, mesh, editing, and `wgpu` architecture. In CDMW-managed
modes, the same executable owns both production **Mesh Editor** authoring and
**Archive Preview**, including Model Library, New Item and specialist previews.
It creates an undecorated child inside CDMW without importing Rust crates into
Python. Preview exposes viewport controls; authoring exposes the full editor.

The current readiness state is **PARTIALLY READY**. The lab builds and launches, opens PA archive roots read-only, browses a virtualized result list, reads archive entries lazily, reconstructs bounded supported 2D Partial DDS entries from sibling `meta/0.pathc` metadata and Sparse DDS entries by validated zero padding, loads supported PAC/PAM/PAMLOD layouts, resolves same-stem material sidecars and authoritative per-submesh DDS relationships for base color, normal, packed material, separate roughness/metalness/occlusion, emissive, independent RGB Specular and red-channel Glossiness/Smoothness, explicit-cutout opacity, explicit global height, hair Flow, and layer-mask diagnostic preview roles, preserves typed and unknown material parameters, applies uniquely owned explicit roughness/metalness/specular/height-scale factors to their material ranges, emissive color/intensity with or without an emissive texture, explicit alpha-test enable state as an approximate cutout policy, hair anisotropy only when both Flow and a proven hair/fur shader family own the range, and production-backed R/B channel selection for color-blending/detail masks, renders geometry through Direct3D 12, provides a navigable aspect-correct viewport with fifteen geometry/material preview modes including Game Outdoor lighting and texture-independent Part ID ownership colors, routes X-Ray and depth-aware Visible selection plus interactive editing through an in-memory generational mesh, and exports the edited copy as a validated neutral OBJ/MTL directory. Its app flow, archive reconstruction boundary, relationship failures, material-parameter Inspector, multi-role DDS upload, and offscreen D3D12 renderer can also be exercised without creating a window. Partial PAR, DDS arrays/cubes and fallback transcoding, actual layered/dye and blended-alpha material composition, non-global displacement/layer semantics, remaining scalar/vector sampling, PAC skin/appearance parity, versioned lab projects, representative performance evidence, and private real-game parity remain incomplete. See [READINESS.md](READINESS.md).

## Imported materials

Imported glTF metallic-roughness materials use their authored PBR values,
GGX highlights, and HDR studio reflections with one final tone map. Neutral
studio lights preserve silver and gold hues; inferred material categories do
not override these imported values. Emission retains its authored strength.
The studio is procedural; Sketchfab environment maps, refraction, and bloom
are not reproduced by this preview.

## Asset-safety notice

Crimson Desert files are user-supplied local assets. Standalone Rust Mesh Lab
opens archive indexes, PAZ payloads, and direct meshes read-only; editing occurs
only in a separate in-memory working document. Integrated mode edits CDMW's
disposable shadow session and hands an accepted revision back to CDMW for its
existing validated package or overlay paths. Neither mode rewrites source PAC,
PAM, PAMLOD, PAMT, or PAZ files in place. The executable does not upload data
and contains no telemetry.

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

CDMW starts integrated mode itself with a manifest it owns:

```text
cdmw_mesh_lab.exe --cdmw-session <manifest> --embedded-parent-hwnd <decimal>
```

`--cdmw-session` cannot be combined with standalone `--mesh` or
`--archive-root`. Preview consumers instead use `--cdmw-preview-session <manifest>` with the
`cdmw_rust_preview_package_v1` package and `cdmw_rust_preview_protocol_v1`.
The authoring manifest uses `cdmw_rust_mesh_authoring_package_v1`; the
window and CDMW then exchange bounded JSONL control messages under
`cdmw_rust_mesh_editor_protocol_v1`. Control messages use stdout and diagnostics
use stderr. Large geometry and state arrays stay in hash-checked files beneath
the owned session directory rather than being embedded in JSONL.

For a layered PAC material, CDMW uses the shared Archive Browser PAC/PAC_XML
graph, leased DDS cache, and material-combiner path to publish an sRGB base
composite and linear packed-surface composite for each Part with a proven layer
graph; direct-only Parts retain their authored DDS. Packed surface green
is roughness and blue is metalness; selector masks are compositor inputs, while
proven normal and height DDS files remain direct resources. Composite sizing is
source-driven, excludes selector masks, preserves aspect ratio, never upscales,
and caps the longest side at 2048. The integrated renderer consumes the full
mip chain with a -2 LOD bias, trilinear filtering, up to 16x anisotropy, and 4x
MSAA when supported. Preparation is bounded and cancellable; an unresolved
material input retains usable direct DDS and never mutates game
archives or the leased preview package.

The leased package also retains its exact per-Part material category and
confidence. An authored PAC `_materialTexture` (normally `*_sp.dds`) outranks
the flattened selector-mask field (`*_m.dds`) for the packed surface slot.
Package-owned resources remain authoritative when an unused compatibility path
points at CDMW's separate decode cache; that external path is still rejected if
no validated packaged/resource alternative exists. Offline generated channels
are accepted only when the PAC compiler proves that the material owner was
conserved with no cross-owner or layer-as-base binding, and tiled skin detail
stays in the runtime mask/normal/material path rather than being baked into the
base normal.

Parity automation can emit the integrated control contract without opening a
window:

```text
cdmw_mesh_lab.exe --control-contract-json <path>
```

The report uses `cdmw_rust_mesh_editor_control_contract_v2` and merges the
former compatibility and Rust-extension rows into one Rust-owned product
surface. Every enabled row must have a painted UI anchor and compiled dispatch
target; every disabled row must have a reason. Rust contract generation does
not resolve, launch, hash, or read a Vortice executable or report.

## Materials in CDMW previews

CDMW-imported glTF materials preserve OPAQUE, MASK and BLEND and scalar opacity.
Blended triangles render after opaque geometry, with depth testing and without
depth writes, sorted for each view and current placement. The same draw path serves
the window and offscreen captures. Imported metallic/roughness factors multiply
their maps and retain glTF defaults when maps are absent. The D3D12 pixel gate
checks overlapping layers, opaque occlusion, moved layers, zero opacity, cutout,
and mapped/unmapped factor semantics. This does not implement transmission,
refraction or the remaining archive-specific layered material composition.

## Effects in CDMW previews

Resident texture-package promotion waits for active camera and placement gestures
to finish. Correlated `package_load_progress` messages pause the host's replacement
deadline only while a prepared package waits for interaction, then restore the
normal deadline. A same-source refresh keeps the completed placement and editable
model matrix; an explicit reset, different source, or changed automatic fit uses
the new package's placement.

The resident effect overlay renders DDS sprites, interpolated flipbooks,
packed mask channels and bounded decoded mesh particles. It uses authored
velocity, damping, speed limits, independent size axes, colour and alpha curves.
Particle camera/sprite bindings are separate from the mesh material bindings;
transparent particles share camera-depth order and a reusable upload buffer.
The synthetic D3D12 smoke gate asserts particle pixels, mask channels, frame
selection, transparency and triangle shape through the production draw path.

This is an approximate preview. Procedural spawn volumes use the placed origin
unless a spawn mesh was decoded; packed mask variants are selected
deterministically. Vector fields, collision, trails, game lighting, distortion
and full material composition are not reproduced. Missing mesh geometry uses
its sprite when available and reports the missing asset. Captures establish
renderer output, not in-game parity.

## User interface

The Rust controls currently use English text. The surrounding CDMW PySide UI
and documentation use the selected app language; those catalogs are not yet
consumed by this editor. Preview localization acknowledgements are separate from
editor UI translation.

The interface described below is the standalone Rust Mesh Lab layout. In
CDMW-managed mode the executable instead presents the Mesh Editor session bar,
left tool rail, camera strip, Parts, Geometry Layers, Action History, Morph &
Refit, and output-policy controls supplied by the integrated control contract.
The session bar and camera strip use labelled rows, the left rail groups
Selection, Transform, Sculpt, Mesh Data, and Deform tools, and the right rail
separates Parts, Layers, and History. CDMW supplies its semantic palette,
light/dark variant, UI and data font sizes, scale, and density before reveal and
on live appearance changes, so embedded egui controls do not inherit an
unrelated operating-system theme.
Selected controls use the strong-text foreground on the muted accent surface.
Disabled controls retain readable text alongside their distinct fill and border.
The optional `integrated_theme_button_readability_for_supplied_palettes` test
reads current palettes exported from CDMW's theme registry through
`CDMW_THEME_PALETTES_FILE` and writes `CDMW_THEME_READABILITY_REPORT`. It checks
paint data without maintaining a second palette list or opening a desktop window.
Rust-native Select, Move, Rotate, Scale, Grab, Smooth, Inflate, and Pinch remain
local; numeric translation, rotation, and per-axis/uniform scale steps commit
through the same local history. Inflate's signed strength inflates above zero
and deflates below zero. Grab, Smooth, Inflate, and Pinch expose Off/X/Y/Z
object-space symmetry within each Part; an explicit selection clips both sides,
mirror-plane vertices apply once, and unmatched vertices remain untouched. Face
and edge Extrude send an explicit world-X, Y, or Z offset. Cleanup/repair and
mirror, normals/tangents, UV0, bone selection and skin weights, parameterized
topology, Geometry Layers, and Morph & Refit route as typed commands through the
disposable shadow `MeshService`. Geometry Layer visibility removes hidden Parts
from both rendering and viewport picking while the base layer remains visible.
A Bones overlay is available only when the host supplies a complete, bounded,
acyclic linked hierarchy, and Rig & Skin Weights shows a bounded selected-vertex
influence/value/total readout. Weight adjustment and normalization require
explicit Vertex targets; source transfer accepts explicit vertices or Parts.
All three are enabled only for Exact PAC LOD 0 with a resolved PAB palette,
unchanged topology/source mapping, and the proven 40-byte, six-slot
`pac_slot_u10x6` record. PAM, PAMLOD, Free Edit OBJ,
unresolved palettes, generated vertices, and protected extra-influence lanes
remain disabled with the owning reason. Refit controls hydrate the selected
bound garment's saved settings, and successful no-op or diagnostic host results
remain visible in the status. CDMW resolves the matching PAB automatically from
the archive/package context; the Rust window deliberately has no manual PAB
attachment control. Morph profile creation exposes rule, axis, amount, feather,
falloff, and mirror inputs, while each active slider shows its saved range and
label. Cleanup and layer creation explain that their topology-changing actions
require Free Edit; **Copy Selection** followed by **Paste New Layer** creates an
editable layer from the current mesh-element or Part selection.

Integrated mode consumes CDMW's already-resolved base, normal, material,
height, emissive, and typed material-input DDS files from the isolated session
package. Every resource is copied beneath the owned session root with a bounded
size, SHA-256, DDS role, per-LOD material ownership, and strict relative path;
the same bindings are restored after every accepted shadow revision, remapped
only when the owning Part remains uniquely identifiable. CDMW also transports
the canonical per-material presentation category, confidence, normal-Y policy,
and bounded roughness, metalness, specular, emissive, height, alpha, and hair
factors already resolved by the shared Archive Preview material graph.
Missing, ambiguous,
or unavailable inputs leave **Solid (Textured)** disabled with the exact reason
and use an honest neutral opaque surface rather than a normal-colour
approximation. The integrated Blender-lite boundary does not yet
include Bevel/chamfer, UV1 or a 2D UV workspace, a true weight-paint
heatmap/brush, normal-direction extrusion, or full layered/dye material
composition. The Bones overlay is
hierarchy inspection rather than posed or skinned-deformation preview, and the
selected-weight display is numeric rather than weight paint. The CDMW authoring
package and Finish path still preserve protected source channels.

The integrated viewport first reuses Archive Browser's resolved native material
package for the same mesh identity. The resolver transfers its material model,
exact package path, and lease atomically so an older geometry-only package cannot
silently replace the texture owner. CDMW leases that context into the shadow
session and copies only bounded, SHA-256-checked DDS resources beneath the owned
root. If the package or a required relationship is unavailable, **Solid
(Textured)** keeps its explicit reason and the mesh remains editable with the
neutral opaque surface; there is no silent texture or normal-colour substitute.
Solid and material triangles render two-sided so intentional interior shells or
inconsistent source winding remain visible, while the same pass still tests and
writes depth so the nearest surface occludes the far side instead of becoming
see-through. Character and ordinary meshes start from the same corrected Front
orientation as the **Front** button; **Back** uses the opposite side. Strongly
Z-elongated integrated assets such as swords instead start from a side
three-quarter view, keeping the complete weapon centered and readable without
changing the named camera-button directions or the standalone Lab camera.
The swapchain prefers an sRGB target, the shader keeps texture and lighting
math linear until presentation, and the studio key/fill follows the current
camera. Canonically synthesized base-colour PNGs are explicitly treated as sRGB
source bytes when CDMW encodes the owned BC7-sRGB session resource, preventing a
second transfer curve from washing midtones toward white; direct DDS resources
retain their existing path. Back-facing shells flip their lighting normal, and
AO uses the same restrained preview strength instead of multiplying the complete ambient
term, and a bounded workbench tone curve prevents either crushed shadows or a
flat global brightness boost. Source roughness and metalness maps remain
authoritative. High-confidence metal adds only a camera-relative studio-card
reflection profile to its specular/environment response so pale steel retains
readable dark and light bands without globally changing base colour or the
leather, cloth, skin, wood, and generic paths. When those maps are absent, the
transported category supplies a
conservative metal, leather, cloth, skin, hair, glass, gem, stone, eye, tooth,
wood, or generic response; category feedback is reduced when authored
roughness is present so mapped weapon materials retain their existing detail.
The windowed renderer selects 4x MSAA only when both the surface format and depth
target support it, otherwise it uses 1x. Textures use linear minification,
magnification, and mip filtering with 16x anisotropy when supported and 1x when
not. **Solid + Wire** uses the exact scene depth test without writing depth or
moving edges toward the camera, keeping rear edges behind the surface instead
of painting a permanent grid-like overlay. Only explicit **X-Ray** uses the
no-depth wire pipeline. Integrated wire and vertex colour controls update those GPU
overlays directly. Normals are short, sampled cyan direction guides with a
dense-mesh cap rather than one full-length spike per vertex, and **UV Checker**
is available from the UV page to make coordinate changes perceptible.

GPU mesh state remains resident between edits. A same-topology geometry revision
refreshes existing vertex buffers in place; a topology generation, index layout,
material range, or buffer-length change replaces the buffers. Raw gesture input,
UI changes, loading, CDMW messages, and resize request redraws on demand, while
an open but stationary gesture does not force a continuous repaint loop.
Optional **Persistent edit colours** compare current positions with the loaded
topology's reference and accumulate displacement magnitude across later edit
gestures: green marks a small change, yellow a medium change, and red a large
change. Turning the option off only hides the preview, so turning it back on
restores the accumulated colours. The reference resets to the current mesh after
a topology change or LOD switch. The colour data is not part of the authoring
transaction, materials, textures, or saved game/mod output. Source/unit and
offscreen GPU checks cover these contracts; they do not establish visible
Windows usability or licensed game-asset appearance.

Integrated mode does not write a mod directly from the Rust window. **Finish
Edit Mesh** returns the accepted revision to CDMW, where **Run validation** must
pass. **Build Mod** can then create DMM/JMM/CDUMM/Crimson Sharp loose output or a
DMM archive group; those package outputs are revision-pinned and atomically
staged. **Install as Overlay** instead enters the existing confirmed
backup/rollback flow. Source PAMT/PAZ files remain unchanged.

- **Archive / Assets** opens an archive root or extracted mesh, searches virtual paths off the UI thread, and virtualizes the displayed rows.
- **Viewport** uses `wgpu` with Direct3D 12 on Windows, an aspect-aware shared camera matrix, and a depth target. Persistent GPU line buffers provide optional cyan vertex normals, an always-readable amber mesh-bounds box, and a blue x-ray Bones hierarchy when a supported PAB companion resolves. For direct files it checks an adjacent or `modelproperty` same-stem material sidecar; for archive files it derives the same family path and resolves it through the asset index. Exact same-stem PAB paths outrank the current proven character-family names; more than one family candidate selects nothing. Archive DDS payloads pass through the bounded Stored/LZ4/Partial/Sparse decoder before DDS metadata validation and upload. Explicit sidecar parameters outrank decoded-name fallback. Each triangle retains its material owner, noncontiguous faces are batched by owner, and distinct supported 2D DDS files bind only to the matching submesh ranges for the active LOD. The explicitly labelled approximate shader samples base color, reconstructs tangent-space normal Z, reads `_materialTexture` G as roughness and B as metalness, lets separate roughness and metalness R channels override only those packed values, applies occlusion R to its ambient terms, and multiplies bound emissive texture data by a uniquely resolved explicit hex emissive color and finite 0–32 intensity when present. Linear Specular has its own RGB reflectance slot. Legacy Glossiness/Smoothness has a separate red-channel slot and supplies `roughness = 1 - glossiness` only when packed material, separate Roughness, and packed skin response have not already supplied roughness, so Specular and Glossiness can coexist without overwriting each other. Explicit roughness factors nudge rather than flatten source-map variation, metalness factors may raise the metal response, and specular factors follow the same material-category boundary. An authoritative linear Opacity texture supplies approximate red-channel coverage when an explicit `AlphaTest`/`AlphaClip`/`AlphaCutout`/`Cutout` family parameter is enabled; otherwise base-color alpha supplies coverage. The current production-preview threshold for an explicit alpha-test material is 0.08. Binding the same Opacity texture to an opaque material has no render effect, and true blend transparency remains unimplemented. Only an explicitly declared `_heightTexture` may bind the global linear Height slot: wrinkle, detail, parallax, and layer displacement references remain preserved but unbound until their owning semantics are native. Height R perturbs the fragment normal from neighboring UV samples and slightly adjusts roughness around neutral 0.5; `_screenSpaceDisplacementScale`, `_detailScreenSpaceDisplacementScale`, or `_heightIntensity` supplies a unique 0–1 strength, otherwise the current production-preview default is 0.025. A declared zero produces no pixel change. This does not move vertices or claim true displacement. Linear Flow textures preserve `_flowTexture`, SSDM, or direction provenance, but only `SkinnedMeshHair`, `SkinnedMeshFur`, and `AnimalHair` owners activate the two-channel strand direction. Qualified owners replace the round direct highlight with shifted primary and secondary strand bands; non-hair owners remain pixel-identical even when the Flow relationship is loaded. Exact `_colorBlendingMaskTexture` and `_detailMaskTexture` references bind as a separate linear Layer Mask role; the diagnostic samples production-selected R and B respectively, while the lit material remains unchanged because the actual selected color/detail layers are not yet composed. Float and packed Byte4 values follow the current native parameter-name families, clamp to 0–1, retain authored-zero presence, and bind by material owner on every LOD. Missing, duplicate, ambiguous, unmatched, or same-preview-slot conflicting relationships keep only the affected roles on defaults; conflicting factor values leave only that factor unbound. Blended alpha, actual layered/dye composition, non-global displacement, and remaining scalar/vector parameters are preserved and reported but not sampled. Role-aware upload maps base/emissive data to sRGB and technical data, including Flow and Layer Mask, to linear even when a DDS header disagrees. It does not claim exact game-shader, layered-material, general scalar/vector, true-displacement, transparency, or PAC skinning parity.
- **Inspector** reports format, editable/declared LOD counts, parser, warnings, archive flags, entry sizes, the archive decode method (Stored, Partial raw, Partial DDS, Sparse DDS, or LZ4), and every loaded material texture's role, requested reference, sidecar parameter/path, resolution method, owning material ranges by LOD, format, color space, and mip count. It also reports prepared emissive, roughness/metalness/specular/height-scale, alpha-cutout, hair Flow gating, and layer-mask channel factors and provides a collapsed list of all preserved typed or unknown parameters with original tag, name, raw value, attributes, wrapper/material owner, explicit/incomplete confidence, LOD ownership, and sampled-versus-unbound status. When a supported PAB resolves, the Inspector reports its path, resolution/decode provenance, fixed-layout parser, bone/root/depth/segment/tail counts, and a collapsed hierarchy with index, name/hash, parent, and bind position. This is read-only hierarchy context; PAC palette, weights, rigid binding, PABC, and morph application remain unresolved. **Editable LOD** switches between worker-prepared LODs while preserving each LOD's geometry, selection, and Undo/Redo history; texture and factor ownership are remapped by submesh name for that LOD, and the active counts follow the edited mesh rather than summing every source LOD. The existing 512 MiB history budget is divided across the loaded LOD sessions.
- **Selection** routes Click, Brush, Rectangle, and Lasso gestures through the same revision-stamped projection for Vertex, Edge, and Face domains. **Visible** depth-tests candidates against a projected-triangle BVH while **X-Ray** includes occluded candidates; both use a persistent 32-pixel screen grid so local queries inspect bounded cells instead of rescanning every projected element. Replace, Add, Subtract, and Toggle apply once to the complete gesture, including fast drags retained by the bounded raw-input queue; pathological long lassos are deterministically compacted while preserving the press and release points. Type-specific Select All, Linked, Grow, Shrink, Invert, and Clear are deterministic selection-only commands: Linked follows vertex, shared-vertex edge, or shared-edge face adjacency from the current active-domain seeds without crossing into disconnected islands; Grow adds one ring; Shrink removes elements adjacent to an unselected neighbor; and Invert complements only the active domain. Each actual change creates one Undo entry without changing geometry, while a repeated no-op creates none. Dense face selections keep their translucent fill but stop outlining every triangle after 128 faces, avoiding radiating overlay clutter.
- **Interactive Edit / Sculpt** provides Move, Rotate, and Scale gizmos plus Grab, Smooth, Inflate, and Pinch brushes. Every brush uses the same visible surface footprint and the current Smooth, Linear, or Constant screen-space falloff, intersected with the explicit selection when one exists. Grab captures its initial footprint and weights for the whole drag; Smooth, Inflate, and Pinch resample the weighted surface footprint as the stroke moves. Smooth can apply 1–8 deterministic passes per pointer sample. Pinch uses the pointer as its center on a camera-facing plane through the affected vertices' mean depth, so even one eligible vertex moves toward the visible brush. Each drag previews locally, mouse release commits one undo entry, and Esc, resize, or focus loss rolls the gesture back. Position edits leave every out-of-scope position exact and recompute normals only for the affected one-ring; face deletion, face midpoint subdivision, selected-edge midpoint subdivision, face duplication, face extrusion, and individual-face inset validate a private working draft before replacing the live mesh and preserve every surviving source vertex's decoded position and normal. Face subdivision and duplication select their generated faces; edge subdivision selects both generated child edges. Multi-face duplication shares one isolated clone per selected source vertex so the copied patch keeps its internal adjacency. **Duplicate as New Part** additionally assigns the copy to the next free submesh while retaining every face's material, UVs, and normals, allowing the selected copy to move without changing pre-existing vertices. **Extrude** moves one shared cap clone per selected source vertex by the positive **Extrude distance** along its normalized source normal, adds two triangles only for each selected-region boundary edge, retains the source owner/material/UV/normal attributes, omits walls between selected neighbors, and selects only the cap for further transforms. Side-wall UVs inherit their endpoint values. **Inset Individual** keeps each selected triangle's original boundary, interpolates three generated cap vertices and their UVs toward that face's centroid by the strict 0–1 **Inset amount**, fills the gap with six same-owner ring triangles, and selects only the caps. Multiple selected faces receive separate caps and do not share generated vertices; this deliberately does not claim region inset or automatic UV unwrapping. Undo and Redo remain one-shot commands. Disabled controls state why they are unavailable, and the Inspector scrolls independently after a shorter-window resize.
- **Export Neutral OBJ…** asks for a parent folder, refuses the selected game/archive root, stages and reparses the active LOD's edited mesh on the worker, verifies its structural fingerprint, then publishes a new `cdmw-rust-mesh-export` directory atomically. Existing output is never replaced and source textures are not embedded.

### Viewport controls

- Hold **RMB** and drag to orbit.
- Hold **MMB** and drag to pan.
- Use the **mouse wheel** to zoom.
- Press **F** to frame the selection, or the complete mesh when nothing is selected.
- Use **Frame All**, **Frame Selected**, or Front/Back/Left/Right/Top/Bottom for exact camera placement.
- Use **Editable LOD** to inspect and edit another proven LOD without losing the previous LOD's changes. Switching keeps the camera and cancels any unfinished gesture before parking that LOD's session. PAC levels use only the proven section 4→LOD0 through section 1→LOD3 mapping; no PAC/PAM/PAMLOD writeback is implied.
- Choose Textured, Game Outdoor, Base Color, Normal Map, UV Checker, Base Alpha, Part ID, Material Response, Layer Mask, Solid Faces, Solid + Wire, Wireframe, Vertices, Wire + Vertices, or X-Ray from **Preview mode**, then independently toggle **Normals**, **Bounds**, and **Bones**. Game Outdoor compares the same material under the production preview's approximate warm-direct/cool-ambient preset; it is not game-shader parity. Part ID gives every material-owner draw range a stable diagnostic color even when no texture is bound. Layer Mask shows `_colorBlendingMaskTexture` R or `_detailMaskTexture` B in grayscale and does not pretend to compose the selected dye/detail layers. Bones draws decoded parent-child bind segments through the surface and remains disabled with an exact reason when no supported hierarchy is available; it does not skin or pose the PAC.
- Choose Click, Brush, Rectangle, or Lasso, then drag in the viewport. Use **All Vertices**, **All Edges**, or **All Faces** for a complete domain; **Linked** expands the current seeds through only their connected island; and **Grow**, **Shrink**, or **Invert** make other topology-aware selection changes. Brush radius, Smooth/Inflate/Pinch strength, Smooth/Linear/Constant falloff, 1–8 Smooth passes, positive face **Extrude distance**, and strict fractional **Inset amount** are adjustable in the inspector; Grab follows pointer travel directly and therefore has no separate strength control.
- **Visible** is the default and rejects candidates behind the nearest projected triangle at their representative point; choose **X-Ray** to include occluded candidates. Sculpt brushes always use the visible-only route so a surface stroke does not also modify the back side.
- Select Move, Rotate, or Scale and drag the visible axis/ring/center gizmo. Select Grab, Smooth, Inflate, or Pinch and drag over eligible vertices.
- Press **Esc** to cancel an active selection or edit gesture.
- The inspector reports the last and rolling 256-sample p95 CPU selection/edit time. Selection also reports how many indexed candidates were inspected out of the complete projected element count; these are CPU callback measurements, not frame time or GPU latency.

Face and Part highlights are filled triangles in the GPU depth buffer. Large selections
keep the same fill instead of changing to dots; occluded portions stay hidden unless
X-Ray selection or display is enabled. Brush strokes cover the path between retained
pointer samples and toggle each element only once per stroke. Camera navigation reuses
selection geometry and counts without rebuilding the CPU picking index every frame.

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

`headless-mesh` decodes the supplied file read-only, then runs Move, Grab, Smooth, Inflate, Pinch, face Delete, face Subdivide, selected-edge Subdivide, face Duplicate, Duplicate as New Part, face Extrude, and individual-face Inset on fresh working meshes for every decoded LOD. Every scenario names its `lod_level`, must make the intended change, preserve positions and normals outside the operation's permitted scope, create one history entry, pass mesh invariants, restore the exact baseline through Undo, and reproduce the exact edited fingerprint through Redo. Top-level vertex/face counts retain the first decoded LOD's counts. Its JSON timings measure CPU decode/edit/history work; they are not pointer-latency, frame-rate, or visual-parity measurements.

## Cache and evidence

No persistent decoded-asset cache is published yet. Build output stays under `tools/rust_mesh_lab/target/` and is ignored. Oracle output is written only to a destination explicitly selected by the caller and refuses to replace an existing package.

Use a system temporary directory for private evidence. Do not place game assets, decoded buffers, screenshots, or private path lists in the repository.

An already-created CDMW session can be rendered through the same package loader,
material bindings, startup camera, and D3D12 draw path without opening a window:

```powershell
.\target\release\cdmw_mesh_lab.exe --capture-cdmw-session "$env:TEMP\session\manifest.json" --capture-output "$env:TEMP\rust-mesh-capture\mesh-textured.bmp" --capture-report-json "$env:TEMP\rust-mesh-capture\report.json"
```

The command also writes sibling Base Color and Part ID BMPs. All outputs must be
distinct, outside the canonical session directory, and are staged before atomic
publication. This is diagnostic evidence only; it does not mutate the session or
replace visible Windows or in-game validation.

## Validation

```powershell
.\scripts\codex_check.ps1 -Area rust-mesh-lab-unit
.\scripts\codex_check.ps1 -Area rust-mesh-lab-gpu
.\scripts\codex_check.ps1 -Area rust-mesh-lab-stress
```

The unit gate runs formatting, Clippy with warnings denied, workspace tests, and a Release workspace build. Its no-window UI fixture discovers coordinates from egui's clipped draw output, then uses the real painted controls plus the live bounded raw-pointer route for menus, all fifteen preview modes and camera settings, LOD switching, PAB hierarchy/Bones state, texture and material-parameter provenance, pointer and topology-aware selection, all seven standalone transform/sculpt tools, all seven topology actions (face Delete, face Subdivide, selected-edge Subdivide, face Duplicate, Duplicate as New Part, face Extrude, and Inset Individual), history, high-DPI navigation, resize, and cancellation. The GPU gate creates no window: it requires a D3D12 adapter, uploads sixteen synthetic DDS files through the windowed renderer's live helper, composes thirteen sampled roles across two independently based material ranges, reuses the mesh draw path for all fifteen preview modes plus Normals, Bounds, Bones, and authored-colour effect guides, renders wide, tall, and 4:3 targets, checks `wgpu` validation scopes, and reads back unresolved, base-only, one-extra-role, metallic and dielectric Specular-map, metallic and dielectric Glossiness-map, opaque and cutout Opacity-map, active and explicit-zero Height-map, inactive non-hair and active hair Flow-map, layer-mask fallback/R/B-channel, overlay-free Part ID and Game Outdoor, Bones off/on, effect guides off/on, emissive-factor, roughness-factor, metalness-factor, metalness-plus-specular-factor, fully composed, Base Color round-trip, and curved generic/metal/leather/cloth/skin/glass material-proof frames during an 84-frame pass. The material proof can be retained as a 3x2 BMP without creating a window. Its additional reversed-winding Solid probe must retain non-background lit pixels, proving the two-sided triangle path is neither culled nor black while remaining depth-writing. It fails unless geometry is visible; the Bones and authored-colour effect comparisons change pixels; base color, normal, packed material, separate roughness, separate metalness, occlusion, emissive, Specular, Glossiness, cutout Opacity, Height, qualified hair Flow, and Layer Mask each change rendered pixels independently where applicable; Specular changes RGB reflectance independently, while Glossiness changes dielectric roughness through its own slot and unit coverage requires explicit or packed roughness to outrank it; the Opacity comparison removes visible pixels only when cutout is enabled and leaves the opaque frame byte-identical; the Height comparison changes pixels at positive strength and exactly zero at explicit zero; the same Flow binding changes hair pixels but leaves a non-hair frame byte-identical; the Layer Mask diagnostic differs from fallback and its R/B selectors differ from each other; Part ID renders both material-owner ranges as distinct colors even with no texture binding; Game Outdoor differs from the same base material under standard Textured lighting; Base Color preserves source sRGB texels through the GPU output path; front-facing Textured luminance stays within the bounded readability ratio; every fallback material category changes pixels; explicit emissive color/intensity changes pixels again; and roughness, metalness, and specular factors each produce another independent pixel difference. The stress gate also creates no window and serially drives the real `LabApplication` through 16,800 lasso gestures, 400 committed and 400 cancelled sculpt strokes, long and 5,000-sample high-rate strokes, tool/mode/resize/focus interruptions, and two deterministic 1,000-gesture mixed sessions. It asserts mesh invariants, idle operators, bounded pointer/latency queues, exact cancellation, and the configured total Undo/Redo history budget. These gates prove CPU/offscreen execution and control routing, not visible usability, OS working-set stability, true displacement, full layer composition, PAC skinning, or real-game appearance parity. `cargo deny`, `cargo audit`, and fuzzing are separate optional gates when installed.

The CDMW-managed authoring lifecycle has separate focused Python tests for
shadow isolation, bounded payloads, exact output, typed cleanup/normals/UV and
rig-weight actions, Morph & Refit safety, atomic history restore, embedded HWND
ownership/lifecycle, and the merged Rust v2 control contract. See
[the Mesh Editor guide](../../cdmw/ui/mesh_editor/README.md); the standalone Rust gates above
do not prove an accepted CDMW Finish transaction.

## Troubleshooting

- **No D3D12 adapter:** update the display driver or run on a Windows device with Direct3D 12. The lab currently fails closed rather than silently switching the production proof class.
- **Mesh layout unsupported:** the parser did not find a locally proven layout. The source is not treated as decoded and remains unchanged.
- **Archive open fails:** select the archive package root containing `.pamt` indexes and numbered `.paz` files. `cdmods` is deliberately excluded.
- **No skin texture:** the supplied PAC may not contain texture names. Keep its `.pac_xml` material sidecar and referenced DDS files in their extracted virtual-path layout, or open the archive root. If no sidecar exists, an owner cannot match a decoded submesh, or different paths claim the same material range, the Inspector intentionally keeps that range on the approximation and explains why.
- **Partial or Sparse DDS fails:** supported 2D archive DDS entries reconstruct only when their validated header, dimensions, mip plan, declared sizes, and active byte limits agree. Partial DDS also requires the exact virtual path in the sibling `meta/0.pathc`; missing, ambiguous, truncated, oversized, array/cube, or otherwise unsupported data fails closed without changing either source file. Partial PAR and GPU fallback transcoding are not implemented.
- **Large archive search:** submit the query with **Search**. Filtering runs on the bounded worker and the UI shows at most 20,000 matching row identities while reporting the full match count.
