# Hair creation in the existing Mesh Editor

Updated on 2026-09-20. Experimental hair authoring uses one
setup dialog for Kliff, Damiane and Oongka. Hairstyles have not been tested in game
and may not work correctly. Local package creation is read-only against installed
archives. Desktop interaction and in-game acceptance are separate from source and
offscreen proof.

## Setup and supported sources

Hair Tools and Finder Create/Edit Hair open the same Character and Action choices.
Create opens an empty scalp; a sequential compatibility check finds the first
usable registered skin/material base without preparing thumbnails. Optional
procedural fills remain in the editor. Edit uses registered thumbnails. Start is
disabled until the catalogue and donor checks finish.

Barber catalogues can include registered PACs without `_player` in their filename.
These use the same prefab, material, LOD and original-skin validation as player
variants. Repeated prefab IDs appear once in the chooser using their first slot,
while export appends a new choice without changing any existing slot or unrelated
customization setting. It clones the first matching slot's metadata and icon.

Edit filters by hairstyle number or asset name before requesting details, shows
24 choices per page and allows at most four detail lookups at a time. A requested
Finder hairstyle opens on its page. Active mounted DDS icons are resolved by
their exact registration paths and decoded off-thread in bounded page batches;
shadowed or ambiguous icon sources are not selected. Missing/corrupt icons use
the existing rendered thumbnails, and selecting a hairstyle retains the full 3D
preview. Page/filter changes cancel icon and compatibility work and reject late
results. Failed compatibility checks retain their explanation when reselected.

The character's mounted appearance and customization documents own fitting roles,
scales and registration. Oongka uses `5_pom` head/body references and `1_phm` hair;
a shared hair prefix cannot identify the character. HeadScale is applied around
the authored head joint, including its weighted body descendants. CharacterScale
is the shared parent transform and cancels in donor authoring coordinates. Facial
details use the same head transform. The clean fitting mannequin uses the head's
fitted eye-cover surfaces as smooth eyes, omitting the separate shader-dependent
iris/lens geometry, lashes, brows and hidden mouth detail. Heads without fitted
eye covers retain their separate eye reference. Face and
body crown/back geometry are partitioned to avoid an overlapping face shell.
The resulting scalp and neck/shoulder
references stay outside output geometry.

The mounted catalogue re-audited on 2026-09-20 contained:

| Character | Registered | Compatible | Unavailable registration |
|---|---:|---:|---|
| Kliff | 7 | 6 | `cd_phm_00_hair_00_0512_player` uses two PACs |
| Damiane | 5 | 4 | `cd_phw_00_hair_00_0507_player` uses two PACs |
| Oongka | 5 | 4 | `cd_phm_00_hair_00_0003_player` uses two different PACs |

Eligibility checks the actual mounted prefab's single PAC reference, material
closure, LOD0, supported 40-byte skin layout and valid influence rows. Multi-mesh
registrations, aliases, additional LODs and incomplete dependencies are gated in
the chooser with a reason; successful loading of a similarly named PAC is
insufficient. Oongka's first compatible base is registered choice 2, `0016_player`.

The supplied Barber Unlocked archive was inspected separately: its Kliff,
Damiane and Oongka selectors have 182/77/175 slots referencing 171/75/171 distinct
hair IDs. Its XML append operations and 24 supplied DDS icon decodes passed local
checks. These counts do not establish compatible donor counts: the ZIP contains
no PAC meshes, rigs or physics. The mod's colour palettes remain owned by the
mounted game/mod; no global palette or existing colour indices are replaced by
hair package export. Beard entries are reference data, not beard-authoring support.

Only Start prepares the replacement editor. Preparation owns a cancellation token,
rejects stale catalogue/character/selection results and retains the current scene
until a complete isolated replacement is ready. Failures clear progress and allow
Retry. Different targets, characters and edit modes use the existing unsaved-work
confirmation. A preset change on the active generated target publishes one undoable
edit without reopening the archive. Reference geometry uses the existing bounded
cache (four entries, 128 MiB); geometry-only reference loads avoid full editable
sessions, roundtrip validation and material/DDS preparation. A conservative
per-vertex budget avoids recursively visiting every scalar for cache sizing.
Identity includes source generation, authored
descriptors and transformed geometry. Alternative reference pickers apply role and
character eligibility before pagination.

## Grooming, skinning and motion

Hair Tools is labelled Experimental at entry, setup and in the editor. Its visible
notice states that hairstyles have not been tested in game and may not work correctly.

