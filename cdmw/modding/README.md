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

## PAB bind transforms

The fixed PAB skeleton reader retains four distinct row-major matrices per
bone: global bind, inverse global bind, local bind and inverse local bind.
The third/fourth blocks were previously discarded as copies. In the inspected
448-bone `phw_01.pab`, `localBind * parentGlobalBind` reproduces global bind
(maximum absolute float error `3.61e-6`), and the stored scale/quaternion/position
reconstructs local bind. Root local and global transforms coincide. This is
evidence for that fixed layout, not for the legacy scan's guessed records.

Python exposes the local pair as `Bone.local_bind_matrix` and
`Bone.inv_local_bind_matrix`; manually created bones default to empty tuples.
Fixed-layout skeletons also retain the original 22-byte `Skeleton.source_header`
so separately decoded tail sections can use their actual format and flags.
Manual and legacy-scanned skeletons have no retained fixed-layout header proof.
Rust retains the same pair and includes it in the structural fingerprint.
Older serialized Rust skeletons deserialize missing local matrices as absent,
without substituting identity. These retained transforms enable hierarchy
animation input; they do not establish jiggle activation or game animation timing.

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

### Bone jiggle reference

`pac_jiggle_bones.py` implements the ordinary and timed instance branches of
`UpdateJiggleEffect` in build `1.0.0.2944`. The two inspected shader variants have
identical function bodies (source SHA-256 prefixes `25bbc446fe96` and
`3033dabff732`). This reference requires resolved animation and runtime records;
it does not infer that a PAC has an active solver from its vertex weights.

`step_jiggle_bone` takes the previous 116-byte `JiggleBone`, the current command
record, a 264-byte `SkinnedMeshJiggleShaderData`, a selected 64-byte animation
matrix, and a 272-byte `CharacterTransformData`. The caller supplies the original
bone index after LOD mapping, frame index, global jiggle delta time, view origins
and object reset flag. The result contains the new packed `bone`, four row-major
`matrix` rows and a `reset` indicator. No fixed timestep is invented.

The reference covers frame continuity, origin-speed resets, platform translation,
animation decomposition, seeded spring acceleration, damping, limits and matrix
reconstruction. Linear velocity and displacement limits act on vector lengths
and scale with the character parameter span, bounded to a multiplier of 1–5.
Angular limits apply independently per Euler axis and are not scaled. Damping is
a multiplier per update, including a zero-delta update. Position/angle clamps do
not reconstruct velocity. The seed uses float32 products of the old position,
velocity, rotation and angular velocity, plus original bone and frame indices;
the GPU random sequence differs from the CPU solver's global generator.

`prepare_jiggle_command` consumes a 48-byte `JiggleCommandShaderData` plus
resolved skeleton/object/shader records. It returns the target `state_index`
and cleared 116-byte command `bone`, populated with the instance payload and
flags 3. Missing jiggle data or LOD above 1 skips the command. The address uses
the original bone index and the skeleton's **LOD0** animation offset, including
when the current LOD is 1. Resource lookup and collision between concurrent
commands for the same bone remain caller responsibilities.

The selected instance record's mode has these consumed masks:

| Mask | Behavior |
| --- | --- |
| `0x4` | Enable linear effect motion |
| `0x8` | Enable angular effect motion |
| `0x2` | Use an axis-angle effect instead of Euler springs when angular motion is enabled |

Pending effects add velocity once and reset elapsed time. A continuing effect
uses its retained state without injecting the impulse again. Euler effects
perturb their initial angles when the angular impulse is nonzero and perturb
their animation target before fading. The axis-angle path evolves a perturbed
axis toward X and applies its rotation before the animated rotation.

Fade is `saturate((fadeRange - duration + elapsed) / fadeRange)` for a positive
fade range; otherwise it is zero. Output weight is authored weight times
`1 - fade`. Duration independently controls expiration, so zero fade range
still ends the effect. Before fade reaches float32 `1e-4`, linear and axis-angle
paths divide their stored velocity by damping **after** integrating and applying
speed limits. Euler effects keep damping. A weight below float32 `1e-4` restores
animation and clears motion before any bone-mask override, while retaining the
updated runtime axis/angle and timer. A motion reset does not cancel or retrigger
an existing effect. Undefined consumed divisions/normalizations are rejected.

`jiggle_bone_blend_override` decodes the output metadata separately. Any nonzero
low-two-bit shader mode sets row0.w to 1. Mode 2 scans up to 32 packed u16 bone
indices and replaces row1.w with the last matching mask value. Values are not
clamped. Unmatched bones retain the supplied instance weight, which is zero on
the ordinary path. These overrides can supersede the later byte-38 render blend.

The Rust counterpart is `cdmw_mesh::jiggle_bones`; its focused native tests use
owned synthetic vectors generated from this reference, including chained native
state feedback. The decoded native core now drives the Jiggle pane through the
rig/preview adapter described below. Wind/water samples, live dispatch/resource
activation and character-profile ownership remain explicit inputs. The reference
uses Python arithmetic
except where float32 storage/seed bits matter; random feedback can amplify
rounding differences over time. Synthetic math tests do not establish GPU,
rendered or in-game parity. Reflected instance-frequency fields are not consumed
by these inspected update bodies and are not exposed as proven solver controls.

### CPU jiggle activation and shader handoff

`pac_jiggle_runtime.py` provides pure reference stages for a supplied 0x220-byte
CPU runtime record. This is runtime state, not a PAC record or a live-process
reader. Constructor `0x15144F5D0`, update `0x142DB60D0`, resource refresh
`0x142DE7D40` and upload `0x142DDFFA0` establish the field-to-shader chain in
build `1.0.0.2944`:

- `advance_jiggle_hit_window` updates the float32 timer at +0x10C, active byte at
  +0x110 and flags at +0x154. Bit 0 follows the hit window; bit 1 follows the
  nonempty mask count at +0x158. A positive timer remains active during the update
  that reaches/passes zero, and is cleared on the following update. Consequently,
  mode 3 uses per-bone instance weights; expiry restores mode 2's profile masks.
- `refresh_jiggle_runtime_resources` preserves the old current state offset as
  the previous offset and updates the shader/state/command slots. Changed slots
  trigger settings lookup: the active hit window chooses resolved hit settings,
  otherwise the resolved named/default profile. Eight runtime overrides replace
  their corresponding values only when strictly positive. Unchanged slots skip
  this copy, even if the timer state has changed.
- `jiggle_runtime_shader_upload` returns the exact +0x114..+0x21C 264-byte slice
  only when the shader slot is assigned. `jiggle_runtime_can_release` requires
  no platform or active hit window, the caller's empty profile ID, and invalid
  shader, command, current-state and previous-state slots.

These helpers preserve unowned bytes. They do not allocate GPU resources, update
platform transforms, resolve a character's description or establish call order.
The global normal/water settings pair is separately consumed by
`UpdateJiggleBoneSample`; this character-resource branch selects named/default
versus hit settings. Source presence alone does not establish active game physics.
Focused tests compose the CPU flags/upload with the existing bone-mask shader
reference; this is synthetic nonvisual evidence, not captured game playback.

### Wind and water jiggle samples

`pac_jiggle_samples.step_jiggle_sample` decodes `UpdateJiggleBoneSample` from
build `1.0.0.2944`. It consumes one 96-byte sample plus the supplied 224-byte
`JiggleBoneEffectGlobalData` block (constant-buffer bytes 48..272), and returns
the updated record and matrix at `1024 + sample_index`. The shader accepts
indices 0..511; the second sample-offset uint selects the wind/water boundary.
CPU publisher `0x142D8FE90` writes a boundary of 256, clamps its supplied dt to
0.03, and copies distinct normal/water settings. The reference consumes the
already-prepared block without inventing weather values or a sample direction.

Only the first cycle timer advances. Rollover discards elapsed overshoot and
clamps the newly perturbed duration to float32 0.0333. Water rollover rotates
the retained linear cycle vector with random yaw/pitch and replaces its angular
cycle vector; it does not substitute the global water direction in this shader.
The second cycle-info pair and the first cycle vector's fourth component survive.
The GPU random seed combines sample/frame indices and stored velocity float bits.

Both branches first apply the decoded linear/angular springs, then add external
velocity and integrate position/rotation **again**. This second integration also
includes the spring velocity. There is no final speed/displacement clamp after
the environment term, so the settings' spring limits are not final sample bounds.
Wind consumes the prepared direction/rotation perturbations, speed, acceleration,
damping and sinusoidal bias/rate. Its angular sign is positive only when the sine
is strictly positive. Water uses its retained cycle vectors and speed modulation.
Reflected strength/direction fields not reread here may still affect upstream
preparation; absence from this shader does not mean they have no game effect.

Nonzero `isCPUMode` preserves the supplied sample and still emits its matrix.
It is not a reset. The same CPU publisher has a separate update branch at
`0x142D9035D..0x142D90A80`, using a mutable CPU RNG and different water-direction
initialization. This reference implements the GPU branch and its CPU bypass,
not that CPU simulator. Live mode selection, sample initialization, weather
production and the water-sample consumers remain unresolved.

