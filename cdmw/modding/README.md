# Modding

Owns mesh and material replacement logic, scene import, source-part mapping,
runtime static mesh building, PAC/PAM/PAMLOD builders, material profiles, and
material payload routing.

Keep PySide UI and archive mutation confirmation outside this package. UI
packages collect user intent; services coordinate execution; archive patching
and backup policy stay behind archive services/core paths.

`static_mesh_output_plan.py` keeps tiled-UV materials in dedicated existing runtime
slots when an automatic complete-swap atlas is needed. Other material groups share
the remaining slots, with the current UV transforms and per-draw vertex limit applied
during allocation. The output section plan owns both mesh and texture routing;
unsupported capacity still blocks output without changing the PAC descriptor layout.

## OBJ material dependencies

OBJ geometry import, texture discovery and replacement dependency checks use the
same material-library parser. It supports quoted paths, existing unquoted paths
with spaces, multiple libraries, and tab-separated declarations. Texture paths
first resolve beside their MTL file; the established OBJ/package lookup remains
available for relocated exports. Full texture paths take priority over filename
aliases, so same-named images in different directories keep their own bindings.
Structured material slots take priority over the legacy texture-name field.
When a relocated reference needs a filename search, a match beneath the model's
own directory takes priority over matches elsewhere in the package.

## Body region decomposition

`mesh_region_decompose.py` splits the difference between two same-topology
bodies across the segmented regions, turning any existing body mod into an
editable slider set. Region weights are a partition of unity, so every region at
100% rebuilds the captured body vertex for vertex; anything no region claims
becomes its own slider rather than being dropped.

Capture is deliberately not `build_morph_delta`, which also requires matching
submesh names — body variants rename their parts (`cd_phw_00_nude_0001` versus
`CD_PHW_00_Nude_0001_Fat`). Correspondence is checked per submesh because it
varies within one file: between those two bodies the torso and hands are
index-identical while the head shares only a vertex count, so the head is
skipped and named instead of subtracted.

## PAC skin-influence layout

Inside the proven 40-byte PAC vertex record, two little-endian u32 fields at
bytes 20 and 24 each hold three 10-bit influence slots. Their six u8 weights
start at byte 28 (`PAC_SKIN_*` in `mesh_parser.py`). Slots range from 0 to 1023;
a zero weight marks an unused influence, and slot 0 is a valid entry.

Slots are **not skeleton bone indices**. Smooth-skinned `.pac` files carry a bone
palette — a u16 count then that many u32 `.pab` bone-name hashes near the start
of the file. `pac_bone_palette_candidates` returns every table matching that
shape and `resolve_pac_bone_palette` picks the one that fully resolves against a
given skeleton, so a mismatched rig yields nothing rather than wrong names.

When the low six bits of byte 39 equal 63, all six packed influences are
skeletal. Below 63, only the first four are skeletal: two packed indices and
the two half-float indices at bytes 12–15 address cloth guides instead. Their
four weights at bytes 32–35 are independent of the four skeletal weights.
Guide indices must never appear as named skeleton bones.

`pack_pac_skin_weights` retains the appropriate four- or six-bone capacity and
quantizes skeletal weights to sum to 255 while preserving cloth bindings.
Callers that require lossless influence coverage must reject wider rows before
calling it. Do not reinterpret packed slots as four u8 indices or reduce
named-bone inspection to the primary influence.

Rigid attachments may have a single full-weight slot 0 and no bone palette.
Their target bone must come from attachment or prefab data outside the mesh;
an unresolved palette alone does not prove a corrupt rig.

Races share rigs: the "other" races ship no `.pab` and skin against
`phm_01.pab` / `phw_01.pab` / `ptm_01.pab`, so pick a skeleton by which palette
resolves, not by name.

Reader (`mesh_parser.py`) and writer (`mesh_skinning.py`) must move together;
they previously agreed on the wrong offsets (28/32), which decoded 72% of every
vanilla body as unweighted and capped authored bones at index 3.
`tests/test_pac_skin_layout_regression.py` pins this against real bodies and
skips when they are absent.

## PAC vertex jiggle contribution

`pac_jiggle.py` edits only byte 38's low nibble in validated 40-byte records.
For the traced skinned-mesh path, the vertex contribution is
`(15 - (byte38 & 15)) / 15`. Reductions scale this numerator, round half steps
toward retaining more influence, and preserve the upper nibble. Every `xF`
value has zero vertex contribution, including `0x0F` and `0x8F`, not only 255.
Repeated edits use the retained source; zero contribution is never amplified.

This mode is selected by CPU setup in game build `1.0.0.2944`: routine
`0x142DD3680` unconditionally sets flag bit 7 at `0x142DD376C`;
`0x142DD3290` writes that result into offset 24 of the 72-byte
`SkinnedMeshSubMeshShaderData`. `GenerateIndirectRenderParamterBuffer` copies it
to offset 48 of the 168-byte `SkinnedMeshMainRenderParameter`.
`CSMainSkinnedMeshStreamOutVertexData` tests bit 7 to select low-nibble decoding.
The shader also contains a full-byte branch, but this CPU path does not select it.
This supersedes the earlier assumption that the two modes were equally plausible
for these meshes. It does not prove every other game path or version uses this mode.
The CPU setup flag is not the similarly numbered PAC metadata flag.