Rust owns guide/card generation, pointer dispatch, visible buffers and simulation.
Qt owns setup and lifecycle. Python owns archive/material loading, host validation,
atomic history, drafts and temporary packages. Actual loader-resolved DDS, tint,
alpha and sidedness are retained; neutral shaded fitting geometry is separate.

Select, Ctrl-select, marquee and the toolbar's Clear Selection/Select All/Invert
change only hair-lock selection. Repeated host state notifications preserve the
acknowledged generated preview instead of exposing retained template geometry.
Move and Lengthen acquire
a clicked lock while preserving an existing selected group. Move follows the grabbed
position with a smooth, distance-based falloff; **Move reach** controls how much of
the lock follows. It evaluates the original shape against the complete drag, so
mouse event frequency does not amplify the edit. Lengthen changes tips
and fixes roots. Comb, Smooth, Curl and Clump respect brush influence and selection.
Draw supports Freehand, Straight, Arc and Circle strokes, visible cards during
dragging and explicit mirror pairs. Straight and Arc use the dragged endpoints;
Arc has a signed Bend control. Circle uses the drag as its diameter. Freehand's
Stroke smoothing filters spatial jitter while preserving the root and current tip,
without a trailing pointer delay. **Follow scalp** starts enabled for Freehand;
shape templates start in the view plane. The checkbox and temporary Ctrl override
control surface following independently of collision, which stays active. With
surface following enabled, each pointer sample projects onto the curved scalp.
Freehand continues from its last tip in the camera plane beyond the outline or
while Ctrl is held. Draw resolves contacts along the view ray to preserve the
stroke silhouette, with gentle outward smoothing across small depth creases.
Triangle-normal clearance must not reverse adjacent guide samples. Sampled
guide segments and generated card width keep contacts active in both modes.
Long strokes retain their pointer path separately and resample the bounded guide
by distance, preserving root and tip. Extra samples near the root let the stroke
leave the scalp gradually. The initial outward seed is replaced on the first drag.
Cards start narrow and tangent to the scalp, then broaden and roll into the follower
bundle with distance; motion blends from the inward root extent to each row's full
radius so rotating cards remain outside the head without lifting the whole lock by
its widest section. Card taper and texture coordinates
follow physical distance rather than pointer sample count. Saved guides retain
their authored shape; older strokes with a baked-in straight root need redrawing.
Live Draw reuses the prepared scalp index and generates only the active locks.
Idle strokes reuse the current frame; endpoint-based tools coalesce queued moves
within a frame while Freehand retains its path samples.
Cut removes distal geometry; Erase/Delete remove owned geometry.
Width and generated follower density affect selected locks. Empty selections,
rigid sections, unresolved groups and unsupported existing-hair operations report
requirements rather than silently succeeding. Draw and follower generation require
generated hair. Ambiguous existing sections are described as original sections
without grooming guides, without warning colours or automatic highlighting.
Their preparation controls are collapsed until needed and remain available after
all sections are prepared, allowing roots and rigid attachments to be corrected.
Root/group assignment or
a rigid classification is required for motion preview; shaping an unprepared
section explains how to assign its guide.

Export does not require editor guides for unchanged existing geometry. Missing
bindings are accepted only when the immutable PAC donor proves the retained
vertices, normals, UVs, skin records and triangle lineage, using stable part
identity and the draft's authoring coordinate transform. This also permits
untouched sections alongside groomed sections and retained triangles after cuts.
Changed unprepared sections remain blocked. Generated geometry still requires
guide coverage; draft versions and the original skin-weight layout stay unchanged.

Each completed action uses the ordered publication queue and receives the normal
host acknowledgement. Draw can start another stroke while previous Draws prepare
and save; pending locks stay visible, and each completed stroke retains its own
history step. The queue accepts up to 32 pending edits within an estimated 256 MiB
snapshot budget and pauses new input if saving falls too far behind. Pending Draw
previews are cached between pointer updates. Undo and Finish wait for the accepted
strokes to drain. The Mesh Editor
spinner tracks background preparation and saving, rather than the active mouse
gesture; losing pointer capture cancels the unfinished stroke.
Conversion's full-state reply also completes its matching
publication when it equals the locally prepared state, releasing Undo and Finish.
Incremental edits retain unchanged channels and references;
new topology uses complete output validation. An immutable original PAC skin donor
is retained in authoring coordinates and matched by stable part identity. Generated
preview geometry never becomes the donor for subsequent strokes. Exact vertex
lineage preserves original packed records, including their separate skeletal and
cloth-guide lanes. New vertices use the existing validated weight transfer.
Ordinary PAC records support six skeletal influences; cloth-bound records support
four and reserve the remaining lanes for simulation guides. Generated vertices
requiring five or six bones use the ordinary branch instead of copying an
incompatible cloth binding. Compatible existing cloth records remain intact.
The 40-byte layout guard stays enabled.

