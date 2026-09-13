# Hair creation in the existing Mesh Editor

Updated 2026-09-13. Code implementation follows the approved Damiane plan. The
user deferred the first in-game check and explicitly requested continuing the
remaining code. This changes delivery order, not game acceptance criteria.

## Implemented workflow

Hair lives in the existing Rust editor: Setup, Groom, Appearance and Motion use
its viewport, Parts, history and Finish. Finder Create/Edit actions prepare the
hair dependencies asynchronously and hand off to the editor. A separate head
PAC can contain only a face mask; setup also loads the body's crown/back and
retains its neck/shoulders outside hairstyle output.

New hair uses scalp attachments, guides, cropped/bob/long/ponytail presets and
textured cards. Grooming supports comb, smooth, cut, lengthen, curl, clump and
optional symmetry. Explicit part groups and guide/root correction reshape
existing hair without changing its UVs. Generated groups expose width, density
and atlas bounds, initially copied from a connected donor card rather than
squeezing the entire hair atlas onto each new card.

The CPU XPBD solver uses a fixed 120 Hz step, pinned roots, distance and bend
constraints, damping, gravity, wind and fitting capsules. Card vertices deform
through the production renderer. Simulation is transient. Strokes pause/restart
motion; Use settled shape and conversion to ordinary topology are explicit
undoable transactions. Hair-to-hair collision and new game physics rigs are deferred.

Python owns reference/dependency decoding, validation and immutable package
output. Qt owns pickers, lifecycle and handoff. No per-frame Python messages are
used. Version 1 hair state stores reference geometry/identities, attachments,
guides, groups, card settings, bindings, donor provenance and target registration.
Materials travel with the same replacement snapshot. Draft v4 publishes hair,
geometry and dependencies together and retains reads of v1-3. Missing files,
changed heads, stale revisions and unsupported helpers fail explicitly.

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

Focused Python tests cover immutable state, topology and UV rules, complete
transaction/Finish publication, undo/redo, v4 persistence, legacy drafts, missing
textures, candidate revisions, reference changes and cancelled body loading.
Headless Qt construction exercises Finder button handoff and stale-result handling.
Rust tests cover four distinct presets, explicit binding, conversion, cancellation,
reference isolation, roots, stretch/collisions, reset and frame-rate behavior.

The authorized real-asset probe reads the installed catalogue and creates a Rust
handoff, then consumes the generated candidate through the production host/writer:

```powershell
.\.venv\Scripts\python.exe tools/dotnet_archive_backend/probe_hair_authoring.py `
  --package-root <game> --cache-root <outside-game-cache> --evidence <temporary-folder> `
  --mode generated --stage prepare --new-stem cd_phw_00_hair_00_9001_01_player
# In tools/rust_mesh_lab, set CDMW_HAIR_PROBE_INPUT=<temporary-folder>/input.json
# and CDMW_HAIR_PROBE_OUTPUT=<temporary-folder>, then:
cargo test --release --locked -p cdmw_mesh_lab hair_production_render_and_benchmark -- --ignored --nocapture
# Repeat the Python command with --stage publish to build/reparse the package.
# Use --mode existing and a distinct stem/folder for the reshape case.
```

The clone-only first milestone remains in `probe_hair_registration.py`.
Machine-local evidence and game assets are not committed. Captured production
DX12 output and benchmark JSON belong in the temporary evidence directory.
The reference benchmark uses 256 guides x 16 points and 49,152 hair vertices at
1920x1080. On this PC's RX 9070 XT, the initial synthetic scene measured about
105 FPS, with 2.5 ms p95 CPU grooming/deformation. Real textured scene captures
also exceeded 30 FPS and the 100 ms feedback budget. These are offscreen timings
including synchronous GPU readback, excluding Qt and desktop presentation.

The generated and reshaped real-asset probes each published and reparsed a
13-payload package. The generated donor changed from 49,516 to 49,167 vertices
(49,152 authored hair vertices plus section placeholders); the reshaped donor
retained 49,516 vertices with changed positions. Both have distinct asset names
and preserve the original five selector records. This is package compatibility
evidence, not evidence that the game accepts the new selection or physics.

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
