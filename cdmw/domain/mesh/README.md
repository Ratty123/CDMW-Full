# Mesh Domain

Owns pure mesh session and validation rules.

Keep mesh parsing, replacement building, native preview packaging, and PySide
controls outside this package. Use `cdmw/modding/` for mesh/material operations,
`cdmw/rendering/` for preview packaging, and `cdmw/ui/mesh_editor/` for UI.

## Derived panel authority

`panel_state.py` defines the immutable session/revision/generation contract for
derived Mesh Editor values. A pending, unavailable, or failed request may retain
last-known-good data from the same session, but `value_revision` keeps that data
distinct from the requested `revision`; only a ready matching value is current
authority. `MeshPanelUnavailableError` is reserved for expected conditions such
as a native snapshot that is not yet authoritative, leaving unexpected failures
available to diagnostics.

## Bounded gesture samples

`stroke_samples.py` owns the pure incremental screen-path bound used by Mesh
Editor live gestures. It always keeps first/final samples, removes points within
the 2.5 px path tolerance, retains turns of at least 12 degrees and a slow-motion
sample every 50 ms, then evicts the least important interior point at the
configured hard limit. The UI packet owner applies the 256-sample / 64 KiB
packet bounds and fixed segment queue; the resident C# form applies the same
sample contract before lasso/toggle mouse-up and before writing a coalesced
protocol path.

## Output policy

`authoring_capability.py` classifies every session as **Exact Game Asset**,
**Free Edit/Rebuild**, or **Read Only** from the mesh format, LOD, explicit
destination, and proven native operation set. Exact PAC/PAM/PAMLOD LOD0 keeps
the writer's protected-record constraints and never treats the capability model
as output authority; the writer and validator still decide whether a revision
can be published. Higher LODs remain exact-policy sessions with authoring marked
unproven rather than silently falling back. Imported OBJ/FBX/DAE/glTF sessions
stay blocked until a new non-exact output folder is selected, while MeshInfo and
unknown formats retain selection and inspection without mutation.

## Authoritative UI lifecycle state

`ui_state.py` defines the immutable `MeshEditorUiState` and its 15 safety
invariants; `ui_state_reducer.py` owns the pure session, process, service,
renderer, interaction, report, and recovery transitions. The model separates
resident service revision, renderer revision and last acknowledgement, while a
separate geometry revision preserves report authority across selection-only
changes. It binds pending request authority to one session and process
generation, and derives authoring and validation-gated output only after the
matching revision equalities. Strict callers raise
on an impossible transition; production reduction enters sticky fail-closed
recovery with a bounded invariant report. Replaying the same event sequence
produces the same state.

## Body region segmentation

`body_regions.py` turns a skinned body's own skin weights plus the bone names
from its `.pab` into named regions (thigh, forearm, breast, ...) with per-vertex
weights, so a morph slider can target "the left thigh" without a hand-painted
vertex selection.

PAC influence slots are per-mesh palette tokens, so pass
`bone_palette=resolve_pac_bone_palette(raw, skeleton)`. Passing an empty palette
means "unresolved" and the map claims nothing rather than mislabelling anatomy.
`primary_influence_only` (the default) keeps each vertex's heaviest influence,
because only the primary PAC slot decodes reliably; regions are then
anatomically correct but carry no falloff.

`DEFAULT_BODY_REGION_RULES` is a data table matched against bone names, ranked by
whole-token match, then rule priority, then pattern length. It is tuned for the
Crimson Desert Biped rig, where twist and muscle helpers carry most limb skin
(`ForeTwist01`, `UpArmTwist1`, `UpperFMuscle`) and the breasts are driven by
sided `Chest` bones. Rig naming varies, so anything the table fails to claim is
reported rather than dropped — check `unmapped_bone_names` and
`unmapped_weight_fraction` when adapting it.

Measured over the vanilla nude bodies of every race: 27-29 populated regions,
0.00% unclaimed skin weight, and 97-100% left/right symmetry.

`body_region_falloff.py` then feathers those hard region edges outward by a
geodesic band (default 3 cm of surface), renormalizing so each vertex's region
weights still sum to exactly 1. Distance is measured in metres along the
surface, not adjacency rings, so the same band feathers the same amount of body
regardless of mesh density. Without it a slider creases the surface at region
boundaries.

`body_region_sliders.py` instantiates a template set (Size, Length, Taper,
Flatten, Shift) against every region, producing a `MeshMorphProfile` of ready
`MeshMorphDefinition` objects. Each slider takes its weighted vertices, pivot,
and local basis from the region, so nothing in it has to know what a thigh is.
A vanilla female body yields 145 sliders across 29 regions.

Slider rules evaluate in Python and reach the native core as sparse deltas, so
adding a rule kind needs no C++ change. `radius` (girth, proportional to
distance from the bone axis) was added for this: `volume` displaces every vertex
the same absolute amount, which is not what a Size slider means.

Generated profiles are fingerprinted over exactly the submeshes their
definitions touch, matching what `MeshService.activate_morph_profile` checks —
using the region map's own fingerprint instead makes every region-scoped profile
fail to activate. `tests/test_mesh_body_region_slider_native.py` drives a
generated profile through the real service and native core to hold that.

`body_region_atlas.py` is the Qt-free presentation model for a region browser:
grouped rows, a readable summary, warnings worth surfacing, and a stable colour
per region so a list, a 3D overlay, and an exported OBJ all agree. Colours are
keyed by sorted region id, so adding a region cannot recolour the others. The
widget that renders it lives at `cdmw/ui/mesh_editor/body_region_atlas_panel.py`
and is self-contained — it emits the picked region ids and knows nothing about
its host.

Inspect a real body headlessly with `python -m tools.dump_body_region_map`, which
prints the per-region report, applies the falloff, and can write a
region-coloured OBJ. Pass `--falloff 0` for hard edges.

Related tests: `tests/test_mesh_body_regions.py`, plus mesh and static
replacement entries under `tests/`.