PAC donor matching keeps verified original-vertex maps and rounded-position
matches first. Remaining nearest-record searches use NumPy float64 operations
with the same arithmetic and first-index tie rule as the scalar path. Temporary
memory scales with the donor mesh, not every source/target pair. A local spot
check with 2,000 queries and 1,500 donors took 0.264 seconds before and 0.019 seconds
after with NumPy loaded; this measures donor matching only, not complete export.

The XPBD preview keeps roots, scalp and reference transforms aligned. Cached scalp
surface contacts check guide segments and card width; neck and shoulder collision
shapes remain active. Card rows are resolved after their neighbouring segments,
and consistent component winding preserves concave ear contacts. A head-relative
rest-shape force prevents whole guides from rotating down under gravity; tip
retention decreases with Shape softness. The visible notice explains that editor
motion does not simulate the donor's in-game rig or physics. Eyes
share one `head:` reference identity and follow the head rigidly; they are
excluded from scalp planting and contacts. This uses the existing reference fields
and leaves the document version unchanged. Every movement
preset is checked separately. Existing bindings with radial offsets greater than
15% of the scalp's largest extent cannot play or settle: their broad root groups
distort under guide rotation. The UI requests smaller root selections or rigid
scalp sections; this does not block static editing or export. Play/Pause/Reset
are transient, Reset is deterministic, and editing during playback resumes from
the edited rest shape. Use settled shape requires a valid, played simulation and
creates one undoable rest-shape edit.
The host measures short guide segments at renderer float32 precision so full and
incremental JSON encodings agree, including conversion after cutting and erasing.
Simulation frames never enter drafts or output. Hair-to-hair collision and new
game physics rigs remain outside this workflow.

## Drafts, materials and output

Hair state v2 and draft v5 remain unchanged; older supported drafts still load.
Hair, geometry, materials, original vertex lineage, hairstyle identity and Mod
inclusion share an atomic transaction. Visibility is independent of Mod inclusion.
Reopening and saving again preserves native snapshot part identities and material
metadata. A clean native snapshot opened for autosave is invalidated by subsequent
grooming. Conversion is undoable. Finish waits for pending publications.

Open in Texture Editor and Apply edited DDS retain material slots, dimensions,
compression and mip counts. Required DDS are validated. The engine's unbound
`nonetexture0xffffffff.dds` marker remains in XML but is not a missing texture.
Qt setup text is included in all 14 built-in languages. The existing native Rust
editor still displays English controls; this change does not add a native
translation framework.

`hair_registration.py` appends the selected character's barber record and clones
its prefab, PAC, PAC_XML, HKX and icon under a distinct identity.
`mesh_hair_output.py` creates independent DDS/PATHC entries and verifies geometry,
weights, material closure and exact package payload readbacks before publication.
Cuts compare surviving skin rows through their original vertex mapping, so
removing or reordering vertices does not incorrectly enter the unchanged-topology
weight-edit path. Actual weight edits still require its exact-record checks.
Installed PAMT/PAZ files stay unchanged. Selector/PAPPT/PATHC data is shared, so
independently built hair packages must be reconciled against the mounted catalogue
before combining them. No in-game installation is performed by verification.

## Verification and reproducible probes

The 2026-09-20 mounted-data pass completed empty-scalp creation, drawing,
selection, Undo/Redo, draft reopening and temporary package export for all three
characters using compatible donors. Damiane also completed 30 existing-hair and
38 generated-hair host transactions, including grooming, cuts, conversion and
Undo; generated hair included settled-shape Undo/Redo. The final dense draft
reparsed at 50,319 vertices. All 13 package payload hashes matched before and
after donor-search acceleration, and each successful run retained unchanged
installed archive fingerprints. These are offscreen editor and file checks.

