# Hair creation in the existing Mesh Editor

Updated 2026-09-14. The current implementation follows the approved Hair UX
repair. The user deferred in-game checks and authorized finishing code and local
builds. Desktop interaction and game acceptance remain explicit gates.

## Workflow and ownership

The Mesh Editor Hair menu provides Create (Cropped, Bob, Long, Ponytail, Empty)
and thumbnail-based Edit choices from Damiane's mounted barber registration.
Finder enters the same workflow. A typed character context resolves matching
head and base-body roles through the resident catalogue; session/generation and
source identities scope its cache. Reference geometry has a separate bounded
cache (four entries, 128 MiB). Generation changes and cancellation reject stale
work. Scalp binding identities also include the actual appearance geometry, so
changed transforms invalidate attachments even when the PAC bytes are identical.
Alternative pickers apply `hair_head`/`hair_body` eligibility before facets,
counts and pagination, with a defensive UI check.
Each selection/preparation attempt has its own token, so late failures cannot
overwrite another choice and a failed attempt can be retried. Cancellation during
reference cache preparation releases untransferred material leases immediately;
cached copies also check cancellation before delivery.

Rust owns visible locks, guide/card generation, picking, grooming and simulation.
Qt owns entry points and lifecycle. Python owns archive/material loading, host
validation, drafts and immutable packages. Hair references use neutral shaded
geometry outside output. Actual donor DDS, tint, alpha, sidedness and normals use
the production material handoff. The default Hair view is textured and faces the
character; topology/rigging/UV controls are hidden while Hair is active.

Stable locks own explicit vertex sets independently of material Parts. Presets
replace their previous guides and sample scalp area. New locks draw textured cards
before release. Movement changes buffers during the stroke. Cuts keep proximal
shape and deletions remove geometry and output contribution. Width changes bound
or generated locks; follower density and Draw require generated hair. Explicit
mirror pairs govern drawing, grooming, cuts and deletion. Empty clicks and camera
movement do not publish transactions. Legacy generated bindings recover ownership;
legacy existing geometry remains unchanged until preparation.

Existing-card preparation accepts connected geometry, uniquely paired seams and
scalp-facing endpoints. Ambiguous sections remain highlighted and block Play/export.
Users can select unprepared sections by material, explicitly group them and choose
a root in the viewport, or classify actual scalp pieces as rigid. A material part
is not silently treated as one simulated strand.

Stroke work and production vertex buffers stay in Rust. An ordered queue bounds
pending actions at eight; each completed action retains its own host history step.
Version 2 updates omit immutable head/collision geometry, unchanged guides/bindings
and material parts. Same-topology changes carry only affected positions/normals;
the host commits them with sparse history, retaining UVs and original skin records.
Topology changes still use complete replacement validation. Acknowledgements update
revisions without installing another scene. Stale
acks are rejected. Finish waits for pending generation and publication. Host work
remains off the Qt thread; the previous scene stays available.
Validated hair states retain their revision separately from the canonical bytes,
avoiding a full document decode for each acknowledgement or status request.

Motion uses fixed 120 Hz CPU XPBD, with root, length/bend, gravity, damping, wind
and capsule constraints. The procedural torso/neck/head pose drives the reference,
roots, rigid sections and collision shapes. Simulated guide positions deform the
production hair buffers every frame. Strokes edit rest geometry and resume at the
current procedural pose. Reset and Use settled shape have separate semantics;
frames never enter undo, drafts or export. New game rigs and hair-to-hair collision
remain deferred.

Hair state v2 and draft v5 publish geometry, guides/locks, materials, original
vertex provenance and output inclusion atomically. Draft versions 1-4 remain
readable; older helpers reject `hair_authoring_v2`. Retained existing vertices
keep source UVs, exact skinning records and provenance through cuts/deletes. New
internal identities are allocated automatically and conflicts rechecked before
publication; package manifests use the readable hairstyle name.

## Addition contract traced from installed data

- Damiane's appearance references `meshparam_example_damian.xml` and its
  customization descriptor. The `hairShape` slot has five contiguous choices.
- A new choice clones a selector record, appends its independent prefab-table
  registration and relocates the prefab's PAC reference. Original records remain.
- Each new identity has its own PAC, PAC_XML, HKX, icon and DDS paths. The texture
  registry receives independent entries; materials point to the packaged copies.
- HKX and the Hair PBD profile retain the existing contract. New topology receives
  weights from the donor palette through the existing native transfer/writer.
  Geometry/weights/bounds are validated and packaged payloads reparsed.