Focused synthetic tests cover cycles, retained state, separate settings, force
ordering, CPU bypass and a generated wind matrix through the existing vertex
blend. `cdmw_mesh::jiggle_bones::samples` is the native counterpart, with 41
synthetic reference vectors including native state feedback. The Jiggle pane
uses its wind samples with manual preview inputs and zero initial state. Water
remains a core/reference path until a render consumer is verified. Neither
Python nor native arithmetic establishes GPU-exact or in-game playback parity.

### Bone-to-render handoff

The native counterpart is `cdmw_mesh::jiggle_skinning`; its focused tests include
the decoded Rust bone step through inverse-bind preparation to a render vertex.
Both implementations require explicitly resolved runtime buffers and maps.

`pac_jiggle_skinning.py` connects the bone reference to the retained render
vertex and guide-cloth blend. It traces `ComputeSkinningMatrix2` (source SHA-256
prefix `db7bcc0dd8b7`) and `CSMainSkinnedMeshStreamOutVertexData`
(`6a00cd165666`) in build `1.0.0.2944`.

`prepare_jiggle_bone_skinning` implements the ordinary inverse-bind path,
including LOD0, for one resolved bone. Both animation and jiggle basis rows are
scaled in character space before `inverseBind * pose`; translation is not scaled.
The solver's row0.w marker and row1.w override are removed from the simulated
pose and written onto the **ordinary** skinning matrix after composition.
Special cross-LOD inverse-variant corrections are not implemented.

`blend_render_jiggle_matrix` resolves PAC slot to original bone through the
supplied palette, then to the skinning buffer through the supplied index map.
It normalizes all six skeletal byte weights, or four for guide-bound vertices
and nonzero main-render flag modes `flags & 0xE00`. Every selected index must be
valid even at zero weight. All-zero weights produce zero XYZ rows. A positive
weighted row0.w selects the weighted row1.w instead of byte 38's contribution.
Positive overrides above one extrapolate; nonpositive overrides bypass jiggle.
Nonzero `0xE00` modes and a missing active jiggle buffer also bypass jiggle.

Positive wind weight fetches samples at `1024 | (originalBone & 255)`, before
the skinning-index remap. The normalized sample basis premultiplies the blended
jiggle basis, including its fourth-column terms, while sample translation is
added separately. Wind blending precedes the final ordinary/jiggle blend.
The returned XYZ rows have a canonical affine fourth column for direct use by
`blend_render_cloth_matrix`; the blend metadata has already been consumed.

These functions require resolved buffers and explicit activation. Wind samples
can be supplied by the separate reference above. These functions do not
infer rig binding, implement special LOD corrections,
or establish production-preview, normal-packing or in-game parity. Synthetic
coverage composes bone motion, inverse bind, byte-38 blending and guide cloth.

### Whole-rig pose and frame reference

`pac_jiggle_rig.py` assembles a fixed PAB and an already resolved PAC palette
into an immutable `JiggleRig`. It validates original bone ordinals, parents,
cycles, finite affine matrices, both inverse pairs and the stored local/global
relationship. Missing transforms and legacy-scan rigs are rejected. The bound
is 4096 bones; a partially usable rig is not published.

An optional existing `NeutralMeshAppearance` must carry the same palette and
one skin matrix per bone. Its neutral global pose is `originalBind * skinMatrix`;
neutral locals are derived relative to those neutral parents. Original inverse
binds remain unchanged. This uses the editor's established PABC interpretation,
including its axis reconciliation, rather than applying raw PABC frames again.

`compose_jiggle_pose` takes optional **absolute local matrices** keyed by original
bone ordinal. It composes changed branches in parent order, including forward
parent references, while retaining untouched global matrices exactly. Jiggle
output is not fed into child animation targets. Root/world motion is supplied
separately through the character-transform record.

`step_jiggle_rig` advances all bones through `step_jiggle_bone` and
`prepare_jiggle_bone_skinning`. Runtime settings, character motion, scales,
reset/frame/time and optional pending command records are explicit inputs.
Its result contains `bone_states` for the next step, `skeletal_matrices`,
`jiggle_matrices` and `reset_bones`. Buffers use original ordinals, so a caller
uses an identity skinning-index map for this assembled reference; the game's
actual buffer allocation and LOD map are not inferred.

The resulting matrices act on original PAC coordinates. Already-neutral editor
geometry must first pass back through the inverse of its **blended** appearance
transform, as in `NeutralMeshAppearance.to_source`. Substituting neutral inverse
binds or applying skinning again to displayed positions changes the result.
Focused coverage includes this composition, hierarchy edits, continuing effects
and mask-index ownership. The retained Damiane body and 0145 mesh also reproduce
their rest positions through the complete rig reference. This establishes
read-only source math, not live profile selection, game animation, production
preview integration, GPU arithmetic or in-game parity.

The native `cdmw_mesh::jiggle_rig` consumes a snapshot of the prepared palette,
parents and original-inverse/neutral-global/neutral-local matrices, stored as
4-by-4 row arrays. It recomputes parent order and validates the snapshot before
stepping all bones. Its preview binding inverts the **blended** neutral rest
matrix once, then composes that inverse with each current render transform to
preserve displayed sculpted positions. This is tested with different bone scales,
where blending inverse bone matrices gives the wrong result. State and bindings
cannot be used with a different rig instance. An explicit jiggle-buffer bypass
handles all-disabled comparisons independently of byte38 and bone overrides.
`mesh_rust_jiggle.py` publishes this rig and retained LOD0 records to the owned,
hash-checked `jiggle-rig.json` payload. Unchanged records remain byte-identical;
edited skin weights use the existing PAC encoder. Geometry-only and contribution
edits reuse that payload. The native Jiggle pane prepares bindings on its bounded
loader, then plays a procedural root-pose test using decoded initialization settings.
Preview frames stay separate from authored mesh data. This integrates the decoded
math, but does not establish runtime activation, live profile selection, wind/water
generation, guide cloth or in-game parity.

## PABV skeleton volumes (read-only)

`pabv_parser.decode_pabv` decodes the authored collider geometry in
`character/binary/skeletonvolume/*.pabv`. The traced loader in build
1.0.0.2944 is `SkeletonVolumeAsyncLoadingTask`, followed by the record reader
at `0x1426A9170`. Standalone PABV files and embedded PAB/PAC volume sets share the
record reader; neither is the PAC cloth guide mesh. The known PAR `0x36/1`
standalone header contains a flags word at byte
16 and a ushort record count at byte 20.

`decode_pab_embedded_volumes` reads the default volume sets retained in a
fixed-layout PAB `1/5`. After its bone records, PAB flag `0x10` adds one uint
per bone and `0x2` adds one byte per bone. The primary volume count follows;
separate rendering and physics sets may follow in that order. EOF can omit
either later set, while a serialized zero count remains an explicit empty set.
PAB flag `0x4` adds per-volume flags. These bits differ from standalone PABV
flags. The embedded loader converts keys below the bone count from indices to
stored hashes and retains larger keys, independently of PAB flag `0x1`.
The returned records use materialized hashes with original absolute PAB byte
offsets; strict rig resolution still rejects unresolved or ambiguous hashes.

This path is traced through `SkeletonAsyncLoadingTask` (`0x142CCEF80`), PAB
loader `0x142D34A90`, and resource-manager slot `0x48` (`0x142CD0B20`). Bone
tail sizes come from `0x1426A9D40` and `0x15022B1D0`; embedded index conversion
comes from `0x151271F58`. The default primary/rendering/physics resources are
stored at skeleton-resource offsets `0x110/0x118/0x120`. The copied 448-bone
PHW rig contains 28 primary capsules, 16 rendering capsules and an empty physics
set, consuming the full file. Every volume resolves to that rig. These defaults
do not establish the final appearance override or runtime collision activation.

`decode_pac_embedded_volumes` locates the model's own volume set in decompressed
PAC `3/9` metadata with guide layouts 0, 3 or 7. After descriptors and any guide
data, metadata bit `0x2000` adds 24 bytes of auxiliary bounds and two
ushort-counted arrays with strides 16 and 24. The ushort-counted bone-hash
palette and 24-byte model bounds follow; bit `0x4` adds another 24-byte bounds
block. The volume count and shared records come next. Every PAC volume has a
flags word, independently of bit `0x4`. Later metadata remains outside the set.
The undecoded embedded bone-group branch (`0x20`) fails explicitly. Raw keys,
geometry, flags and absolute offsets are retained; the decoder does not infer
index conversion or expose these records as already bound to a skeleton.

