# Rust Mesh Lab readiness

## Result

**PARTIALLY READY**

The isolated lab builds, launches a responsive Windows window, selects a Direct3D 12 adapter, renders validated geometry and distinct sidecar-resolved base/normal/packed-material/separate-roughness/separate-metalness/occlusion/emissive/specular/glossiness/opacity/global-height/flow/layer-mask DDS files on their owning submesh ranges through `wgpu`, preserves typed and unknown sidecar material parameters, applies uniquely owned explicit roughness/metalness/specular/height-scale factors to their material ranges, emissive color/intensity to bound emissive textures, explicit alpha-test enable state as an approximate cutout policy, hair anisotropy only when Flow belongs to a proven hair/fur shader family, and production R/B channel selection for color-blending/detail masks, opens archive roots read-only, reconstructs bounded supported 2D Partial/Sparse archive DDS entries in memory, virtualizes archive results, loads direct/archive PAC/PAM/PAMLOD candidates, and supports fifteen aspect-correct geometry/material preview modes—including Game Outdoor lighting and texture-independent Part ID ownership colors—plus camera navigation, pointer-driven selection, transform, sculpt, and history workflows on an in-memory generational mesh. The same app-owned workflows now have no-window construction and behavior coverage, and the shared multi-role DDS upload plus renderer draw path has an opt-in offscreen D3D12 validation/readback gate.

It is not LAB READY because private real-game parity, complete layered/dye and blended-alpha material composition, non-global and true vertex displacement, Partial PAR and unsupported DDS subresources/transcoding, PAC skinning/appearance, representative stress/performance evidence, cache, versioned lab projects, fuzzing, and source fingerprint sessions remain incomplete.

## Implemented and locally proven