- Reshaping with unchanged topology uses the geometry-only PAC writer, preserving
  the donor's original packed skinning records, including eight-influence vertices.
- The inspected primary donor exposes only LOD0. A donor with additional PAC
  LODs is rejected until an affected-LOD writer has been verified.

`hair_registration.py` owns immutable selector/identity preparation.
`mesh_hair_output.py` composes authored geometry, textures and required metadata
through `export_archive_overlay_package`. Source revisions, identity/catalogue
conflicts and exact packed-payload readbacks are checked before atomic publication.
Installed archives are only read. Shared selector/PAPPT/PATHC changes mean packages
must be rebuilt against the currently mounted catalogue when combining hair mods;
two independently built sixth-choice test packages are alternatives, not a merge.

## Validation and reproducible probes

Focused Python tests cover the real Qt menu/request lifecycle, stale results,
reference cache isolation/bounds, v5 reopening and legacy drafts, cancellation,
revision rejection, atomic transactions/Finish, Undo/Redo and packed eight-influence
reshape/cut/delete output. Resident catalogue fixtures cover filtering before
pagination. Rust tests drive the production pointer dispatcher for selection,
Move, Draw, symmetric Cut/Erase, Lengthen, Comb, Smooth, Curl, Clump and Escape;
width/density and event-frequency checks inspect draw buffers and root stability.
The incremental protocol is tested through its real file writer and host reader,
including atomic failure, history bounds and Finish. Motion tests require hair
deformation separately from reference movement, reset and transient authoring state.

`tools/dotnet_archive_backend/probe_hair_workflow.py` opens the resident catalogue,
resolves actual character dependencies and prepares an editor handoff on its normal
worker path. It supports `--candidate` for host application, draft reopening and
reparsed package output, `--skip-package` for repeated timing, and `--profile-host`
for stage diagnosis. Required paths are `--game`, `--cache`, `--worker`, `--evidence`;
`--mode` is generated or existing. Evidence stays outside installed archives.

Set `CDMW_HAIR_PROBE_INPUT` to that handoff's `input.json` and
`CDMW_HAIR_PROBE_OUTPUT` to a new temporary folder, then run from the Rust workspace:

```powershell
cargo test --release --locked -p cdmw_mesh_lab hair_production_render_and_benchmark -- --ignored --nocapture
```

This probe uses DDS and shader settings discovered by the real loader, without
test-only material overrides. It captures four presets from three views and
measures production pointer dispatch and draw snapshots with DX12 offscreen
rendering at 1920x1080. The observed 256-guide, 16-point, 49,152-vertex scene was
about 108 FPS and 1.1 ms p95 input-to-draw-buffer CPU time. This excludes desktop
presentation and must not be reported as normal-window input latency.

A generated candidate reopened its v5 draft and published/reparsed all 13 files
through the real package pipeline, with installed archive fingerprints unchanged.
The original 49,516-vertex donor became 49,167 vertices including excluded-section
placeholders. Existing-card preparation identifies ambiguous disconnected sections
in the real donor; correction is required before motion or export. The probe's
explicit root correction, Cut and Delete sequence reduced that donor to 49,477
vertices, reopened its v5 draft and reparsed all 13 package payloads. Its release
renderer measured about 63 FPS and 4.4 ms p95 input-to-buffer time, with measurable
non-root hair deformation. No installed archive bytes were changed.

Cold editor setup measured roughly 11-17 seconds during investigation. The 3-second
warm-open and 500-ms acknowledgement targets have not been established. An isolated
metadata publication fell from about 4.8 seconds to 686 ms after removing full-mesh
transactions; this is neither a grooming-latency nor presentation measurement.
History accounting was further optimized without changing retained-byte semantics.
On the saved 256-guide, 49,152-bound-vertex scene, revision lookup alone previously
decoded 10.5 MB and took about 101 ms p95; cached validated revision reads avoid
that work. This component measurement excludes transaction validation and display.
Full host/presentation measurements remain required. Normal-window picker/editor
captures and the complete real-user tool matrix are also outstanding.

## Remaining acceptance

The feature is not game-verified. The user must still confirm an additional
choice appears, original choices remain usable, and selection survives save/load.
Then validate one reshaped and one generated hairstyle for textures, attachment,
head movement, running, relevant headgear, LOD transitions and game motion.
Normal-window interaction and presentation performance also remain separate
checks; offscreen renderer evidence does not establish them.

If game data alone cannot provide additional selectable choices, stop and record
the exact blocker. Replacements or executable hooks require revised scope. Keep
the local-only Rust publication hold in force.
