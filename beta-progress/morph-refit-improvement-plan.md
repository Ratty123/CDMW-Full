# Morph & Refit improvement plan

- Plan ID: `MRF`
- Created: 2026-10-17 (Europe/Stockholm)
- Status: Planned. Implementation has not started.
- Project: `D:\CLAUDETEST\CDMW Full`
- Game reference: `C:\games\Steam\steamapps\common\Crimson Desert`
- Plan file: `beta-progress/morph-refit-improvement-plan.md`
- Shared completion log: [progress.md](progress.md)
- Investigation baseline: branch `RR/independent-item-packages`, commit `afa050237092d1aa38ad0642ceabdd889da907da`.
- Checkout when this plan was prepared: `b99e5c267f74e135410b9a627df8abc9a05d920d`. Earlier measurements are not fresh validation of this revision.

## Goal

Improve how garments fit the body while preserving authored layer spacing, sensible surface correspondence, rigid pieces, masks, source identity, and reliable undo and failure handling.

Start with the two reproduced weaknesses: disconnected garment layers within one Part nearly collapsing together, and tiny mismatches between adjoining body Parts causing much larger changes in the fitted garment. Add clearer bulk editing and final-fit diagnostics. Consider the small connectivity optimization only when measurement supports it.

This document prepares the work requested after the investigation. Creating or reading it does not start implementation. Begin implementation when the user asks to start, using authorization already established in that session.

## Current handoff

- Completed: MRF-DOC-01 only (planning).
- Active task: None.
- Working agent: Unassigned.
- Claimed source files: None.
- Next task: MRF-BASE-01.
- Blockers: None identified for planning.
- Required tasks: MRF-BASE-01, MRF-FIT-01, MRF-FIT-02, MRF-UI-01, MRF-DIAG-01, and MRF-DONE-01.
- Conditional tasks: MRF-PERF-01, MRF-RE-01, and MRF-VIS-01. Record any deferral and its reason here; leave an unperformed task unchecked.
- Evidence limit: Existing results are source inspection and synthetic native execution. No fresh native build, rendered review, REA session, or in-game validation was performed during the investigation.

## Completed preparation

- [x] **MRF-DOC-01 complete:** Created this plan, retained the investigation evidence, and established matching task IDs and shared completion tracking.

Completion: 2026-10-17. Documentation only. Saved-content checks confirmed unique task IDs, balanced fenced blocks, only MRF-DOC-01 checked, one matching progress entry, and preservation of prior shared entries. All implementation and conditional tasks remain unchecked.

## Shared progress rules for every agent

1. Before implementation, read the applicable project instructions, this plan, and `beta-progress/progress.md`. If that exact progress file is missing, create it before the first implementation change. Reuse it if another agent has already created it.
2. The progress file is shared by all plans and agents in this folder. Preserve existing entries and formatting. Do not clear, replace, reorder, or rename it, and do not create a separate progress file for this plan.
3. Claim the active task and affected source files in Current handoff before editing. Coordinate overlapping changes with other agents. The two fitting tasks touch shared native owners and should be implemented sequentially unless file ownership is explicitly coordinated.
4. Use the stable namespaced IDs below. Keep one authoritative completion checkbox per task in this plan.
5. Mark a task `[x]` only after its work and acceptance checks are complete. Add a Completion note with the date, result, exact relevant checks, evidence type, and limitations. Record the source/build identity when executable behavior was tested.
6. At the same completion checkpoint, append one short completed-work bullet to the shared progress file. Use its existing format: `- YYYY-MM-DD | MRF-FIT-01 | Completed outcome; verified <check and result>.`
7. Read both files immediately before editing. With ThinkForge, use the latest read's SHA-256 and a targeted patch. If a file changed, reread and merge only the intended update. Never write an old whole-file copy over newer shared work.
8. The two files are separate writes. Reread both afterward and verify that the checkbox, evidence note, and matching progress entry agree. If interrupted between writes, reconcile the missing half on resume after checking the evidence.
9. Check for an existing task ID before appending so retries do not duplicate completions. Split oversized tasks into stable named subtasks before claiming partial completion.
10. Keep ownership, partial work, blockers, deferred choices, and the next action in this plan. The shared log stays a simple list of completed work.
11. If later evidence invalidates a completed task, reopen its checkbox and record the reason here. Append a dated correction referring to its original progress entry; preserve other agents' history.
12. Update both documents throughout implementation and before each handoff. Planning, diagnosis, successful compilation, and a deferred proposal must not be described as completed fixes.

