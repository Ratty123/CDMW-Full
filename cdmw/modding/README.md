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

Inside the 40-byte PAC vertex record, four influence slots sit at byte 20 and
their four u8 weights at byte 28 (`PAC_SKIN_*` in `mesh_parser.py`). `0xFF`
marks an unused slot, so slot values are capped at 254.

Slots are **not skeleton bone indices**. Each `.pac` carries its own bone
palette — a u16 count then that many u32 `.pab` bone-name hashes near the start
of the file. `pac_bone_palette_candidates` returns every table matching that
shape and `resolve_pac_bone_palette` picks the one that fully resolves against a
given skeleton, so a mismatched rig yields nothing rather than wrong names.

Only the **primary** influence (byte 20) decodes. Weights are sorted descending,
so it is the heaviest, and it resolves correctly through the palette. Bytes
21-23 are a packed field rather than plain slots — byte 21 is always a multiple
of 4 with 64 distinct values, byte 23 caps at 12 — and decoding them as slots
produces impossible blends. Anything needing named bones must use the primary
influence; the raw bytes still round-trip verbatim for replacement.

Races share rigs: the "other" races ship no `.pab` and skin against
`phm_01.pab` / `phw_01.pab` / `ptm_01.pab`, so pick a skeleton by which palette
resolves, not by name.

Reader (`mesh_parser.py`) and writer (`mesh_skinning.py`) must move together;
they previously agreed on the wrong offsets (28/32), which decoded 72% of every
vanilla body as unweighted and capped authored bones at index 3.
`tests/test_pac_skin_layout_regression.py` pins this against real bodies and
skips when they are absent.

Related docs: `docs/architecture.md`, `docs/project-map.md`.
Related tests: mesh, static replacement, material, and package entries in
`docs/test-matrix.md`.