- Isolated Cargo workspace; production CDMW has no dependency on it.
- Pinned Rust 1.95.0 and locked dependencies.
- Read-only `.pamt` index discovery and parsing with PAZ range validation.
- Stored and LZ4 entry decode; bounded PATHC-backed Partial DDS reconstruction; validated Sparse DDS zero padding; and filename-derived ChaCha20 type 3 support using the current CDMW lookup3 contract for both PATHC paths and long encrypted filenames.
- PAC/PAM/PAMLOD geometry foundations with fail-closed layout validation.
- Proven PAC section-to-LOD decoding and an **Editable LOD** selector. The worker prepares every decoded LOD, and switching preserves independent geometry, selection, and Undo/Redo state without multiplying the 512 MiB history budget. Non-manifold source edges retain all incident faces rather than rejecting an otherwise valid lower LOD.
- DDS legacy/DX10 metadata, bounded mip planning, supported 2D archive Partial/Sparse reconstruction, role-authoritative color-space classification, and direct supported 2D `wgpu` upload. Base/emissive roles select an sRGB GPU format; technical roles select linear even when the file header carries an sRGB variant, and impossible sRGB/format combinations fail closed.
- Bounded material-sidecar scanning preserves wrapper type, submesh, shader/material name, texture parameter, original path, inferred role, and unknown texture references across common attribute spellings. It also preserves Float/Float2/Float3/Half2/Color/Byte4/BitFlag32/unsigned/signed/bool and unknown parameter tags with their original name, raw value, attributes, and explicit/incomplete confidence. Direct and archive loaders derive same-stem material sidecars, prefer explicit sidecar references over decoded-name base-color fallback, map wrapper owners independently onto every LOD's decoded submesh order, and use exact/relative/unambiguous asset relations without selecting ambiguous basenames. Base color, normal, packed material, separate roughness/metalness/occlusion, emissive, specular/glossiness, opacity, global Height, Flow, and Layer Mask roles may coexist per owner; disjoint owners may bind different DDS files, and same-owner conflicts leave only the conflicting preview slot unresolved. The approximation routes linear Specular and legacy Glossiness/Smoothness textures into the production preview's one response slot and samples either only in proportion to the source metal fraction, so neither can lift a dielectric material's F0. Glossiness keeps its provenance and is not inverted into roughness because the production selector declares no component contract for it. It samples Opacity red-channel coverage only for an explicitly enabled alpha-test family parameter, falls back to base-color alpha, and uses the current production-preview 0.08 cutoff; an opaque material ignores the same Opacity binding. Only an exact `_heightTexture` declaration binds global linear Height. Height R perturbs the fragment normal from neighboring UV samples and adjusts roughness around neutral 0.5 using a unique finite `_screenSpaceDisplacementScale`, `_detailScreenSpaceDisplacementScale`, or `_heightIntensity` clamped to 0–1; absent scale falls back to 0.025 and explicit zero disables the effect. Wrinkle/detail/parallax/layer displacement stays preserved but unbound, and no vertices move. Flow is linear and preserves `_flowTexture`, SSDM, or direction provenance, but only `SkinnedMeshHair`, `SkinnedMeshFur`, and `AnimalHair` owners enable its two-channel UV strand direction and shifted primary/secondary anisotropic bands; a non-hair owner remains byte-identical. Exact `_colorBlendingMaskTexture` and `_detailMaskTexture` parameters bind a separate linear Layer Mask role with the production R and B selectors. The Layer Mask view renders only that component in grayscale and leaves Textured output unchanged because actual dye/detail sources are not yet composed. The approximation also samples unique explicit roughness, metallic/metalness, and specular Float or Byte4 factors clamped to 0–1, preserves authored zero independently from absence, applies a unique hex emissive color plus finite float intensity clamped to 0–32 only with a bound emissive texture, and follows production true/false/string/numeric alpha-enable semantics. Conflicting or invalid values leave only that field unbound. Channel-authoritative opacity, blend transparency, actual layered/dye composition, non-global displacement, and remaining scalar/vector parameters remain incomplete.
- Immutable decoded source document and separate editable working document.
- Generational vertex/edge/face handles and topology generation.
- Interactive Move, Rotate, Scale, Grab, Smooth, Inflate, and Pinch with Smooth/Linear/Constant visible-surface falloff, stable begin weights for Grab, resampled weights for the other brushes, and 1–8 Smooth passes; atomic face Delete, Subdivide, Duplicate, Undo, and Redo; topology failures leave the complete working state unchanged and generated subdivision/duplicate faces become the deterministic selection.
- One modal gesture owner and one committed history entry per confirmed gesture.
- Deterministic click/brush/rectangle/lasso query predicates, stale-snapshot rejection, and a persistent 32-pixel screen grid that bounds local candidate inspection in the interaction crate.
- User-selectable depth-aware Visible and X-Ray selection. Visible candidates query a projected-triangle BVH with interpolated depth; sculpt brushes always use that surface-only route, and no synchronous GPU readback is used.
- Viewport-aligned Vertex/Edge/Face Click, Brush, Rectangle, and Lasso selection with visible overlays in either depth mode and Replace/Add/Subtract/Toggle operations.
- Topology-aware All/Grow/Shrink/Invert commands for Vertex, Edge, and Face domains plus complete Clear. Grow expands one connected ring, Shrink removes elements adjacent to an unselected topological neighbor, Invert changes only the active domain, type-specific All activates and replaces that domain, and every actual command change is one selection-only Undo entry.
- Bounded raw pointer sampling that retains press, intermediate movement, and release when Windows coalesces redraws; long lassos compact deterministically while retaining their final release point, one completed gesture creates one history entry, and Esc/resize/focus loss restores the pre-gesture mesh.
- Orbit, pan, zoom, frame-selected/all, six standard views, and one aspect-aware camera generation shared by rendering and interaction snapshots.
- Direct3D 12 `wgpu` surface, depth target, persistent revisioned mesh/normal/bounds buffers, Textured/Game Outdoor/Base Color/Normal Map/UV Checker/Base Alpha/Part ID/Material Response/Layer Mask/Solid/Solid+Wire/Wireframe/Vertices/Wire+Vertices/X-Ray modes, and independent Normals/Bounds overlays. Game Outdoor is a production-constant-informed lighting comparison inside the approximate shader; Part ID colors actual material-owner ranges without requiring a texture; Layer Mask is a grayscale inspection mode, not layer composition. Bones is visibly disabled until skeleton context exists.
- egui archive/assets, viewport, inspector, selection/edit, and status surfaces. The viewport and Inspector explicitly label material rendering as approximate. Archive textures report whether their bytes came from Stored, Partial raw, Partial DDS, Sparse DDS, or LZ4 handling; Flow rows retain their source relationship while prepared factors state whether the owner qualifies as a proven hair/fur family; Layer Mask rows retain their exact parameter while prepared factors report R/B selection; actual sampling still requires each DDS binding. A collapsed material-parameter section reports preserved values, owners, confidence, and sampled/unbound state without flooding the default layout.
- No-window `LabApplication` construction plus 14 painted-control/input tests whose coordinates come from egui's clipped draw output: all fifteen preview modes, LOD menus, overlay and camera controls, texture relationship and material-parameter provenance, 24 selection domain/shape/depth combinations through the bounded raw-pointer route, topology-aware All/Grow/Shrink/Invert/Clear with exact selection history, all seven edit tools, Smooth/Linear/Constant falloff and 1–8 Smooth passes, face Delete/Subdivide/Duplicate plus selected-edge Subdivide, exact Undo/Redo, disabled controls, 1×/1.5×/2× camera input, three resize shapes, Esc/resize cancellation, and dense face-selection fill without per-triangle outline strokes. Lower Inspector controls are verified at 1280×720 and 1000×600.
- Offscreen D3D12 renderer coverage uploads fifteen DDS files with the live plan/upload helper, composes base/normal/packed-material/roughness/metalness/occlusion/emissive/specular/glossiness/opacity/height/flow/layer-mask roles across two base-colored ranges, applies separate explicit emissive, roughness, metalness, metallic-specular, metallic/dielectric Glossiness, opaque/cutout Opacity, positive/zero-scale Height, inactive-non-hair/active-hair Flow, and layer-mask fallback/R/B-channel probes, and exercises all fifteen preview modes with Normals and Bounds across 4:3, portrait, and widescreen targets. A validation error scope and CPU readbacks reject invalid or all-background output, require all thirteen sampled roles to change pixels independently where applicable, require both Specular and Glossiness to change metallic pixels while leaving dielectric pixels identical, require cutout Opacity to remove visible pixels while opaque Opacity remains byte-identical, require Height to change pixels at positive strength while explicit zero remains byte-identical, require Flow to change hair pixels while leaving a non-hair frame byte-identical, require Layer Mask and its R/B selector to change diagnostic pixels, require the overlay-free Part ID probe to produce two owner colors without texture bindings, require overlay-free Game Outdoor to differ from standard Textured lighting, and require each other scalar factor class to change pixels again without constructing a window.
- Read-only `headless-mesh` probe for caller-selected PAC/PAM/PAMLOD files, with fresh-working-mesh operation/Undo/Redo fingerprints and invariants for Move, Grab, Smooth, Inflate, Pinch, face Delete, face Subdivide, selected-edge Subdivide, and face Duplicate on every decoded LOD.
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
| Partial/Sparse DDS reconstruction | Synthetic pass; private corpus not run | Supported 2D Partial DDS uses exact PATHC identity and bounded LZ4 reconstruction; supported Sparse DDS validates and zero-pads to the declared size. Real archive breadth, Partial PAR, arrays/cubes, and fallback transcode remain unproven |
| Native texture/material binding | Partial | Multiple sidecar DDS files can render with role-correct color space on distinct owning submesh ranges, including reordered LOD ownership; the approximation samples base color, tangent-space normal, `_materialTexture` G roughness/B metalness, separate roughness/metalness overrides, occlusion, emissive, metallic-only Specular or legacy Glossiness/Smoothness through one response slot, explicit-cutout Opacity, exact global `_heightTexture` fragment relief, qualified two-channel hair Flow, diagnostic `_colorBlendingMaskTexture` R / `_detailMaskTexture` B, and unique explicit roughness/metalness/specular/height-scale plus emissive color/intensity and alpha-enable factors. Flow activates only for proven hair/fur shader families and remains inert elsewhere. Layer Mask is inspection-only and does not alter the lit material. Typed and unknown parameters are preserved with provenance. Remaining scalar/vector, actual layered/dye, non-global/true displacement, channel-authoritative opacity, and blend transparency plus arrays/cubes and fallback transcode remain incomplete |
| PAC skin palette/PAB/PABC/morph | Incomplete | Character appearance parity not proven |
| Lab project | Incomplete | Camera/tool/history persistence is not published yet |
| Neutral export | OBJ/MTL implemented | GLB, skinning/material preservation, and private corpus re-import parity remain incomplete |
| Persistent cache | Incomplete | No cold/warm cache timing |
| Interaction stress | Synthetic app gate passes; representative soak still partial | The complete deterministic synthetic interaction matrix passes with bounded app containers and history; long-duration real-PAC input, OS working-set, UI-thread frame pacing, repeated window lifecycle, and GPU/device-loss soaks remain unrun |
| Performance targets | Partial instrumentation | The live inspector reports last/p95 CPU query and operator cost plus indexed candidates inspected, and one supplied PAC has CPU headless-edit timings; no representative corpus latency, FPS, GPU, or memory claim has been measured |
| Fuzzing | Not run | Parser robustness proof incomplete |
| `cargo deny` / `cargo audit` | Not run yet | License/advisory gate unproven |