## Scope and invariants

- Preserve Part, vertex, and triangle identities, topology, authored source coordinates, source mappings, palettes, bone indices, and weights.
- Preserve neutral-based evaluation, repeat fitting, body-slider following, reset, bake, undo, and history.
- Preserve rigid-component shape, protected masks, seam behavior, body clearance, and layer-order checks.
- Invalid candidates must fail atomically without publishing partial geometry, settings, or history.
- Keep changes in the existing native, service, and UI owners. Do not place expensive mesh analysis on the UI thread.
- Do not split or remesh source assets merely to make a solver case pass. Do not add global vertex welding or unrestricted nearest-body projection as a shortcut.
- Retain the existing source/skeleton/neutral contracts. No Morph authoring defect was independently reproduced in the investigation.
- General self-collision of connected folds, new skinning layouts, runtime cloth changes, broad LOD work, and engine changes are outside the initial fitting fixes.
- Separate Mesh Editor performance, virtual-loader, window movement/DPI, and Inspect File Formats plans retain their own scope.
- Follow current project instructions and the relevant section of `docs/test-matrix.md`. Use `cdmw-verify-mesh-editor` when selecting implementation proof. Use lifecycle or archive-mutation guidance only when those behaviors actually change.
- This planning task does not launch visible UI, attach a debugger, edit archives, build, package, install, or publish. A configured game path is not permission to alter PAMT/PAZ files. Reuse later session authorization for the exact work it covers.

## Recorded investigation evidence

These observations came from the previous investigation, using the existing native helper at `native/cdmw_mesh_core/build/Release/cdmw-mesh-core.exe`. Its exact build provenance was not established by rebuilding. All numbers below are synthetic model units, not real-outfit measurements.

### A. Layer preservation depends on Part packaging

The probe used a closed cylindrical arm of radius 0.06 and two sleeve surfaces with radii 0.10 and 0.11. It compared identical surfaces stored in separate Parts versus disconnected islands inside one Part. Tightness was 100%, clearance 0.1%, and the morph profile was empty.

| Arrangement | Initial gap | Mean fitted gap | Accepted |
| --- | ---: | ---: | --- |
| Separate Parts | 0.010000 | 0.009984178594415938 | Yes |
| Disconnected islands in one Part | 0.010000 | 0.00001426212757850453 | Yes |

The same-Part case lost about 99.86% of the initial gap. The body stayed unchanged in both cases.

The current layer-standoff search, layer-link construction, and garment layer constraints exclude same-Part relationships. Final validation cannot protect a layer relationship that was not constructed. Relevant owners: S1 and S2.

Reproduction details to retain when converting the probe into a regression:

- Use `_arm()` and `_sleeve()` from `tests/test_mesh_refit_tightening_native.py`.
- Arm: 64 segments, radius 0.06, Y rings 0, 0.1, 0.2, 0.3, 0.4, 0.5, with caps.
- Each sleeve: 32 segments, Y rings 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4. Outer radius is 0.11.
- For the combined Part, offset the outer sleeve face indices by the inner sleeve vertex count. Preserve the otherwise identical inputs.
- Measure radial layer separation over the middle-ring vertices corresponding to indices 64 through 159 in each sleeve.

### B. Tiny body-seam mismatch changes the fitted hem