| Area | Evidence and acceptance |
|---|---|
| Setup and switching | Real Qt construction tests: no catalogue, required character, Start gating, accepted preparation, failure/retry, cancellation, stale results, same-target preset dispatch; existing archive-switch confirmation tests |
| Grooming | Production pointer dispatcher plus normal serialized candidates and Python host acknowledgements; geometry changes and fixed roots, Select/Ctrl/marquee, consecutive Draw, Cut/Erase/Delete, Lengthen and all shaping tools |
| Appearance | Production archive/material loaders; authored component-scale tests; root/group and rigid assignment; synthetic symmetry, width/density and DDS handoff/reapplication tests |
| Motion | Production draw buffers and DX12 captures; six movement presets, scalp card penetration, transient state, Pause/Reset, editing during playback and settled-shape Undo/Redo |
| Persistence and output | Generated and existing sequences, skeletal/cloth-record preservation, five/six-bone generated output, repeated save/reopen, conversion/Undo, inclusion, pending Finish, PAC reparsing and complete temporary overlay packages |
| Desktop and game | Offscreen captures do not prove normal-window interaction or presentation latency. Packaged startup/provenance is a separate check. In-game installation, barber selection, save/load, headgear and physics remain unverified. |

Focused commands (run Python with a pytest base temp outside the checkout):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_hair_workflow.py tests/test_mesh_hair_authoring.py tests/test_hair_registration.py --basetemp "$env:TEMP\cdmw-hair-tests"
cargo test --manifest-path tools/rust_mesh_lab/Cargo.toml --release --locked -p cdmw_mesh hair
cargo test --manifest-path tools/rust_mesh_lab/Cargo.toml --release --locked -p cdmw_mesh_lab hair
.\.venv\Scripts\python.exe scripts/generate_ui_localization_manifest.py --check
.\.venv\Scripts\python.exe scripts/validate_ui_localization_catalogs.py
```

`tools/dotnet_archive_backend/probe_hair_workflow.py` requires explicitly authorized
`--game`, `--cache`, `--worker` and temporary `--evidence` paths. `--character`
selects the mounted context; `--mode` selects generated/existing. `--audit-all`
checks every listed registration. `--prepared-setup` exercises the complete staged
loader. `--live-renderer` points to the compiled Rust test executable and runs the
production pointer/host matrix; `--capture-steps` also records textured per-tool
DX12 captures from the real material loader. `--resume-draft` checks reopening,
saving again and export. `--skip-package` limits an already covered output run.
An isolated checkout also needs the built native helpers: use the existing
`CDMW_MESH_CORE_BIN` and `CDMW_ARCHIVE_ACCELERATOR_BIN` overrides when those
binaries are in the main checkout.
`--style-index` selects a zero-based catalogue entry directly; use a compatible
entry from `--audit-all` (Oongka's first supported entry is index 1).
Set `CDMW_HAIR_PROBE_EMPTY_START=1` for the focused empty-scalp sequence: two
Draw strokes, selection, Lengthen, Undo/Redo, draft reopening and package export.
Short crown strokes are selected from the top view where they were drawn;
the front view may correctly hide them behind the head. Step captures include
that top view as well as the front view.
Every successful installed-data probe verifies unchanged archive fingerprints.

The Rust ignored `hair_production_render_and_benchmark` test consumes the probe's
`input.json` via `CDMW_HAIR_PROBE_INPUT` and writes into
`CDMW_HAIR_PROBE_OUTPUT`. It records front/side/rear images of every nonempty preset,
motion contacts and capture timings. These measurements exclude desktop compositor
presentation. Keep generated assets, captures and packages outside Git.

`hair_draw_shapes_render_and_drag_benchmark` uses the same retained loader input.
With `CDMW_HAIR_PROBE_CAPTURE_STEPS=1`, it captures each Draw shape before and after
Move and records CPU dispatcher/preview p50/p95 timings plus cached versus rebuilt
scalp-index generation timings. These timings exclude GPU upload and desktop
presentation; use a release test executable for performance evidence.

`hair_production_contact_regression` consumes the renderer probe's `candidate.json`
through the same environment variables. It samples deformed card vertices during
all six movements, records the worst contact and solver timing, and rejects scalp
penetration over 2 mm beyond the pinned root row. This catches a later segment
correction pushing an earlier card row back into the scalp.

`hair_production_settle_regression` consumes a captured hair-state JSON file and
checks settled-state validity for every frame of six movements at three frame-time
variations. Very short cut tips retain a small numerical separation during motion
so float32 rounding cannot collapse their segments and reject the settled edit.

The local-only Rust publication hold remains in force. New game rigs, additional
LOD writers and multi-PAC hairstyle authoring need their own verified support.