`tools/pac_shader_consumer_study.py` reads PASC v7/v8 shader containers. Its
candidate filter checks the record field name at every bit alignment because
current LLVM metadata strings are not necessarily byte-aligned. DXC reflection
and actual stride-40 buffer loads still establish record usage; a name match
alone is not proof. This is a bounded study of matching shaders, not an
exhaustive LLVM bitcode reader or proof that unobserved lanes are unused.

These are vertex blend weights, not spring constants or proof of live physics.
Bone overrides can replace the vertex blend. The upper nibble's other consumers
remain unresolved, so disabling must preserve it as well as all other record lanes.

## PAC cloth guides (read-only)

`pac_cloth_guides.py` decodes the known PAC 3/9 header's guide layouts 3 and 7.
The low nibble of metadata flag byte 1 selects the guide layout; zero means
there is no guide section, not that the model has no other physics. The guide
block follows the complete submesh descriptor table. It has its own bounding
box, up to 1024 vertices, triangle indices and a separate alpha bitmask.

Each 16-byte guide record contains three unsigned 15-bit coordinates, a fourth
10-bit bone palette slot at bytes 6–7, three more 10-bit slots packed at bytes
8–11, and four byte weights at bytes 12–15. The shader uses each weight divided
by 255; the decoder retains sums of 254 or 256 instead of silently normalizing.
Coordinates use the guide bounds, not any visible part's bounds.
`cpu_unskinned_vertices` separately retains the CPU initializer's full unsigned
coordinate interpretation. These positions precede skeletal transformation;
the CPU also normalizes valid skinning weights, unlike the shader path.

The reader also retains the two per-guide byte arrays, ordered index groups,
layout-7 group tags, complete 10-byte constraint records, per-vertex constraint
spans and edge indices. No unknown or apparently unused bytes are discarded.
`inspect_guide_topology` reports whether these tables match the guide's edges,
adjacent triangles and per-vertex references. The observed record classification
uses the low byte of the final word; its high byte varies in stock files and is
retained separately in the evidence summary and intact in the raw records.

`inspect_guide_particle_initialization` follows the PAC view constructor and CPU
particle initializer in game build 1.0.0.2944. Channel B equal to 255 initializes
zero inverse mass and position blend 1. Every other value uses the same inverse
mass: `1 / Mass` when the material's Mass is positive, otherwise 1. Intermediate
bytes do not scale mass. The report exposes the per-vertex 0/1 factors without
assuming a material's Mass.

When `UseVertexAlphaPositionBlending` is enabled, position blend is channel B
divided by 255, rounded to binary16. With the flag disabled, every value below
255 initializes blend 0. Reports show both cases because a PAC alone does not
resolve the active material. Channel A supplies the particle's group ID; only
IDs 1 through 31 select dynamic-fix bits in the traced base-movement shader.
Membership does not establish whether a runtime bit is active.

The cloth attachment report compares the two decoded mode-1 preparation paths:
candidate pools per connected component, and one pool for the entire guide mesh.
Initially fixed vertices and dynamic-fix group IDs 1 through 31 are eligible.
The selector retains up to four **distinct squared float32 distances**, keeping
the first guide index at an equal distance. A fixed vertex can select itself;
fractional channel B alone does not make a vertex an anchor. Reports include
selected indices and lengths before half upload. Default positions are CPU
coordinates before skinning; callers can supply initialized positions instead.
The PAC does not establish which runtime path is active.

`prepare_guide_cloth_attachments` requires explicit choices for component
separation, vertex-alpha blending and automatic weighting. It calculates anchor
lengths, normalized attachment-distance ratios, position blends and orientation
neighbor pairs. Ratios use mean distances before half upload. Equal-distance
ranges use one minus the initial blend and skip automatic weighting. Otherwise,
automatic weighting applies `clamp(base ** (10 * (ratio + shift)), 0, 1)` to
dynamic particles: it multiplies the initial blend with vertex alpha enabled,
or replaces it with vertex alpha disabled. Fixed vertices retain blend 1.

Orientation selection compares the first neighbor's packed ratio for each
triangle and retains the earliest triangle on a tie. Vertices absent from all
triangles report unknown neighbors. Float32 and CPU half packing follow the
traced operations; the reference uses Python's power function and does not
claim bit-exact `powf`, live activation, solver or collision parity.

The shared Python PBD parser retains `Mass`, `UseVertexAlphaPositionBlending`,
`UseRotationCorrection`, `UnderWaterGuideMeshVertexWeightCoefficient`,
`AutoWeightingExponentialBase` and `AutoWeightingInputRatioShift` for guide
inspection. The latter defaults are 0.4 and 0; they do not establish whether
automatic weighting is enabled. Decoded initialization defaults are mass 1, vertex-alpha
blending on, rotation correction off and underwater coefficient 1. A declared
`SimulationMode` resets rotation correction to on for cloth or off for spline;
later explicit options override it. Source order is retained, and `AttachedCloth`
options remain separate from the parent material. These fields do not replace
the preview's approximate solver or heuristic pins.

