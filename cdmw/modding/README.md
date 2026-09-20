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

The reader also retains the two per-guide byte arrays, ordered index groups,
layout-7 group tags, complete 10-byte constraint records, per-vertex constraint
spans and edge indices. No unknown or apparently unused bytes are discarded.
`inspect_guide_topology` reports whether these tables match the guide's edges,
adjacent triangles and per-vertex references. The observed record classification
uses the low byte of the final word; its high byte varies in stock files and is
retained separately in the evidence summary and intact in the raw records.

Alpha bits matching channel B's value 255 is a structural observation, not proof
of runtime pinning. Group starts do not always match those alpha bits. Reports
show these comparisons explicitly; no pin, mass or stiffness controls are
inferred from them. This reader does not replace the approximate simulation preview.
Unsupported layouts, mismatched descriptor counts, out-of-range triangles and
truncated metadata report unavailable without reading into geometry sections.

Inspect loose decoded files with:

```powershell
.\.venv\Scripts\python.exe tools\pac_cloth_guide_study.py 'C:\path\model.pac'
```

The command reads its inputs and prints JSON with source hashes, decoded guide
geometry, complete stored tables, topology comparisons and field offsets. It
returns a nonzero status if any input is unavailable. Keep reports and game-derived
data outside the repository.

Related tests: mesh, static replacement, material, and package entries under `tests/`.