The second probe extended the existing skirt/legs/feet test. Upper and lower body Parts met at an exact boundary, then the upper Part was shifted slightly along X.

| Upper Part X offset | Minimum fitted hem Y | Maximum garment vertex change from exact-seam result | Accepted |
| --- | ---: | ---: | --- |
| 0 | 0.1647062892653445 | 0 | Yes |
| 0.000001 | 0.11708891222814806 | 0.076274046613093 | Yes |
| 0.000006 | 0.11708869683047902 | 0.07627414600609304 | Yes |

The existing exact-seam scenario requires the hem to stay above Y = 0.155. The shifted cases were accepted despite falling below that reference requirement.

The body adjacency graph uses exact `Vec3` position keys, and correspondence walks connected triangles. Other body boundary bookkeeping also uses exact positions. The observation establishes sensitivity around body boundaries; it does not independently isolate every contributing stage. Relevant owners: S1 and S2.

Reproduction details:

- Start from `test_hem_follows_the_leg_instead_of_dropping_onto_nearby_feet`.
- Two legs: X centers -0.09 and 0.09, radius 0.05, 24 segments, capped, with Y rings 0, 0.05, 0.1, 0.15, 0.25, 0.4, 1.
- Preserve the foot shaping: `z * (1 + 2.5 * max(0, 1 - y / 0.16)) + 0.1 * max(0, 1 - y / 0.16)`.
- Split triangles into lower/upper Parts according to whether mean triangle Y is at least 0.15. Remap the used vertices within each Part.
- Skirt: radius 0.23, 48 segments, Y rings 0.17, 0.20, 0.24, 0.35, 0.55, 0.8.
- Body drivers are Parts 0 and 1; garment is Part 2. Apply each upper-Part offset before binding, with 100% tightness and 0.1% clearance.

### C. Smaller opportunities

- Mixed-selection controls are populated from one Part, and Apply sends all displayed settings. Changing clearance can therefore also copy mode or intensity across Parts. This is source-confirmed behavior, not a live UI reproduction. The existing Fit to body action already reads authoritative per-Part state; preserve that behavior. Owners: S3-S5.
- The recorded maximum and p95 binding distances stayed at 0.05 before and after both layer fits. These are stored binding measurements, not a final-fit quality score. The current UI warning is about binding distance. Owners: S2, S3, S8.
- The strain-limiting loop rebuilds unchanged face-neighbor connectivity during up to 64 passes. Building it once per call is a possible optimization. No timing improvement was measured. Owner: S1.

## Required tasks

### MRF-BASE-01: Reconfirm the implementation starting point

- [ ] **MRF-BASE-01 complete:** Current owners, task claims, relevant evidence, and the focused validation scope are recorded.

Work:

- Read current instructions, this plan, the shared progress file, Git status, and the relevant source owners.
- Compare the current implementation with the recorded investigation. Do not implement a stale proposal if another agent has already changed the behavior.
- Re-establish the two missing regression cases before their fixes. Reuse earlier passing checks when the relevant code is unchanged and their evidence remains applicable.
- Record source revision, actual helper path/build identity, input construction, and measurement method. When native source changes, use the current owning build instructions to exercise the changed target instead of an older executable.

Acceptance:

- Each next change has an identified owner and a reproducible failing or inadequate baseline.
- The chosen checks address the changed contract. No broad gate or unrelated build is added just because Mesh Editor files are involved.
- The shared progress file exists and task ownership is clear.

Completion: Pending.

### MRF-FIT-01: Preserve disconnected layers inside one Part

- [ ] **MRF-FIT-01 complete:** The layer reproduction retains meaningful spacing regardless of whether its surfaces share a Part.

Depends on: MRF-BASE-01.

Work:

- Identify separate surface islands while recognizing trustworthy seam equivalence.
- Consider cross-island layer relationships within a Part, consistently across standoff, layer links, clearance, and final validation.
- Keep own faces and immediate continuous-surface neighbors out of layer searches. Do not merely remove the existing same-Part skips.
- Retain the current distance, normal, body-region, and ambiguous-trim safeguards.