## Texture-complete goal remains open

Loading the mesh shape is not appearance parity. The lab now parses material
sidecar texture ownership, resolves multiple disjoint
base/normal/packed-material/roughness/metalness/occlusion/emissive/specular/glossiness/opacity/global-height/flow/layer-mask relationships,
applies role-correct sRGB/linear upload mapping, derives tangents from current
geometry, switches fixed role sets per material range and LOD, and keeps
explained neutral defaults for missing, ambiguous, or conflicting roles. Lab
readiness still requires the asset
graph to resolve every authoritative material relationship, validate supported
Partial/Sparse DDS reconstruction across a private archive corpus, decode Partial
PAR and unsupported array/cube or fallback-transcode cases, sample every supported
texture role and subresource, apply non-global displacement and the remaining preserved scalar/vector factors, channel-authoritative opacity and blend policy, and compose actual layered materials rather than only inspecting their masks
on their owning submeshes. The rainbow surface remains the normal-based
placeholder wherever no authoritative material role can bind; the plain shader
is an approximation, not proof of the character's exact loaded skin. This
partial path must not be reported as complete texture loading.

## Synthetic texture-resolution proof

No-window unit fixtures use an extracted `character/model`, `modelproperty`, and
`texture` layout. They require explicit sidecar base color to outrank a valid
decoded fallback, resolve all thirteen sampled roles across distinct owners,
bind distinct DDS files when submesh owners are disjoint, isolate two paths that
claim the same owner/preview slot—including Specular versus Glossiness—without discarding a valid sibling role, preserve
owner identity when lower-LOD submesh order changes, refuse a missing explicit
DDS instead of falling back, and retain one decoded reference only when no sidecar exists.
Parser fixtures cover nested and self-closing
texture parameters, common path/name attribute variants, XML entities, role
classification, malformed-but-bounded texture recovery, typed/vector/unknown parameter preservation,
and incomplete-value confidence. Loader fixtures require explicit emissive, roughness/metalness/specular/height-scale, alpha-cutout, and layer-mask channel factors to follow reordered LOD ownership and isolate conflicting values field by field; only exact global `_heightTexture` references may bind while wrinkle displacement remains unbound, alpha enable values follow the production true/false/string/numeric contract, Flow anisotropy is prepared only for proven hair/fur shader families, and color-blending/detail masks select R/B respectively. Renderer tests
require legacy DXT1 base color to map to BC1 sRGB, an sRGB-declared normal to map
to linear BC7, and unsupported sRGB format combinations to fail. The opt-in
offscreen D3D12 gate uploads fifteen synthetic DDS files, composes thirteen roles across
two independent material ranges, and compares unresolved,
base-only, one-extra-role, metallic and dielectric Specular-map, metallic and dielectric Glossiness-map, opaque and cutout Opacity-map, positive and zero-scale Height-map, inactive non-hair and active hair Flow-map, layer-mask fallback/R/B-channel, overlay-free Part ID and Game Outdoor, factored-emissive,
roughness-factor, metalness-factor, metalness-plus-specular-factor, and fully
composed CPU readbacks through the live helper during its 73-frame pass. Every
sampled role and each explicit factor class must change pixels independently;
Specular and Glossiness must each change metallic pixels and leave dielectric pixels identical; cutout Opacity must remove visible pixels while opaque Opacity remains byte-identical; Height must change pixels at positive strength and remain byte-identical at explicit zero; hair Flow must change pixels while the same non-hair binding remains byte-identical; Layer Mask must differ from fallback and R/B selectors must differ from each other; Part ID must render both material-owner ranges as distinct colors without texture bindings; Game Outdoor must differ from the same base material under standard Textured lighting. This is synthetic relationship
and GPU execution proof, not evidence that the supplied PAC has a material
sidecar or that a private archive reproduces its full appearance.