The PAC path is `CharacterMeshAsyncLoadingTask` (`0x142CD7030`), metadata reader
`0x142C61960`, guide/palette reader `0x142C63CE0`, and bounds/volume reader
`0x142C65090`. Manager slot `0x50` (`0x142CD0FD0`) enables the record flags
byte before calling `0x1426A9530`. A ready model resource's volume set at
`+0x110` takes precedence over PAB/body/head sources in `0x142D91540`; an empty
serialized model set does not create that resource. Among five copied PHW
samples, lower-body `0166` contains one capsule and upper-body `00_0001`
contains two, with keys matching their PAC bone-hash palettes. The `0145`,
upper-body `0002`, and Damiane nude samples have explicit empty model sets.
This does not establish runtime activation or a cause for differing jiggle.
`tests/test_pac_embedded_volumes.py` checks metadata boundaries, all three
supported guide layouts, mandatory flags, truncation and immutable raw keys.

Each record stores a bone key, a 4x4 local matrix, a retained usage byte and a
serialized shape tag. Tags 0/1/2/4/5 become engine box/cylinder/mesh/sphere/capsule
types 2/3/4/1/5; tag 3 is rejected by the traced reader. Boxes store dimensions
in z/x/y order, cylinders and capsules store radius/height, spheres store radius,
and mesh shapes store ushort-counted float3 vertices and ushort indices. Header
bit `0x2` appends a flags uint to every record; absent flags initialize to zero.
Unknown header flag bits are retained, without assigning them behavior. Source
offsets and immutable decoded values remain available for inspection.

Header bit `0x1` identifies bone-name hashes; otherwise the authored keys are
indices into the selected skeleton. `resolve_pabv_bones` requires an explicitly
supplied fixed-layout PAB and rejects missing, ambiguous or out-of-range keys.
It does not select a character variant, silently bind an unmatched shape to the
root, or assume that a filename identifies the active skeleton volume.

`pabv_cloth_collider_definition` connects sphere/cylinder/capsule geometry to
the existing 104-byte definition consumed by `update_guide_cloth_collider_result`.
The CPU producer at `0x142D3EE80` copies the local matrix, radius and height,
and initializes the low type word and both local-center fields to zero. Its
runtime bone sets replace flag bits `0x2`, `0x4` and `0x8`, so the helper requires
explicitly resolved flags instead of treating the source word as final. Box/mesh
geometry can be inspected but is not substituted with approximate primitive
contacts.

`prepare_pabv_cloth_colliders` performs the primitive producer's flag override
and deduplication after strict bone binding. It requires all three runtime hash
sets explicitly, keyed by output bits `0x2`, `0x4` and `0x8`. These are not
automatically equated with the material XML inclusion/exclusion name lists.
The comparison at `0x143A52AC0` checks both type words and flags exactly, then
uses an inclusive float32(0.001) tolerance for radius, height and all 16 matrix
values. Bone identity does not participate. The first matching definition and
its binding are retained; matches are checked against kept definitions in source
order, without transitive grouping. Returned source ordinals preserve that
provenance. The activation summary is only the producer's OR of flag bit `0x1`;
it does not establish whether the game enables the collider group.

`default_pabv_cloth_flag_bone_sets` supplies the decoded initial profile from
the PBD manager's successful configuration-load path in build `1.0.0.2944`:
flag `0x2` contains pelvis, both thighs, calves and feet; `0x4` contains both
upper arms; `0x8` contains both thighs, calves and feet. The loader populates
only empty sets, so this is a fresh-manager profile, not a claim about every
live instance. Bone names are hashed case-sensitively without a NUL using the
existing PA checksum algorithm (`length + 0xDEBA1DCD`). All 448 stored PHW rig
hashes matched that calculation in the copied-input probe.

The owner link is traced from the graphics manager's virtual getter at slot
`0x568`, through character-resource initialization at `0x151009935`, to the
PBD configuration loader `0x1435F5440`. The initial sets are populated at
`0x1435F5F87..0x1435F6364`, independently of each material's inclusion,
exclusion and temporary-fix lists. Callers must choose this initial profile
explicitly; preparation does not silently replace supplied runtime sets.

Active appearance metadata is required to select overrides of the rig defaults. For example,
the shipped Damiane `00` Nude prefab declares `SkeletonVolumeName`, while the
`02` Nude prefab has no volume declaration. A replacement mesh's filename alone
therefore cannot establish which collider file the game uses. The selected
Damiane `0111` Head prefab has no `SkeletonVolumeName` override.

When a ready model-level set is absent, the cloth source follows body/head
**`SkeletonVolumeName`**, separately from
`RenderingSkeletonVolumeName` and `PhysicsSkeletonVolumeName`. The Nude parser
stores these at property offsets `0x78/0x80/0x88`; appearance assembly copies
them into compact resource fields `0x28/0x38/0x40`. The Head parser's volume
at `0x68` becomes compact field `0x30`. The primary body/head result reaches
the collider source's `+0x30` at `0x142D94CFF`, then `0x143648EB0`. These offsets
belong to different structures. An earlier rendering-volume interpretation was
too broad; a rendering override must not replace the cloth source by name alone.

`merge_pabv_body_head_volumes` implements the ready-source merge at
`0x142D3EB50`, called through resource-manager slot `0xA0` (`0x142CD4990`). It
copies every body record in order, then replaces only the first `Bip01 Head`
record with the head source's first match. It does not append the remaining
head records. Both matches are required when a head source is supplied. Legacy
indices require each source's explicit matching rig before merging; the head
never implicitly borrows the body's index layout. The materialized result
uses hash keys and per-record flags, and retains `(input, record)` provenance.
These are decoded records, not an exported PABV or its original header.

Automatic resource selection, compiled-resource overrides, load-failure handling,
any later runtime set changes and native preview integration remain separate
work. The merge helper reports missing head matches rather than silently
choosing a different source; runtime resource fallback remains caller work.

`tests/test_pabv_parser.py` covers both flag layouts, all decoded shape tags,
source bounds, strict rig binding and a capsule passed through the existing
animated collider calculation. `tests/test_pab_embedded_volumes.py` covers
PAB tail flags, separate volume sets, absolute source offsets, index conversion,
truncation and primary geometry preparation. Shipped Damiane and standard body volumes have
also been decoded from read-only copies; this is format evidence, not proof of
visible collision behavior or game parity.

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

`pac_cloth_preview.build_cloth_preview_snapshot` now prepares the guide data for
native playback using the host's already resolved PAB/PAC palette and neutral
appearance. Animation frames preserve guide weights divided by 255; CPU rest
geometry uses normalized weights and the separate full-16-bit coordinates.
Constraint lengths, angles and areas retain the decoded half upload. Fixed
points come from channel B equal to 255, with the optional vertex-alpha blend
retained separately. Undecoded constraints, zero guide-bone weights and invalid
palette references make this capability unavailable instead of inventing pins.

The existing owned `jiggle-rig.json` can carry an optional `cloth` snapshot;
`jiggle.decoded.cloth` reports its availability, guide/fixed/area counts and
`rotation_available`. Orientation neighbors use explicit per-component,
vertex-alpha preparation with automatic weighting disabled; this does not infer
the active runtime material. Older snapshots without neighbors still support
translation-only playback.
It is cached with the source and rig, uses the existing atomic payload writer,
and preserves all retained render record lanes. A missing or unsupported guide
mesh leaves decoded jiggle available. This additive transport does not change
the payload version or require older readers to consume the new member.
The native `cdmw_mesh::cloth` core consumes this snapshot with retained render
records. Its controlled preview profile uses unit dynamic inverse masses,
explicit gravity/damping/stiffness, a bounded Jacobi schedule, optional vertex
alpha and a preview floor. These choices are not inferred active game settings.
Optional two-edge guide rotation uses the decoded frame correction and binds
edited positions through the full neutral guide/skeletal matrix blend. Unknown
neighbors disable that option; degenerate frames stop playback without publishing
an invalid frame. Area records remain counted but inactive; runtime
dispatch/overrides and the full collision stages remain incomplete. The native
core is connected to Mesh Data > Cloth through the existing bounded loader and
draw-only motion controller. Current/original/disabled comparisons use verified
byte39 contributions; current rules evaluate original neutral source heights to
match PAC output after sculpting. These arrays are also available on cloth parts
without jiggle flags. Preview-only solver settings and controlled root motion do
not modify PACs or establish game-equivalent playback.

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

The native 16-bit variants of `ComputePbdProcessConstraints` retain descriptive
reflection names where the packed variant exposes `_pN` words. Their byte sizes
and offsets agree. Relevant runtime fields include:

| Record | Byte offset | Half-float field |
| --- | ---: | --- |
| Per-frame (100 bytes) | 66 / 68 / 70 / 72 | Modified stretch / bend / area / restore-angle stiffness |
| Per-frame | 76 / 78 | Elasticity / fading ratio |
| Per-frame | 80 | Stretch constraint follow-the-leader ratio |
| Particle extra (28 bytes) | 8 / 10 | Stretch / bend stiffness override |
| Particle extra | 12 / 14 / 16 / 18 | Restore-angle / elasticity / gravity / damping override |
| Simulation parameter (312 bytes) | 264 / 266 | Stretching scale / overstretch reference ratio |