Acceptance:

- The same-Part fixture preserves spacing comparable to its separate-Part reference. Document a numerical tolerance before evaluating the fix, using source precision and the fixture's scale. Do not loosen the reference until a collapsed layer passes.
- Check the minimum local gap as well as the mean, so an average does not hide collapse.
- The body stays unchanged, and original source identities, topology, skin data, and authored coordinates remain intact.
- Multiple nested islands, seam-equivalent panels, protected vertices, rigid trim, and close layers behave correctly.
- Existing garment seam, layer-order, clearance, and atomic-failure checks for the changed paths remain valid.

Boundary: Initial work covers disconnected surface islands. It does not claim general self-collision handling for connected folds.

Completion: Pending.

### MRF-FIT-02: Recognize near-matching body seams conservatively

- [ ] **MRF-FIT-02 complete:** Tiny intended seam mismatches no longer produce the recorded large accepted change in the fitted hem.

Depends on: MRF-BASE-01. Coordinate with MRF-FIT-01 before editing the shared native owners.

Work:

- Confirm which exact-position adjacency and boundary stages contribute to the reproduction.
- Introduce virtual fitting adjacency only for confidently matched body boundary edges.
- Require compatible orientation, an unambiguous counterpart, and a very small precision-aware tolerance. PAC decoding and quantization provide useful bounds; see S6 and S7.
- Use existing conservative garment seam matching as a reference. Do not assume nearby positions alone prove continuity.
- Preserve original body coordinates and triangle identities, body-region restrictions, and full-body clearance checks.

Acceptance:

- The exact-seam and both shifted cases stay above the existing synthetic hem Y threshold of 0.155.
- Their garment results remain close under a documented continuity tolerance that accounts for the small intentional body shift. Bit-identical output is not required.
- Nearby limbs, opposing surfaces, parallel rims, intentional openings, and thin surfaces are not wrongly connected.
- Ambiguous matches retain a conservative result or fail atomically rather than creating unsupported graph connections.
- Existing foot-avoidance, open-boundary, garment seam, and source-identity checks remain valid.

Boundary: Change the fitting interpretation of a boundary, not the source mesh through global welding or vertex snapping.

Completion: Pending.

### MRF-UI-01: Preserve unchanged settings in mixed Part selections

- [ ] **MRF-UI-01 complete:** Bulk edits modify only the fields the user changes while preserving each Part's other settings.

Depends on: MRF-BASE-01.

Work:

- Show Mixed where selected Parts have differing values.
- Track which fields the user changes and apply those fields against authoritative per-Part state.
- Reuse native omitted-field and per-Part batch behavior where sufficient. Trace affected protocol consumers if a contract change is necessary.
- Retain an explicit full-settings copy action only if that behavior remains useful and clear.

Acceptance:

- Changing clearance on a mixed cloth/rigid selection preserves mode, intensity, enabled state, tightness, and masks unless the user changes those fields.
- Apply Selected and Apply All have clear, tested semantics.
- The existing Fit to body behavior continues to preserve unrelated authoritative per-Part settings.
- A batch remains atomic and produces one undoable operation. Stale UI state cannot silently replace unrelated current settings.
- Verify actual UI-to-command behavior with the smallest relevant behavior test; source-text matching alone is insufficient.

Completion: Pending.

### MRF-DIAG-01: Add useful final-fit diagnostics

- [ ] **MRF-DIAG-01 complete:** Users can distinguish initial binding information from measurements of the current fitted geometry.

Depends on: MRF-BASE-01; use the corrected layer model from MRF-FIT-01 for layer diagnostics.

Work:

- Label initial binding-distance warnings according to what they measure.
- Add bounded, on-demand current-fit measurements for body clearance and recognized inter-layer spacing, with the affected Part/area identifiable.
- Include deformation or constraint information where it helps explain why the fit stopped. A heatmap or selecting affected geometry is optional.
- Keep diagnostics read-only and use existing work ownership for expensive analysis.