## Synthetic Partial/Sparse archive proof

The archive crate reconstructs a fixed Partial DDS fixture through a bounded
sibling `meta/0.pathc` and a fixed Sparse DDS fixture by validated zero padding.
Their complete output hashes must exactly match the current CDMW Python oracles:
`c9096e57e46707bd071a94b7274c6e8af0ddf01766137a186b58e993893b21a5`
for Partial and
`2880a12980fe3145ebafbe2a3d9cf177337608e9037db99a9d5e717ecfc522cb`
for Sparse. Separate regressions cover lookup3 block boundaries and long-filename
ChaCha derivation, missing PATHC, excessive PATHC records, truncated compressed
blocks, caller-selected output limits, stale PATHC chunk sizes, and byte-exact
source preservation. A no-window loader fixture crosses the real application
archive boundary, inspects the reconstructed DDS as uploadable, exposes
**Archive decode Partial DDS** in the painted Inspector, and again requires the
PAZ and PATHC files to remain unchanged. This is exact synthetic
cross-implementation and app-boundary proof, not private archive-corpus parity.

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
dispatcher used by the live viewport. It submitted Textured, Game Outdoor, Base Color,
Normal Map, UV Checker, Base Alpha, Part ID, Material Response, Layer Mask, Solid Faces,
Solid + Wire, Wireframe, Vertices, Wire + Vertices, and X-Ray with Normals and
Bounds across 640×480, 480×640, and 1280×720 targets, then submitted and read
back material-role, metallic and dielectric Specular-map, metallic and dielectric Glossiness-map, opaque and cutout Opacity-map, positive and zero-scale Height-map, inactive non-hair and active hair Flow-map, layer-mask fallback/R/B-channel, overlay-free Part ID and Game Outdoor, emissive-factor,
roughness-factor, metalness-factor, metalness-plus-specular-factor, and fully
composed probes: 73 frames total. The D3D12 validation scope was
empty and the readback contained non-background pixels. The same gate also
checks the live GPU-cache predicate: a different working-mesh identity with
equal geometry/topology revisions must not reuse the previous buffers. That
regression failed under the old revision-only predicate and passes with the
identity-aware key. No winit window or
surface was created. This proves offscreen command encoding, pipeline/resource
compatibility, aspect-dependent camera framing, and observable output. Positive Height strength changes pixels while explicit zero leaves the frame byte-identical; this is fragment relief, not vertex displacement. Qualified hair Flow changes pixels while an unqualified non-hair Flow binding leaves the frame byte-identical. Layer Mask changes diagnostic pixels and its R/B selectors produce distinct output without changing the lit material. Part ID renders two texture-independent owner colors after the targeted readback disables diagnostic overlays. Game Outdoor changes the same base material through only the source-backed lighting constants and exposure branch. It is
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