`pac_cloth_constraints.py` implements the decoded core stretch, angle-bending
and coefficient-bending projections as mathematical references. They return
per-particle position corrections from one input iteration, before contacts,
flag propagation and dispatch. Stiffness is supplied per particle;
`decode_guide_constraint_stiffness` selects the packed runtime fields above,
where a negative override falls back and zero is an explicit override. These
modified runtime values are not assumed to equal the material XML values.

Stretch target length applies bone scale, then blends toward the animated edge
using the low byte of `packedSmoothingRatios / 255`, then applies stretching
scale. Correction uses the uploaded inverse sum of initial inverse masses;
recomputing it from current masses changes the result. Follow-the-leader can
replace the mass pair with `1-ratio` and `1+ratio` according to LRA ordering,
subject to the decoded thresholds and each particle's underwater state. The
short-edge stiffness reduction also retains its runtime and extra-data gates.

Angle bending uses the authored same-edge normal convention (flat angle pi).
Coefficient bending uses positions relative to the first endpoint, including
when half rounding leaves a nonzero coefficient sum. Their different
denominator/degeneracy thresholds are preserved. Type 2 alone does not select
coefficient bending: guide mode, flags2 bit `0x400`, effective input-position
blend below 0.5 and bend/iteration gates also participate. The blend is particle
half 94 or its nonnegative extra-data half-6 override, not `_cr` at half 90.
`select_guide_bending_projection` selects the formulation after eligibility is
established; higher blends and other eligible cases use angle bending. All six
inspected normal-step shader variants leave type-3 area
records unprojected in this constraint loop. That does not establish global
area support or behavior in other stages. These references do not implement a
complete solver or change the approximate preview.

`pac_cloth_base.py` provides the normal base-step force, damping, contact-response
and position-prediction math, checked against packed and native-16-bit variants
of `ComputePbdProcessBaseMovement`. It operates after animation/space adjustment
and runtime eligibility selection. Gravity is parameter half 260, or scene
half 82 when frame bit `0x4000000` selects that override, plus parameter half
262. Extra-data half 16 replaces the entire sum only when it is zero or negative;
positive values mean fallback. Damping uses a different rule: a nonnegative
extra-data half 18 overrides parameter half 256. Neither rule invents a clamp.

`integrate_cloth_forces` applies gravity opposite the supplied scene direction
and adds the decoded Y-only buoyancy term using density and inverse mass. Bone
inertia uses frame float3 at 12 times parameter float 48, limited by global PBD
float 1132 before adding resolved environmental acceleration. The caller must
supply that environmental term after air/water force construction, its separate
cap, orientation response and wave modulation. The explicit external-force
skip still permits gravity/buoyancy; it does not mean a stationary particle.

`apply_cloth_damping` runs after forces. Its axis coefficients are `float32(0.1)`
times damping, with frame `0x2000000` adding the global
`_positionBasedDynamicsParameter.x` only to X/Z. This is a per-step multiplier,
without timestep exponentiation. Frame flag `0x4` plus a non-`FFFF` u16 at 74 selects
the 36-byte `AdvancedDamping` record: center position, center velocity and angular
velocity. That path adds a correction toward rigid group motion using the
particle's **old** position and velocity, preserving newly added forces.

`cloth_contact_velocity_response` implements the already-eligible inward-contact
branch: tangential motion scales by `1-friction`, while normal motion reverses
with restitution. `predict_cloth_position` advances position and projects it
against the gravity-direction ground plane. With ground collision disabled,
the shader still uses a scalar limit of 1000 in that direction. Neither helper
silently normalizes the supplied direction/normal. Runtime contact eligibility,
special movement boosts, flag bookkeeping, scene sampling and reset/hold paths
remain separate. Synthetic composition tests connect this base math to authored
stretch constraints and final movement; a repeated-step test checks damped fall
against an independent geometric-series solution. This is not a complete solver
or evidence of visible/game parity, and does not change the preview.

`pac_cloth_state.py` connects timing, guide/static animation and explicit state stages
from the same base shader:

- `select_cloth_base_substep` reads the supplied 1216-byte global parameter
  record and returns no step when its clock gates fail. Frame **flags2** `0x8000`
  selects the scaled clock; flags2 `0x800` selects variable delta time and runs
  only substep zero. Both modes still require the index below the selected step
  count. Fixed time below float32(0.0001) skips the invocation unless variable
  mode or frame **flags** `0x400` applies. Scene half 94 multiplies integration
  time, not the guide animation ratio. In fixed mode that ratio is saturated
  `(index + 1) * fixed_time / (execution_interval + previous_remaining_time)`;
  a denominator at or below float32(0.000001) selects 1. Variable mode selects 1.
- `prepare_guide_cloth_animation` consumes the original particle, invokes fixed
  preparation below, and reads already-resolved guide and character matrices.
  The guide translation is transformed by the character's three basis rows,
  then frame translation is subtracted. World translation is not added. The
  anchor interpolates from `prev_ix`; frame flags `0x400` uses the full anchor.
  Resource lookup and water/air-pocket sampling are explicit caller work.
- `prepare_static_cloth_animation` resolves static anchors from supplied host,
  attachment and particle records. It includes component transforms, reference
  pairs and first-step adjustment, then returns the position for the later water
  query. Static anchors do not use guide interpolation or subtract frame
  translation. The caller supplies the correctly selected transform-buffer bank.
- `prepare_cloth_fixed_state` clears per-step flags and evaluates fixed groups
  1 through 31 using their original bit indices. Existing particle `0x4000`
  vetoes group fixing below overstretch ratio 99, before the guide branch clears
  that flag. A valid shrink-mask resource requires its resolved uint32 sample;
  zero fixes the particle and sets `0x800000`. Nonpositive inverse mass also
  bypasses dynamic integration but does not itself set group-fixed bit `0x40`.
- `select_cloth_base_integration` runs after animation/space adjustment and any
  input-position collision. Frame flags `0xC00` return early before considering
  fixed particles; all later stages must be skipped. Otherwise, fixed particles
  copy adjusted `_ix` into both `_p` histories while preserving velocity,
  working `_x`, contact data and the velocity-reference position. They still
  require final flags/pre-collision cache/hold processing with zero non-gravity acceleration.
  Dynamic particles continue through forces and prediction.
- `predict_dynamic_cloth_state` consumes already-adjusted particle positions,
  prepared flags and velocity after forces/damping. Guide contact requires
  `cr > 0`; static contact requires particle `0x10000000`. An eligible contact
  clears that flag even when outward velocity needs no response. The special
  backward boost changes prediction only, retaining the pre-boost stored
  velocity. Skipping integration still applies ground projection to prepared
  `_p[0]`, and the velocity-reference position receives working `_x`.
- `finalize_cloth_base_state` evaluates the outward-force flag, independently
  resets the two pre-collision cache blocks when requested, and invokes the hold
  stage below. Fixed particles use zero acceleration; dynamic particles use
  retained non-gravity acceleration, not stored velocity or full acceleration.
  Frame flags `0xC00` bypass this stage entirely.
- `finalize_cloth_base_hold` advances the pinch timer after preceding flag/cache
  stages. Flags `0x300` reset its base to 100000. Existing particle `0x80000000`,
  frame flags2 `0x10000`, overstretch ratio at least 99 and a non-gravity
  acceleration absolute-component sum strictly below float32(0.1) hold both
  position histories at working `_x`; stored velocity remains intact.

Guide space adjustment has two separate decisions. Frame flags `0x1` skips
external forces; flags2 `0x100` skips position integration. A special movement
case enables both only with frame `0x20000000`, scene `0x200`, particle LRA ratio
below float32(0.7) and bone-velocity w strictly between -30 and -10. This is a
narrower window than prediction's later backward boost. Original guide particle
`0x4000` forces the first decision on and the second off, before fixed preparation
clears that bit. Water classification, gated by flags2 `0x1000`, clears both.

When external forces are skipped on substep zero, the shader aligns the old
anchor direction with the new one and applies that matrix to working `_x`.
The result replaces `_p[0]` when integration is skipped, otherwise `_x`.
It uses the full new anchor and clears velocity, retaining `_p[1]`, `prev_ix`
and the velocity-reference position. Anchor lengths below float32(0.000001)
use identity; cosine below float32(-0.9999) uses `-I`, including the third axis.
Later substeps retain the skip decisions without repeating this adjustment.

Static attachment requires frame flags `0x200000`, skinning record uint32 at 60
below `FFFF`, and simulation parameter uint32 at 92 below `1FFFFFFF`.
Frame `0x80000` with overstretch below 99 vetoes attachment unless extra flags
bit `0x4` suppresses that veto. An active extra-data resource requires its actual
28-byte record; missing resource indices do not consume a supplied override.

The attachment path applies parameter half 302's scale, quaternion halves
304 through 310, and translation halves 296 through 300 to the original local
position. The quaternion is not normalized. Then it applies the attaching
instance's basis and its translation relative to the host. Instance byte 12
contains signed tile Z in the low half and tile X in the high half; tile offsets
use 1000 units. Relative translation subtracts the small local translations
before adding tile differences, retaining detail far from the origin. Ordinary
static anchors use the host basis without adding its translation.