Acceptance:

- The original layer probe can distinguish retained spacing from near-collapse even when binding metadata is identical.
- Body clearance and layer separation are presented separately.
- Measurements are tied to the current mesh state, with sampling limits and unavailable results reported honestly.
- Running diagnostics does not change geometry, settings, masks, or undo history.
- Work and memory are bounded; no new UI-thread stall is introduced.
- Do not add automatic rejection thresholds without separate evidence that intentional folds and overlaps remain valid.

Completion: Pending.

## Conditional tasks

### MRF-PERF-01: Reuse invariant neighbor lists within one fit

- [ ] **MRF-PERF-01 complete:** The measured optimization preserves fit results and avoids repeated connectivity construction.

Start only after a relevant baseline shows useful repeated work. This task is optional and does not block the fitting fixes.

Work: Build the unchanged face-neighbor lists once outside the strain-limiting pass loop. Preserve neighbor and iteration ordering. Recompute geometry-dependent quantities every pass. Avoid a persistent cross-call cache in the first change.

Acceptance: Equivalent inputs preserve the existing numerical result and failure behavior. Record repeated before/after timing on the same representative case, including variability. Claim a speed improvement only if it is measured beyond timing noise. If the benefit is negligible, retain the existing code and record the decision as deferred here.

Completion: Pending.

### MRF-RE-01: Use REA for a concrete remaining format or engine question

- [ ] **MRF-RE-01 complete:** A narrowly defined blocking question has evidence sufficient for a decision, with remaining limits recorded.

Start only when local source and controlled native checks cannot resolve a relevant issue. The two reproduced fitting weaknesses do not require engine reverse engineering to establish that they exist.

Work: State the question, exact game/build identity, REA connection status, and read-only investigation method before analysis. Keep runtime observations separate from authoring-side behavior.

Acceptance: Record observed facts, any inference, the resulting decision, and what remains unproven. No speculative engine workaround or broader format support is introduced from weak evidence. Follow the current session's authorization for debugger attachment, game runs, and real-data access.

Completion: Pending.

### MRF-VIS-01: Validate representative real assets when authorized

- [ ] **MRF-VIS-01 complete:** The claimed visual or in-game behavior is supported by the corresponding real-asset evidence.

Start only when representative assets and the required visible or game validation are within the authorized scope.

Work: Compare matched before/after poses and views on suitable layered and seam-boundary assets. Include rigid trim and a body-morph change where relevant. Identify source assets and the exact executable. Inspect export or animation behavior only when it is part of the claimed improvement.

Acceptance: Preserve source provenance and archive fingerprints, use temporary evidence, and record any visible regression or limitation. A rendered editor check proves only the rendered editor result; animation, LOD, and runtime cloth claims require their own evidence. Do not turn parser success or synthetic tests into in-game proof.

Completion: Pending.

## Final required task

### MRF-DONE-01: Verify and close the implemented scope

- [ ] **MRF-DONE-01 complete:** Required changes have focused proof, consistent tracking, and an accurate handoff.

Depends on: All other required tasks. Conditional tasks may remain deferred with their reasons recorded.

Work:

- Compare matched before/after geometry and behavior for the changes actually made.
- Confirm neutral evaluation, body-slider following, rigid-component distances, masks, atomic failure, undo/reset/bake, and source/skin identity through the relevant focused tests.
- Inspect task-owned diffs and update the nearest owning documentation when behavior changes. Follow current changelog and local commit rules.
- Record remaining limits and the next useful task without overstating the proof.

Acceptance:

- Every completed task has one checked checkbox, completion evidence, and a matching shared progress entry.
- Required acceptance checks pass against the intended implementation/build. Unrelated failures are isolated and reported.
- Conditional or unperformed work remains unchecked. If only part of the required scope is complete, leave this task pending and report that scope accurately.
- No regression is known within the exercised scope. The handoff states whether proof is source-only, synthetic/native, rendered, real-asset, or in-game.
- Do not claim that nonvisual checks alone prove the requested appearance on all game meshes.

