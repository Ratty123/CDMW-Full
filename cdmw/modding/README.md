# Modding

Owns mesh and material replacement logic, scene import, source-part mapping,
runtime static mesh building, PAC/PAM/PAMLOD builders, material profiles, and
material payload routing.

Keep PySide UI and archive mutation confirmation outside this package. UI
packages collect user intent; services coordinate execution; archive patching
and backup policy stay behind archive services/core paths.

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

The decoder reads all six packed influences. It also reads two additional
indices from half-float fields at bytes 12–15, with weights at bytes 34–35, when
the low six bits of byte 39 are not 63. These extra lanes can bring a vertex to
eight influences; invalid or disabled entries are excluded.

The writer authors only the six packed palette lanes and preserves the extra
lanes. `pack_pac_skin_weights` keeps the six strongest inputs and quantizes
their weights to sum to 255. Callers that require lossless influence coverage
must reject wider rows before calling it. Do not reinterpret packed slots as
four u8 indices or reduce named-bone inspection to the primary influence.

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

Related tests: mesh, static replacement, material, and package entries under `tests/`.