When both extra-data `dynamicFix` indices at 22 and 24 are valid, the anchor
instead follows their current particle positions. It aligns their original
local edge, transformed by the selected basis, to the current edge. The length
ratio divides by the **untransformed** original local edge length. This path
uses the original local position, bypassing the earlier component offset and
relative translation in the final anchor. A zero original edge has no supported
finite shader result and is rejected. A collapsed current edge selects the
first reference position. Group/mask-fixed reference followers snap both `_x`
and `_p[0]` before first-step adjustment; zero inverse mass alone does not.

Static first-step adjustment uses the same direction-alignment math and separate
force/integration decisions described above, but original particle `0x4000`
does not apply the guide override. Water classification happens afterwards and
does not clear those decisions. Its query position includes the host world
translation, frame translation and the **adjusted working position**. The shader
subtracts the previous-view position when constructing the texture coordinates.
Skinning records, reference records and unrelated particle fields are preserved.

Final outward-force classification uses working `_x` and the negative scene
gravity direction without normalizing that input. With `u = -gravity`, it forms
`r = x - dot(x, u) * u`, normalizes `r + length(r) * u`, and projects retained
non-gravity acceleration onto that direction. A result strictly above 30 sets
particle `0x40000`; otherwise it clears the bit. A zero direction has no supported
finite shader result and is rejected.

The pre-collision cache is a ten-uint window addressed by simulation parameter
uint32 at 148 plus `particle_index * 10`, in the resource selected by uint16 at
226. It is **not** particle `sbc_offset` at 124. With a valid resource, frame
`0x80000000` resets its first five words to `(0, FFFFFFFF, FFFFFFFF, FFFFFFFF, 0)`;
frame `0x10` independently resets the last five to
`(0, FFFFFFFF, FFFFFFFF, FFFFFFFF, FFFFFFFF)` and clears particle `0x20000000`.
The caller supplies the resolved window when either reset is active. These
writes preserve the particle's contact normals and radius.

Contact-cache writeback requires an explicit shader storage variant. Without
frame flags2 `0x200`, the packed variant clears both complete contact vectors;
the native-16-bit variant clears their xyz components and preserves each w.
Both clear `cr` and preserve `lra_ratio`. With that flag, both retain the cache.
These stages preserve unrelated record bytes and reject missing consumed inputs.
Water classification from supplied samples and guide input-position collisions
from supplied collider snapshots are covered below. Actual texture/resource
acquisition, later collider queries and full CPU dispatch remain caller work.
Animation preparation invokes fixed-state preparation internally; do not clear
particle flags first. Clock, guide, force and prediction composition and static
attachment/reference/fixed-state branches are covered by synthetic tests. These
references do not establish bit-exact GPU execution or change the interactive preview.

`pac_cloth_collisions.apply_cloth_input_collisions` implements the guide-only
input-position pass from the same packed and native-16-bit base shaders. It runs
after guide animation preparation and **before** early-return/fixed/dynamic
integration selection. Static particles bypass it. Both global uint32 at 1200
and frame flags2 `0x20000` must enable it. The pass changes only `_ix` and flags;
working/predicted positions, velocity and contact normals remain unchanged.

The caller supplies actual reference, extra-collidable, scene-object, collider
definition and collider-result snapshots. Each reference uint packs extra-group
start/count in low/high 16 bits; `FFFFFFFF` and zero-count entries are skipped.
The three active-mask words at simulation bytes 64..75 cover 96 colliders. Their
counter includes skipped groups and restarts for each reference. Different
scene owners, indices above 95, scene `0x40000` or flags2 `0x400000` bypass this
mask. A group's matching collider source is normally excluded; group bit `0x4`
reenables it only for the same scene and matching non-sentinel PAC ID. Selected
resource indices at least 65000 resolve to buffer zero, while identity checks
retain the original indices. Missing consumed snapshots are rejected.

Projection additionally requires group bit `0x2`, the collider scene's parent
equal to the current packed scene ID, frame `0x20000000`, scene `0x200` and
bone-velocity w strictly above -20. Parameter bit `0x10` blocks projection
unless bone speed is strictly above 4. The shape definition must have type 3.
Current collider centers define an oriented axis; previous centers are unused.
Frame translation, both scene translations and signed X/Z tile differences
(1000 units per tile) place the animation anchor in that collider's space.
Corrections feed into the next collider in reference/group/element order.
A zero axis has no supported finite shader result and is rejected.

Global uint32 at 1204 selects the PAC custom mode/thickness at parameter bytes
196/200; disabling it selects mode zero and thickness zero. Modes 0..23 change
the plane thickness, effective radius and flag policy, not spring stiffness.
The decoded comparisons use float32 constants. Key differences include:

- Modes 0/1 add 0.03 thickness for groups larger than two; modes 6/7 use -0.05
  for those groups. Signed unknown modes below two also use the additive rule.
- Modes 7..13 and 16 include group-size or movement-dependent thickness rules.
  Their movement condition is speed above 4 or **frame ground height** below -10,
  distinct from the bone-velocity-w gate. Mode 13 with one collider scales its
  radius by 0.7 and selects thickness 0.08.
- Modes 17/18 promote radii strictly below 0.2 to 0.3. Modes 19 and multi-collider
  mode 20 project without setting the contact bit. Modes 21..23 require strict
  radial inclusion to project; other accepted modes can project outside the radius.
- Modes 0/2 and modes above 5 require one collider or effective radius below 0.4.
  Modes 1/3 instead accept the first collider or radius below 0.4. Mode 5 also
  requires particle LRA ratio strictly above 0.1. Mode 4 has no such count/radius gate.

Contact uses strict radial inclusion and sets particle `0x1000000`. Before the
loop, that bit is cleared when scene `0x200` differs from the presence of scene
`0xC00`, when scene `0x10000` is set, or when speed exceeds 4. After the loop its
value is ORed into particle `0x40000000`, preserving an existing companion bit.
This bookkeeping also runs with zero references. Tests cover all 24 modes,
thresholds, mask/owner selection, ordered projections, source immutability and
composition with fixed integration. Later collision/constraint passes, live
resource production and native preview integration remain separate work.

The same module's `update_guide_cloth_collider_result` and
`update_static_cloth_collider_result` reproduce the selected-record geometry
and history writes from `ComputePbdUpdateBoneCollidables` (captured PASC SHA-256
`ddbce0a97004bc8fff0e6ad264e7eeac9b6680ced03b8965dfa5f82f095ad824`).
They emit the complete 56-byte result consumed by the contact helpers below.
The caller must first resolve dispatch, visibility, counts, buffers and mappings;
these functions do not infer runtime activation or substitute missing resources.

- Guide colliders use definition104's local matrix, radius and height. The
  explicitly selected mapped branch scales animation basis rows by the original
  bone's character-space scale, then combines them with the character world
  basis. Animation translation participates; character world translation does
  not. The unmapped branch uses only the world basis. Definition local centers
  76/88 are not used here. Missing selected bone data fails.
- Local matrix row0 supplies the axis, row2 the radial vector, and row3 the
  center. Scale/shear can extend both endpoints while the radius loses its
  component parallel to the axis. Definition flag `0x2` first multiplies radius
  by scene half84. Consumed zero-normalization cases are rejected; no sphere
  fallback or cosine clamp is invented for this producer.
- Guide previous endpoints come from the old **current** fields. Old radius
  strictly below float32(0.0001), scene `0x2`, or different scene bits `0x40` and
  `0x80` resets history to the new endpoints **before** later adjustments.
  Group `0x2` can enable endpoint shifting/enlargement via scene `0x8000`, or
  scene `0x4` plus the global large-shield switch for type3. These consume the
  group count, global float1172 and optional PAC custom scene half98, including
  the decoded sentinel/radius branches. They change only current endpoints.
  Radius becomes zero when group bits `0x3` and scene bit `0x4` are all clear.
- Static-list colliders transform authored centers76/88 and retain the authored
  radius without scaling. Frame `0x200000` with an original index other than
  `0xFFFF` selects the attached object's basis and its translation relative to
  the host, including signed 1000-unit X/Z tile differences. Otherwise only the
  host basis participates. Frame `0x2` or the same old-radius threshold resets
  history; the old result's owner uint is preserved.

`tests/test_pac_cloth_collider_update.py` checks analytic transforms, shear,
activation/history branches, custom endpoint shifts, signed tile coordinates
and a generated-record handoff through moving capsule contact. These are finite
reference calculations, not GPU rounding, native preview or game parity proof.
Authoring collider definitions, resolving bone/LOD resources and connecting the
native preview remain separate work.

The same module also decodes shape and contact math from
`ComputePbdProcessConstraints`. These helpers operate on explicitly selected
positions and collider records, after the caller resolves iteration, movement
and resource choices:

- `cloth_collider_proximity_distance` returns signed distance for type 1 spheres,
  type 3 flat-capped cylinders and type 5 capsules. Its prepass uses the collider
  **definition** radius. Unknown types return the shader's literal 1000 sentinel.
  The capsule distance formula has no collapsed-axis fallback.
- `cloth_collider_contact_surface` returns the later response's surface point
  and normal from the selected reference position. The caller supplies the
  animated-result or static-definition radius as appropriate. Thickness expands
  sphere/capsule radius; cylinders also extend both axial endpoints. A capsule
  axis strictly shorter than float32(0.000001) uses the first endpoint as a
  sphere center. This fallback belongs to the surface query, not the proximity test.
- `resolve_cloth_moving_contact` projects the selected target only when its
  signed distance to that response plane is negative. Its explicitly selected
  tangent-damping branch removes `float32(0.45)` times the tangent motion,
  scaled by `min(penetration / abs(normal_motion), 1)`. Relative motion subtracts
  the supplied collider displacement. Zero normal motion with positive penetration
  selects scale 1, matching the shader's division followed by minimum.
- `project_static_cloth_collider` consumes one 104-byte definition and 16-byte
  attached-static group record, plus the selected scene/frame/tile translation.
  Definition float3s at 76/88 supply centers. Type 4 instead interprets the second
  vector as a plane normal, uses it without normalization and bypasses friction.
  Other unhandled shape types use a zero surface/normal and produce no contact.

Cylinder response chooses the side or cap according to their signed distances;
ties choose the cap. Near the edge, a band of half the smaller expanded radius
or half-height blends the radial and cap normals. This changes the normal while
retaining the chosen surface point, which is not always the Euclidean closest
point. An unused singular radial normal does not invalidate a finite cap branch;
consumed zero normalization and collapsed cylinder axes are rejected.

Attached-static friction reads the group's static/kinetic halves at 4/6. It uses
the original target-minus-reference motion and subtracts friction from the
projected point, with tangential length strictly above float32(0.000001).
A coefficient must exceed float32(0.001) to be
active. Static friction cancels the tangent when its length is at most the static
coefficient times penetration. Otherwise kinetic friction reduces it by at most
the kinetic coefficient times penetration, capped by the active static coefficient
and by the remaining tangent length. These rules are separate from the moving
collider's optional 0.45 correction.

`apply_attached_static_cloth_collisions` connects that single-collider projection
to the attached-static list in **both** the guide and static-mesh constraint
branches. The caller supplies positions after preceding animated contacts, the
already-selected reference position and the incoming contact aggregate. Outer
constraint/collision eligibility remains the caller's responsibility.

- Simulation ushort 214 is a complete-list `0xFFFF` sentinel; otherwise its low
  11 bits are the absolute reference start and high 5 bits are the reference count.
  Each reference uint is one complete group index, with `0xFFFFFFFF` skipped.
  Indices increment without wrapping back into the 11-bit field. References are
  not packed extra-group ranges, and repeated group indices are not deduplicated.
- The 64-byte host instance comes from scene uint 48 plus **one if
  `SceneConstantBuffer._frameNumber.y` (uint at byte 36) is nonzero**, with uint32
  addition. The resulting resource index selects buffer 0 when >=65000. This is
  not an even/odd test. Simulation uint 88 selects the element. A present list
  requires this host record even when its decoded count is zero.
- Host byte 12 packs signed tile Z in low16 and X in high16. Host float3 48 plus
  frame float3 0 plus `(tileX*1000, 0, tileZ*1000)` places particles in collider
  space. This loop consumes neither the host matrix basis nor the scene object's
  own translation/tile fields.
- Group ushort 2 is the collider count; uints 8/12 supply the definition SRV and
  element start. Resource indices >=65000 select buffer 0; element addition wraps
  uint32. Group bit flags do not gate this loop, and the guide input pass's
  96-collider mask does not apply here. Empty groups skip definition access.
- Guide particles (`simulation ushort 216 == 0xFFFF`) use float 204 as thickness;
  static meshes use fixed `float32(0.01)`. Target corrections feed forward in
  reference/group/element order while the reference position stays fixed. Contact
  is ORed with the incoming aggregate, including a contact with no position change.
  The function does not write normals, particle flags or caches.

`select_guide_cloth_collision_candidates` decodes animated collider eligibility
and cache selection for the guide constraint branch. It requires the **original**
152-byte particle snapshot plus the current working flags after preceding
constraints/prepasses. Outer constraint/collision gates must already have passed.
The returned definition/result/scene addresses allow subsequent geometry work;
this selector does not load result or scene records or project particle positions.

- Scene ushort 72 is the reference start, with `0xFFFF` disabling this guide
  collision branch, including its later attached-static contacts. Original
  particle bits `0x3C00` also disable it unless frame bit `0x20000` is set.
- Cache access requires frame bit `0x10` and simulation ushort 226 other than
  `0xFFFF`. That ushort selects the uint buffer, with values >=65000 selecting
  buffer 0. The caller supplies the ten-uint window at simulation uint 148 plus
  `particle_index*10`. Word 5 holds the animated candidate count; words 6..9 hold
  four tokens. This is separate from the first five words used by other stages.
- Original particle bit `0x20000000` permits reuse only when the loaded count
  is below 5. A zero count is a valid empty cache. A count of 5 or more selects
  a full search without rebuilding while that original valid bit remains set.
  With cache access enabled and the original valid bit clear, a full scan rebuilds.
- Each token is `reference_ordinal + 1000*group_ordinal +
  1000000*collider_ordinal`, with uint32 arithmetic. These are ordinals within
  the nested reference/group/collider lists, not absolute resource addresses.
  The consumer decodes by division/remainder and bounds-checks each list level.
  A consumed `0xFFFFFFFF` token resolves to three zero ordinals in both captured
  shader variants; it is not skipped. Decimal carry and uint32 wrap are retained.
- Full scans apply the 96-collider active mask to matching raw scene identities;
  its index resets per reference and advances across excluded groups. Different
  scenes, scene bit `0x40000`, frame flags2 bit `0x400000`, and indices above 95
  bypass that mask. Cached selection bypasses it entirely but rechecks the
  group/source/PAC and definition eligibility below. Stale out-of-range cached
  entries are skipped without forcing another full search.

Matching definition source normally excludes a group; group bit `0x4` permits
consideration only for a matching non-sentinel PAC ID in the same raw scene.
Definition uint 100 bit `0x1` then requires that PAC match; with this bit clear,
the definition must come from a different raw source. Buffer-0 substitution does
not make different raw owners equal. Groups without bit `0x1` are excluded by
working particle bits `0x30000` or scene bit `0x1`. Groups with bit `0x1` in the
same scene are excluded when frame bit `0x20` and scene bit `0x200` are both set.
Group bit `0x2` is additionally excluded for particle half 88 below float32(0.3)
when frame bit `0x20000000` is set and scene bit `0x200` is clear.

`update_guide_cloth_collision_cache` consumes all eligible response-plane queries
in their evaluation order. The supplied distance is measured before correction
against the selected animated response plane. Distances strictly below
`float32(0.03)` qualify, including positive distances that produced no contact.
It stores the first four tokens while counting **all** qualifying queries,
writes word 5 and ORs `0x20000000` into the current working flags. Rebuilding an
empty list still marks the cache valid. Other words and unused token slots are
preserved. Modes other than rebuilding leave the cache and working flags intact.
The existing base finalizer resets this cache half and clears its valid bit
when frame bit `0x10` requests that earlier reset.

`select_cloth_collider_blends` resolves the constraint shader's timing from
per-frame parameters, the 1216-byte PBD globals and the 44-byte push constants.
It returns `None` for the decoded frame/clock/substep skips. Frame flags2 bit
`0x8000` selects the scaled clock at global byte 896 instead of 864. Fixed-step
blends are `substep/count` and `(substep+1)/count`; variable mode (`flags2 & 0x800`)
uses 0/1 and only substep 0. These differ from base animation's interval timing.
Global uint 1124 must equal **1** to subdivide that interval by solver iteration.
The local limit is `min(flags2 & 7, push_uint4)`; global uint 1148 enables the
unsigned adjustment `push_uint0 + local_limit - push_uint4`. The previous
iteration is one less than that result. The helper preserves the shader's uint
and float32 conversions; a zero divisor is rejected. Frame bit `0x2` selects
current-time sampling, otherwise previous-time sampling is used.

`sample_cloth_collider_motion` consumes a 56-byte animated result with
previous/current endpoint pairs at 8/20 and 32/44. After interpolation and space
translation, it projects the reference onto the axis averaged between sampled
and current endpoints. Its axial coordinate is **not clamped** to the segment.
Movement is `(currentA - sampleA) + u*((currentB - currentA) - (sampleB - sampleA))`;
adding this to the reference gives the position used for the current-time surface
query. This captures endpoint-dependent movement rather than just translating by
the first endpoint. A collapsed averaged axis has no supported finite result.

`apply_guide_cloth_animated_collisions` composes timing, candidate selection,
endpoint movement, surface response, flags and cache recording. It starts after
the caller's outer collision gates and preceding constraints/prepasses, and ends
at the entry to the attached-static loop. It requires the original particle and
current working position/flags separately, plus actual scene/result snapshots.