Completion: Pending.

## Focused verification baseline

The investigation ran 15 passing cases across the selectors below, with no reported failures or skips. These results establish the previous baseline, not completion of any fix. Use the current test matrix and relevant selectors when work starts; widen only to resolve a concrete remaining risk.

The prior harness used the project `.venv/Scripts/python.exe -B`, `pytest.main`, `-q`, `-p no:cacheprovider`, and unique `--basetemp` directories under the operating system temp folder. No native rebuild was performed.

```text
tests/test_mesh_refit_tightening_native.py::test_tessellation_taper_ellipse_and_folded_opening
tests/test_mesh_refit_tightening_native.py::test_quantized_panel_seams_share_displacement
tests/test_mesh_refit_tightening_native.py::test_hem_follows_the_leg_instead_of_dropping_onto_nearby_feet
tests/test_mesh_refit_tightening_native.py::test_repeat_percentage_reset_bake_and_history_are_neutral_based
tests/test_mesh_refit_tightening_native.py::test_unreliable_fit_fails_without_partial_settings_or_geometry
tests/test_mesh_refit_tightening_native.py::test_failed_body_change_with_active_fit_is_atomic
tests/test_mesh_refit_tightening_native.py::test_post_fit_correction_cannot_publish_a_body_intersection
tests/test_mesh_refit_tightening_native.py::test_body_slider_following_remains_correct
tests/test_mesh_refit_tightening_service.py::test_fit_reads_authoritative_part_settings_and_publishes_one_undo
tests/test_native_mesh_editor_morph_refit.py::test_refit_batch_preserves_omitted_settings_and_mixes_cleared_and_replaced_masks
```

The three garment-seam parameters, two hem cases, two failed-body-change cases, and two body-slider cases account for the parameterized count. Two additional layer-packaging probes and three body-seam probes produced the numerical findings above. The temporary probe scripts were not added to the repository; convert the described cases into maintained regressions during the relevant implementation task.

Documentation-only preparation requires saved-content inspection and a task-scoped diff, not application tests, native builds, broad gates, packaging, or game launches.

## Source map

Paths are relative to `D:\CLAUDETEST\CDMW Full`. Entry lines identify the reviewed baseline; reread current owners before editing.

| Ref | Owning source | Relevant entry lines |
| --- | --- | --- |
| S1 | `native/cdmw_mesh_core/src/owners/session_refit_conform.cpp` | 217: exact body adjacency; 274: correspondence walk; 343: layer standoff; 431: layer links; 535: repeated neighbor construction |
| S2 | `native/cdmw_mesh_core/src/owners/session_morph_01.cpp` | 191: conservative garment seams; 723: connected-surface grouping; 831: same-Part layer exclusion; 871: body boundary data; 1556: layer validation; 1810: candidate composition; 2017: stored binding metrics |
| S3 | `tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_ui.rs` | 3366: binding warning; 3379: controls from a selected Part; 3500: full-field apply |
| S4 | `cdmw/services/mesh_service_morph.py` | 1551: configure refit; 1597: authoritative Fit to body settings |
| S5 | `native/cdmw_mesh_core/src/owners/session_morph_commands.cpp` | 544: omitted-field preservation; 584: per-Part batch settings |
| S6 | `cdmw/modding/mesh_parser.py` | 1725 and 1816: descriptor-based position decoding |
| S7 | `cdmw/modding/mesh_pac_topology_builder.py` | 183: source quantization precision |
| S8 | `native/cdmw_mesh_core/src/owners/edit_topology_09.cpp` | 740: binding-distance collection |
| S9 | `cdmw/services/mesh_service_body_controls.py` | 81: source/skeleton eligibility; 119: temporary mapped view; 193: body-control generation |