## Headless painted-control and edit-scope proof

Fourteen no-window tests now construct the real `LabApplication`, discover control
coordinates from egui's clipped draw output, and route resulting actions at the
same post-frame boundary as the Windows runtime. They cover all fifteen preview modes and the LOD
menus, camera, every selection shape/domain/depth combination, topology-aware
All/Grow/Shrink/Invert/Clear across all three domains, all seven edit
tools, topology, history, disabled states, high-DPI input, short-window scroll,
resize, and cancellation. The latest draw-command regression selects 256 faces
and requires translucent face fills with no individual outline strokes. A
separate two-triangle-quad regression requires exact connected-ring results,
selection-only Undo/Redo, and unchanged geometry. The weighted-sculpt regression
chooses Linear falloff and four Smooth passes through painted controls, requires
nonuniform bounded weights from the real projected brush, proves four passes
reduce total edge length more than one pass, and restores/replays the exact mesh
with Undo/Redo. Mesh regressions separately
require deformation positions and normals to remain exact outside the affected
one-ring, and topology operations to preserve normals on surviving source
vertices. These checks inspect application state and egui draw commands, not
native pixels or visible appearance.

## Supplied PAC headless edit proof

A Release `headless-mesh` run on 2026-08-30 decoded one user-supplied PAC as
`rust_pac_section_4_pac40`. All four declared LODs were decoded using the same
section-to-LOD mapping as the production parser, and their counts matched:

| LOD | Vertices | Faces | Edit families passed |
|---|---:|---:|---:|
| 0 | 13,740 | 25,158 | 9/9 |
| 1 | 1,938 | 3,030 | 9/9 |
| 2 | 609 | 778 | 9/9 |
| 3 | 337 | 429 | 9/9 |

Move, Grab, Smooth, Inflate, Pinch, face Delete, face Subdivide, selected-edge
Subdivide, and face Duplicate each ran on fresh working meshes for every LOD.
Every operation changed the expected
fingerprint, preserved every position and normal outside its permitted scope,
created one history entry, passed invariants, restored the exact baseline with
Undo, and reproduced the exact edited fingerprint with Redo. The single warm
decode took 3.34 ms and all 36 complete operation/Undo/Redo scenarios took
573.66 ms. LOD3 contains three source edges shared by four faces;
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