- The reference is the working position when frame bit `0x20` and scene bit
  `0x200` are both set; otherwise it is original particle float3 36. Surfaces use
  the advected reference, current interpolated centers and **result** radius 4.
- Groups with flag `0x1` use simulation float 204 as thickness; other groups use
  `float32(0.01)`. Group flag `0x2` adds simulation half 286. The optional 0.45
  tangent correction is enabled by the working-reference condition, or by
  frame `0x20000000` with scene `0x4000` for a group without flag `0x1`.
- Separate histories are used for scene `0x4000` with flags2 `0x80`, or the
  flypapering branch: global uint 1140 nonzero, parameter flag `0x8`, frame
  `0x20000000`, original particle `0x04000000`, and scene `0x4000` clear.
  `bit1_position` means group flag `0x1` set; `bit0_position` means it is clear.
  Each matching history receives its own ordered projections. The general
  position retains the most recent corrected target; later blending is separate.
- Contact normals accumulate without normalization. Flypapering excludes normals
  from groups without flag `0x1`. `last_radius` and `last_bit1_radius` retain the
  most recent matching contact radius, not maxima. Flag `0x8000` is cleared on
  entry and then follows the most recent contacting group's flag `0x1`.
  Contact with both group categories sets `0x10000`; frame `0x20000000` or no
  contact with the flag-clear category subsequently clears `0x30000`.
- Unhandled animated types, including type 4, return a zero response plane and
  no contact, but their zero-distance query still qualifies for cache recording.
  Type 4's plane projection belongs to the attached-static path instead.

`apply_static_cloth_animated_collisions` covers the corresponding direct-list
branch for simulation ushort 216 other than `0xFFFF`. Definition/result starts
are **uints 160/164**, resources are ushorts 232/234, and count is ushort 242.
Resource values at least 65000, including `0xFFFF`, resolve to buffer 0; element
addition wraps uint32. The raw definition source is skipped when it matches
ushort 238/uint 180. The 96-bit mask always applies to indices 0..95, with none
of the guide branch's scene/flags2 bypasses. Later indices bypass the mask.
Definition ownership flags, guide groups and the animated cache are not used.

- Original particle flags `0x3C00` suppress the animated list unless frame bit
  `0x20000` is set. This still allows attached-static contacts, unlike the guide
  branch's disabled state, which bypasses both lists.
- Endpoint motion uses the same timing and reference rule as guide cloth, but
  space translation is **only per-frame float3 0**. Scene origins and tiles do
  not participate. Result radius 4 and fixed `float32(0.01)` thickness feed the
  surface query; authored thickness 204 and half 286 are unused. Contacts use
  plain projection without the optional 0.45 tangent correction.
- Normals accumulate and the last contacting radius is retained. Contacts do
  not set guide contact flags. Entry clears `0x8000`; on the **penultimate local
  iteration**, it clears `0x308300` instead. This uses the same adjusted iteration
  and local limit as timing, even when blend subdivision is disabled. Both
  category histories remain the initial working position.

`apply_cloth_bone_collisions` connects the outer gate, selected animated branch,
attached-static loop and subsequent history blend. It returns `None` for a
frame/clock/substep skip. Otherwise, frame `0x100` must be set and the original
particle's `0x40` clear. Push uint 12 must be zero, unless frame float 24 is
**at most -10**. Bypassing the collision stage returns `active=False`, unchanged
position/cache and working flags with only `0x8000` cleared. Active results
retain the contact metadata needed by later passes. Actual resource records
and SceneConstantBuffer uint 36 (`frame_number_y`) remain explicit caller inputs.

After attached-static contacts, flypapering replaces the general position with
`bit1_position + weight*(bit0_position-bit1_position)`. The weight is 0.5 when
original particle half 88 is strictly greater than `float32(0.3)`, otherwise
`float32(0.1)`. Scene `0x4000` with flags2 `0x80` instead uses 0.5, independently
of that half value. These conditions also apply to the static-mesh branch.
This order can replace an attached-static correction while preserving contact,
normals, radii, flags and cache state. It must not be followed by an invented
second attached-static projection.

Focused tests use analytic signed distances, finite-difference gradients,
rotation/translation equivalence, cylinder edge/tie cases, capsule degeneracy,
raw plane normals, ordered buffer selection, contact/friction composition,
cache reuse/overflow, base-reset-to-rebuild transitions, moving guide contacts and
the shared static/guide collision stage through the final history blend. They
do not establish GPU rounding or gameplay parity. Layer/world contacts, final
state writes and native preview wiring remain to be connected; this is not the
complete cloth solver.

`pac_cloth_runtime.py` traces the CPU material-to-frame update at `0x143CE26F0`.
`update_cloth_frame_stiffness` converts raw authored coefficients before writing
the existing frame record; they are not direct shader stiffness values. For a
positive input, the rule is `min(1 - powf(1 - bounded_input, scale / denominator),
limit)`. Mode 1 (cloth) bounds stretch/bend inputs at float32(0.4); other byte
modes use float32(0.99). Area and restore angle use an input bound of 1.

| Authored coefficient | CPU material offset | Frame half offset | Nonpositive input |
| --- | --- | --- | --- |
| StretchingStiffness | `0x08` | 66 | 0 |
| BendingStiffness | `0x0C` | 68 | -1 |
| AreaStiffness | `0x14` | 70 | 0 |
| RestoreAngleStiffness | `0x10` | 72 | -1 |
| UnderWaterRestoreAngleStiffness | `0x84` | 94 | Negative uses raw ordinary restore; zero produces -1 |

Runtime globals supply the denominator, four scale factors, four output limits
and a separate bend switch that selects denominator 1. Decoded initialization
values are denominator 4, scales `(5, 1, 1, 1)`, limits `(0.6, 0.06, 0.6, 0.06)`
in stretch/bend/area/restore order, and the bend switch enabled. These are not
captured live settings and the reference requires callers to supply them.
Underwater restore shares ordinary restore globals. Material `MaxStiffness`
occupies a separate field at `0x104`; this traced conversion uses the runtime
limits above. It does not establish that the material field is unused elsewhere.

Half updates compare the old decoded value to the new float32 result using
inclusive `+/- FLT_EPSILON`, **before** the decoded CPU half packer. A write can
invalidate an upload even when the packed bytes stay identical. The reference
returns that invalidation and the written offsets, preserving all other fields.
Its Python power calculation does not claim bit-exact CRT `powf` results.

`update_cloth_iteration_bits` uses an already-selected signed-byte simulation LOD.
A negative material `OverIterationSkipLod` selects the global threshold. At or
above that threshold, the selected limit is 2; otherwise it is the smaller of
the material count's low uint16 and the global uint16 count. Only the low three
bits are written into frame flags2, preserving the other flags. Invalidation
compares the full selected count before masking. The CPU XML parser rounds odd
`SolverIterationCount` values upward before this update; the function takes that
already-parsed value. This stage does not establish the complete dispatch loop.

The dynamic-fix mask has a different source: `0x143CE1F00` copies live owner
`+0x158` to simulation parameter `+168`. PAC guide membership and a material
name alone do not determine which groups are active. Upstream controller
assignment, collision/contact generation and preview integration remain
separate work. Synthetic tests connect the new stiffness upload to the
existing stretch projection without claiming visible or in-game parity.

The same module now follows LOD and blend state into the two separate frame
halves: elasticity at 76 and fading at 78. `select_cloth_simulation_lod` applies
eligible material scale and global scale to screen ratio, then checks thresholds
in LOD3/LOD2/LOD1 order. Comparisons are strict; equality continues toward higher
detail. A forced global other than -1 supplies its signed low byte. Earlier
caller branches that force LOD3, LOD0 or skip simulation remain explicit.

`update_cloth_lod_state` operates on a **64-byte slice at owner+0x60..0x9F**,
not a complete controller object. Crossing from below the simulation LOD limit
to at/above it sets fade direction +1; crossing back sets -1. Explicit early
force branches instead clear the direction. Every LOD update clears the
elasticity override at owner+0x68. The returned reactivation, resource+0x103
reset, LOD-change and count+0x1C8 requests describe external side effects for the
caller to apply; this reference does not dereference resources or mutate them.

`advance_cloth_frame_blend` consumes that slice and an already-selected timestep.
The timed elasticity amount contributes only while its timer remains positive
after decrement. A separate timer updates the additive elasticity ratio from
remaining time/duration, optionally inverted; once inactive, it retains the last
ratio. The base elasticity sum clamps to [0,1], then two ordered overrides blend
it toward 1 without another implicit clamp. Ragdoll and scene terms are explicit.

An active fade uses `max(minimum_rate, 1 / reciprocal_denominator)`. Reaching
exactly 0 or 1 retains the direction; only crossing the endpoint clears it.
Direction zero uploads a fading value of **zero**, preserving the stored ratio.
`NeedNaturalWarmUp` (material byte `0x197`) plus the scene warmup request clears
stored/uploaded fading unless the updated direction is +1. Fading and elasticity
are never substituted for each other. Both upload through the same half-value
comparison/packing rules as stiffness, preserving unrelated frame/controller bytes.