With an explicitly supplied material, the guide report calculates initial
inverse masses and selects the corresponding half-precision position blends.
These values precede long-range attachment preparation, which can modify blends
again. The report additionally compares both cloth-mode preparation paths with
automatic weighting explicitly disabled. These are calculation scenarios even
when the supplied profile is intended for another mode; neither the mode nor
the unresolved automatic-weighting switch is inferred from the profile name or
XML option alone. Supplying a material does not prove it is active in game.

The alpha bitmask and ordered group starts remain separate evidence. Neither
is used to infer pinning; group starts do not always match fixed vertices.
The traced ordered-group consumer prepares spline attachment data; cloth mode
uses a separate triangle-based preparation path.

`inspect_guide_constraint_geometry` derives rest lengths, triangle areas and
hinge angles from the authored records. It defaults to CPU coordinates before
skinning, or accepts explicitly supplied particle positions. The CPU uses the
same directed edge for both hinge normals, so flat adjacent faces have rest
angle pi. Optional bending coefficients follow the traced cotangent formula;
the report includes its cotangent limit and marks degenerate geometry explicitly.
Unrecognized records remain present without invented measurements.

The game expands each 10-byte PAC record to a 36-byte CPU record, then packs it
into a 16-byte upload record. Upload types distinguish distance, angle bending,
coefficient bending and triangle area. The latter requires both the global area
switch and material `UseAreaConstraint`; bending selection also depends on the
ordered initialization results. Rest measurements alone do not select an active
solver. They are mathematical values before half-precision upload, not bit-exact
CPU emulation.

`pac_cloth_skinning.py` provides a mathematical reference for the decoded
guide-to-render handoff. `prepare_guide_skinning_matrices` accepts externally
supplied guide animation frames and subtracts each shader-decoded rest position
through its frame. This preserves rotation about the guide, not just translation.
The frame's fourth column is metadata, not conventional homogeneous coordinates.

`blend_render_cloth_matrix` averages the four referenced guide matrices using
normalized render-to-guide weights. These weights differ from the unnormalized
guide-to-bone weights above. It then blends toward the caller-supplied ordinary
skeletal/jiggle matrix by `(byte39 & 63) / 63` multiplied by the weighted guide
`row0.w` runtime factor. A stored value of 63 bypasses guide access entirely.
Every fetched guide index must be valid, even if its weight is zero. The result
contains four XYZ rows for point transformation; normals require the inverse
transpose of the blended basis. This reference requires valid guide indices
and supplied runtime matrices; it neither generates those matrices nor emulates
missing GPU resources or bit-exact float/half arithmetic.

The runtime factor's traced material source is
`UnderWaterGuideMeshVertexWeightCoefficient`. `guide_runtime_blend_factor`
follows the CPU uploader's float32/half packing, including its subnormal rounding,
then the shader's saturation. Non-finite packed results are reported as unsupported.
The coefficient applies only to dynamic particles with underwater flag `0x80`; fixed particles,
dry particles and the `0x800000` override return 1. The override restores the
authored skeletal fraction rather than forcing full skeletal skinning. Lowering
this coefficient increases guide influence in that underwater branch; it does
not reduce spring stiffness. Water contact, override activation and material
selection require runtime inputs and are not inferred from a PAC.

Raw decoding retains zero weight totals. With an active guide buffer, all-zero
guide weights produce a zero matrix and a singular normal basis in the traced
formula. This does not prove source corruption because the runtime can bypass
the guide path. The existing editing wrapper still rejects zero skeletal or
guide totals; read-only decoding does not relax that export guard.

The read-only inspector also reports render bindings for each part at every
stored LOD, including bypass counts, referenced guides, weight totals and authored
skeletal blend values. Zero-total vertices are counted separately. Invalid guide
indices are counted with bounded source-offset examples, independently of guide
decoding. A static PAC cannot establish the active runtime guide buffer or the
final cloth contribution.

Initialization does not establish final motion: runtime overrides, active solver
selection, collision behavior and skeletal transformation remain unresolved here.
It does not replace the approximate simulation preview or enable pin editing;
changing fixed vertices can also require rebuilding the authored constraints.
Unsupported layouts, mismatched descriptor counts, out-of-range triangles and
truncated metadata report unavailable without reading into geometry sections.

Inspect loose decoded files with:

```powershell
.\.venv\Scripts\python.exe tools\pac_cloth_guide_study.py 'C:\path\model.pac'
.\.venv\Scripts\python.exe tools\pac_cloth_guide_study.py 'C:\path\model.pac' --material 'C:\path\profile.xml'
```

The command reads its inputs and prints JSON with source hashes, decoded guide
geometry, complete stored tables, particle initialization, rest-constraint geometry,
attachment candidates, topology comparisons and field offsets. Optional material
context applies to every input PAC and includes the profile's path and source
hash. Malformed material XML is rejected instead of becoming a successful
default calculation. The command
returns a nonzero status if an input is unavailable. Keep reports and game-derived
data outside the repository.

Related tests: mesh, static replacement, material, and package entries under `tests/`.