Decoded initialization values are global screen scale float32(1.4), ordered
thresholds float32(0.1/0.3/0.6), simulation LOD limit 3, fade reciprocal denominator
5, minimum fade rate 1 and elasticity-transition duration 0.5. These are supplied
explicitly and are not evidence of live scene configuration. The source of the
scene warmup request, timer activation and external elasticity ratio still needs
upstream tracing. Synthetic composition connects LOD reactivation to the uploaded
fade and `select_guide_result_positions`; no visible or gameplay claim follows.

`pac_cloth_environment.py` decodes water volume queries and constructs environmental
acceleration from explicit runtime records and scene samples.
`plan_cloth_water_samples` consumes the 768-byte water constant buffer and a
position already relative to the previous view. Common UVs are
`(0.5 + x * float8, 0.5 - z * float12)`. The detailed top texture is selected only
when `abs(x) < float416 / 2` and `abs(z) < float424 / 2`, using UVs
`(0.5 + x * float424, 0.5 - z * float428)`. The inspected shader reuses float424
for the Z bound and X scale. Coarse top, bottom and both air-pocket samples use
common UVs. Water samplers are bilinear clamp; air-pocket samplers are bilinear
black-border, all at LOD zero. The helper returns unclamped coordinates and does
not acquire textures or execute samplers.

`classify_cloth_water` consumes four samples in selected-top, bottom, air-top,
air-bottom order. Water constants float3 at 32 supply minimum, maximum and bias.
For a sample below 1, height is
`bias + current_view_y - minimum - sample * (maximum - minimum)`; otherwise
height is the absolute sentinel -10000, without a view offset. Negative samples
are not clamped. Against `relative_position.y + current_view_y`, the water top
is exclusive and bottom inclusive; the complete inclusive air-pocket interval
is excluded. The returned membership precedes frame flags2 `0x1000` gating.
The caller retains the guide-before-adjustment versus static-after-adjustment
query order described above. No missing scene samples are invented.

`cloth_environment_acceleration` supplies the base integrator. It uses
velocity **after** gravity and bone inertia. Air resistance remains active when
wind is disabled; frame `0x40000000` additionally includes particle velocity in
the air-relative motion. Parameter half 280 supplies quadratic air resistance.
Flags2 `0x8` enables voxel/frame wind, with parameter half 268 scaling the voxel
sample before its speed-dependent force calculation. Extra-data half 20 is a
direct wind multiplier, defaulting to 1 when absent, not an override sentinel.

Guide frame wind has separate sky-visibility thresholds near 0.1 and 0.8;
static frame wind does not use those thresholds. The global sky-on-voxel switch
controls voxel attenuation independently. Flags2 `0x10` additionally removes
inward horizontal wind near the model center and attenuates the remaining wind
using the decoded radius and smooth transition. This mask does not also mask
the separately computed air-resistance term.

Underwater relative motion combines bone/particle velocity, half the scene water
velocity and eligible shallow-water flow. A squared-speed dead zone precedes
turbulence. Parameter halves 290/292 supply linear viscosity and quadratic drag;
the special speed cap affects the quadratic term only. Both air and water forces
then receive the global acceleration cap, surface response and horizontal wave.
Orientation uses particle `_p[1]` and neighbor u16s at 112/114, not the adjusted
working position. Frame `0x80000` selects the first-edge response unless extra
flag `0x4` disables it; otherwise two valid neighbors define a triangle normal.
Missing neighbors and degenerate edges retain their distinct shader branches.

The reference requires voxel, sky, shallow-water and scalar noise samples only
when their branches consume them. It does not generate the procedural noise,
sample scene textures or determine live force eligibility. Zero dry-turbulence
normalization and purely vertical nonzero forces make the inspected math
non-finite and are explicitly unsupported, without inventing recovery behavior.
Tests cover the decoded branches and compose the result with base integration,
prediction and final movement; they do not prove GPU or game equivalence.

`pac_cloth_movement.py` implements the decoded core of the normal final-movement
pass, confirmed against both packed and native-16-bit variants of
`ComputePbdProcessFinalMovement`. `cloth_attachment_correction` uses the selected
solver output (`_p[iterationCount & 1]`) for the current particle, but always
uses `_p[0]` for anchors. A candidate must currently have zero inverse mass or
particle bit `0x40`; initial group membership alone does not activate it. The
allowed radius is the uploaded rest distance times bone scale, optionally
expanded to the animated distance by frame bit `0x800000`, then multiplied by
stretching scale and `float32(1.1)`. Corrections share the original input point
and average only violated radii. Frame bit `0x80` enables this pass, while
current-particle bit `0x40` bypasses it.

`guide_final_input_blend` selects particle half 94 or its nonnegative extra-data
half-6 override and applies per-frame half 44 (`stiffnessScale`). This final
pass discards the scaled blend unless it exceeds `float32(0.999)`; smaller
weights can still affect other solver stages. The global switch, scene/frame
gate, underwater fifth power, particle-state overrides and pinch-timer recovery
remain explicit. These weights are not a generic jiggle-strength slider.

`finalize_cloth_motion` applies attachment correction before the final animation
blend. Frame flags2 bit `0x40` also shifts `currentPosForVelocity` by that
correction, excluding its direct contribution from the next velocity. Velocity
uses the selected substep clock (`0x800` selects variable rather than fixed)
times scene half 94 (`timeScale`), floored by the minimum velocity delta time.
The caller supplies the appropriate global clock family (`0x8000` selects
scaled clocks). Per-frame half 54 limits speed, with particle bit 4 reducing
that limit to one tenth. Velocity suppression precedes ground response:
particle bit 2 applies parameter half 254 (`groundFriction`) to horizontal
motion relative to per-frame half3 at 56 (`modifiedPbdBoneVelocity`), clears Y,
and can apply the half-46 backward speed along scene half3 at 86. Consequently,
the final velocity is not universally bounded by the earlier speed cap.

The normal pass writes the final position to `_p[1]` and `_x`, preserving old
`_x` as the next `_p[0]` history except for its decoded frame-state override.
These references return mathematical values without mutating their input
records. They exclude reset/hold paths, visibility/dispatch selection, contact
bookkeeping, NaN recovery and GPU rounding; they are not a complete solver and
are not wired into the preview. Tests compose authored anchor preparation,
stretch correction, final movement and render-position interpolation on owned
geometry; they do not establish game or rendered parity.

`pac_cloth_frames.py` provides a mathematical reference for the guide branch of
`ComputePbdUpdateResult`, using explicitly supplied runtime inputs. Particle
offset 0 is the animation target `_ix`; offset 36 is the simulated position `_x`.
`select_guide_result_positions` interpolates `_p[0]` at offset 12 toward `_x`
unless per-frame flags2 bit `0x800` bypasses interpolation, then blends toward
`_ix`. The interpolation ratio is remaining/fixed simulation delta time from the
appropriate clock (`0x8000` selects the scaled clock). The second blend is
`_fadingRatio`, identified by native 16-bit reflection at offset 78 (the high
half of packed `_p6`). `pac_cloth_runtime.advance_cloth_frame_blend` implements
its CPU producer from explicit controller and scene inputs; it is not
offset 96's packed smoothing field.

`update_guide_result_frames` preserves the entire frame when per-frame bit
`0x10000` suppresses this update. Otherwise it updates translation and runtime
blend metadata; bit `0x4000` additionally enables rotation correction. Bit
`0x80000` selects single-edge rotation, with the second neighbor preferred and
fallback to the first only when the second index is out of range. This branch
compares the animated edge with the selected current position minus the
neighbor's raw `_x`. Edges no longer than 0.01 use identity; nearly opposite
directions use negative identity as in the shader.

With `0x80000` clear, two neighbors define input/output frames. Their simulation
edges use raw `_x` at both ends. Output directions blend animation and simulation
by `saturate(simulatedLength / (0.8 * animatedLength))`, reducing the rotation
when edges compress. The correction maps the animated frame toward the simulated
frame, not the reverse. Frame bases transform through world, correction and
inverse-world bases. Translation is `(selectedPosition + pbdSpaceOffset)` times
the inverse-world basis, without an inverse translation row. The fourth column
remains metadata, with row0.w supplied by `guide_runtime_blend_factor` below.

Known out-of-range orientation indices use the shader's defined branches;
`None` from preparation means untouched/unknown memory and is rejected when
rotation consumes it. Zero/collinear edges that make the two-edge math singular
are reported unsupported, without inventing an identity result. These functions
do not discover active flags, solve particle motion, emulate dispatch/resource
selection or claim bit-exact GPU arithmetic. They are not wired into the preview.

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
and supplied runtime matrices, which may be produced by the result-frame
reference above. It does not emulate missing GPU resources or bit-exact
float/half arithmetic.

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
