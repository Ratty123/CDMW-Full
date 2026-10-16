# Inspect File Formats update plan

- Plan ID: `FMT`
- Created: 2026-10-17 (Europe/Stockholm)
- Status: Planned. Implementation has not started.
- Project: `D:\CLAUDETEST\CDMW Full`
- Plan file: `beta-progress/inspect-file-formats-update-plan.md`
- Shared completion log: [progress.md](progress.md)
- Investigation baseline: branch `RR/independent-item-packages`, commit `afa050237092d1aa38ad0642ceabdd889da907da`.
- Checkout observed while preparing this plan: `f5abdaceaff93048a6a51414d5133e9f8c492cd2`. The relevant committed source paths had no changes from the investigation baseline. Other agents had active working-tree changes.

## Goal

Make Utilities > Inspect File Formats accurately describe the current CDMW workflows: what a format is used for, which operations are supported, where those operations are available, and what limits still apply.

Keep shipped archive inventory facts distinct from application import, export, editing, and package capabilities. A successful read or import must not imply unrestricted editing, exact game-format writing, or verified in-game support.

This document prepares the work requested after the inspection. Creating or reading it does not start implementation. Begin implementation when the user asks to start, using authorization already established in that session.

## Current handoff

- Completed: FMT-DOC-01 only (planning).
- Active task: None.
- Working agent: Unassigned.
- Claimed source files: None.
- Next task: FMT-BASE-01.
- Blockers: None identified for planning.
- Required tasks: FMT-BASE-01, FMT-MODEL-01, FMT-DATA-01, FMT-MESH-01, FMT-ROUTE-01, FMT-APP-01, FMT-FILTER-01, FMT-DOCS-01, FMT-TEST-01, and FMT-DONE-01.
- Evidence limit: The earlier inspection used source review, stored inventory, a small headless panel probe, and six synthetic test nodes. It did not validate visible appearance, scan an installed game, or prove in-game behavior.

## Completed preparation

- [x] **FMT-DOC-01 complete:** Created this plan with the investigation findings, acceptance criteria, stable task IDs, and shared completion rules.

Completion: 2026-10-17. Documentation only. Saved-content checks passed: 11 unique task IDs, only FMT-DOC-01 checked, one matching shared progress entry, all prior progress entries preserved, balanced fenced blocks, and 37 source references resolving to 36 existing files. The task diff passed whitespace checks. All implementation tasks remain unchecked; no application tests were run for this planning change.

## Shared progress rules for every agent

1. Before implementation, read the applicable project instructions, this plan, the shared `beta-progress/progress.md`, and current Git status. If that exact progress file is missing, create it before the first implementation change; otherwise reuse it.
2. The progress file belongs to all plans and agents in this folder. Preserve its existing entries and format. Do not clear, replace, reorder, rename, or fork it into a separate completion log.
3. Claim the active task and affected source files in Current handoff before editing. Coordinate overlapping files with other agents. Mesh Editor, independent-item/virtual-loader, Morph & Refit, and window/DPI work retain their own plans and owners.
4. Keep one authoritative completion checkbox per stable FMT task ID in this plan. Use smaller named subtasks if a task becomes too large to complete as one unit.
5. Mark a checkbox `[x]` only after its work and acceptance checks are complete. Add a Completion note with the date, outcome, exact relevant checks, evidence type, and remaining limits. Record the tested source revision when executable behavior is checked.
6. At the same checkpoint, append one short completed-work bullet to `progress.md`, using its existing format: `- YYYY-MM-DD | FMT-DATA-01 | Completed outcome; verified <check and result>.` Include a link to this plan where useful.
7. Read both files immediately before editing. Use the fresh SHA-256 and a targeted ThinkForge patch. If either file changed, reread and reapply only the intended change. Never overwrite newer shared work with a cached whole-file copy.
8. Check for the task ID before appending so retries do not create duplicate completions. The two files are separate writes: reread both afterward and confirm that the checkbox, evidence note, and progress entry agree. Reconcile an interrupted checkpoint on resume after checking its evidence.
9. Keep active work, ownership, partial results, blockers, and next actions in this plan. Keep the shared log as a simple list of completed work. Unperformed or deferred tasks remain unchecked with an explanation here.
10. If new evidence invalidates a completed task, reopen its checkbox and explain why. Append a dated correction referring to the original progress entry while preserving the history.
11. Update both files throughout implementation and before each handoff. Planning, a source review, and a passing unrelated test are not completed fixes.
12. Follow current repository commit rules. Inspect the latest index before staging, stage only task-owned paths or hunks, and coordinate shared Git index operations. Never include another agent's pending work to make a commit easier.

## Scope and design boundaries

- Keep the Format Explorer lightweight and read-only. Its display must not launch conversion, scan game assets, or perform archive writes.
- Preserve archive schema consumers, versioning, stored inventory counts, and report meanings. `schemas/archive_content_capabilities.v1.json` also serves runtime consumers outside the panel.
- Prefer existing capability owners for operation rules. Add only the smallest explicit metadata needed for presentation; avoid creating a second competing source of authoring policy.
- Correct the catalogue and its explanations without widening parsers, writer gates, supported game layouts, or mesh authoring permissions.
- Retain external-tool prerequisites, experimental labels, version limits, output types, and workflow-managed editing constraints.
- This task does not implement a new material editor, mesh authoring operation, file codec, package version, or archive mutation path. Record a separate issue if a missing workflow needs feature work.
- Use focused checks from the current `docs/test-matrix.md`. Documentation-only preparation needs saved-content and diff checks, not the application suite.
- No native build, broad suite, visible UI, real-game mutation, packaging, release, or publication is part of this planning task. Follow the applicable instructions and existing session authorization if later work requires any of them.

## Recorded inspection findings

These are observations from the investigation baseline. Reconfirm the relevant owners before changing metadata; another agent may have updated the feature in the meantime. Source references S1-S14 are listed below.

| Area | Recorded state | Required treatment |
| --- | --- | --- |
| PATHC | The catalogue says an unmatched shipped DDS header is refused. `register_dds` already appends a compatible header and derives raw mip block information, subject to validation and capacity limits. | Refresh evidence and remaining restrictions; retain real collision-table and unsupported-layout limits. Do not invent an in-game result. S3, S5. |
| PALOC | The evidence describes the flat layout but omits the supported version-0, 512-byte-header LZ4 container and preservation behavior. | Document both layouts, strict version handling, and actual edit/round-trip limits. S3, S6. |
| Sequence sidecars | `.paseq`, `.paseqc`, and `.pastage` are displayed as read-only, while Browse Archives offers validated fixed-size string edits. `.pabgh` supports validated row editing but has no mapped tool. | Describe constrained edits and their copied output; keep full cutscene/event authoring unavailable. Check what the shared manifest's write field means before changing it. S3, S7. |
| Mesh formats | `.pac` and `.pam` have empty remaining-work text, which the panel renders as "Nothing outstanding." Current exact-authoring policy still blocks or leaves operations unproven; LOD and Free Edit output rules differ. | Show operation/output limits and use neutral wording when no note is recorded. Keep game-format authoring distinct from rebuilding a working mesh. S1-S3, S8. |
| Interchange formats | FBX status and GLB/glTF/OBJ/DAE editing destinations lag current import/export workflows. FBX import requires a configured Blender route; DAE import does not establish DAE export. | Record operation-specific support and prerequisites. Do not label external conversion as native decoding or imply unsupported exports. S3, S8, S9. |
| Application packages | `.cditem` is absent from all 141 catalogue rows despite Create New Item, Independent Items, and Virtual Loader workflows. | Add explicit application-package coverage without inventing archive inventory counts. Recheck producer/reader versions and experimental limits before writing claims. S10. |
| Effect and managed formats | `.pae` and `.paem` have constrained support but no tool mapping. Some related formats are modified through Create New Item workflows. | Link only verified workflows and describe bounded, workflow-managed operations. A writer helper alone does not prove a standalone editor exists. S1, S11. |
| Material sidecars | Structured material-editor code exists for `.pac_xml`/`.pami`, but the inspection did not establish a reachable UI entry point. | Verify navigation first. Do not add an assumed editor link; document an accurate available route or record a separate UI follow-up. S12. |
| Filtering | The default panel showed 87 shipped rows; including non-shipped rows showed 141. Combining that option with "Only what I can edit" showed 35 and excluded zero-count GLB/OBJ because `moddable` also requires `files > 0`. | Define how presence and supported editing should interact, then implement and test that contract. Import/export alone must not imply editable. S1, S2. |
| Maintenance | Stored manifest progress totals matched the generator, but the read-only report check failed because the checked-in report text/layout differed. The feature guide refers to a missing dedicated test file. | Synchronize the generator and intended readable report, and update test/documentation references. Do not describe the report-layout drift as incorrect inventory totals. S13, S14. |

### Baseline validation already performed

- The smallest `FormatExplorerTab` was constructed with an offscreen Qt platform and a callback, without starting the full application or scanning archives.
- The probe recorded the 87/141/35 filter results above, checked detail selection for ten formats, and confirmed that a `.wem` link emitted the `archive_browser` destination.
- Six existing synthetic test nodes passed: two PATHC cases, three PALOC container cases, and one transactional structured-sidecar case. Exact nodes are listed in Validation.
- The default invocation of `tools/report_format_decode_progress.py` exited 1 for report text drift. Stored `progress` values matched the computed summary.
- These results are historical evidence, not fresh validation of future changes. Reuse unchanged proof where applicable and rerun the affected checks when the contract changes.

## Required tasks

### FMT-BASE-01: Refresh the starting point and coordinate ownership

- [ ] **FMT-BASE-01 complete:** The current source baseline, overlapping work, task ownership, and focused checks are recorded.

Work: Read current instructions, this plan, shared progress, Git status, and the relevant owners. Compare the findings against current source and pending changes. Coordinate with agents changing Mesh Editor or `.cditem` workflows before documenting their capabilities.

Acceptance: Every correction has a current source owner and evidence. Record obsolete findings instead of implementing them. Confirm the shared log exists, and claim the next task and files in Current handoff.

Completion: Pending.

### FMT-MODEL-01: Define the catalogue's capability and presence contract

- [ ] **FMT-MODEL-01 complete:** The model distinguishes inventory presence, supported operations, output limits, and application-only formats without changing unrelated archive contracts.

Depends on: FMT-BASE-01.

Work: Inspect the manifest's Python and .NET consumers and the existing domain capability owners. Define display meanings for read/inspect, bounded edit, import, export, and package support. Identify whether evidence belongs in archive metadata, existing application metadata, or a small presentation-specific addition. Reuse existing policy for mesh operation status.

Acceptance: Archive counts and backend field meanings are preserved. Application-only formats have an explicit kind/origin and no invented shipped-file count. A format can be importable without being editable or exportable. The chosen design and filter truth table are recorded here before dependent edits.

Completion: Pending.

### FMT-DATA-01: Correct known format evidence and bounded editing claims

- [ ] **FMT-DATA-01 complete:** PATHC, PALOC, sequence-sidecar, and PABGH descriptions match current supported operations and remaining restrictions.

Depends on: FMT-MODEL-01.

Work: Correct the findings above using the current PATHC, PALOC, and structured-sidecar owners. Keep source-level proof distinct from historical user or in-game validation. Describe sequence string edits and PABGH row edits as bounded operations producing an edited copy. Change shared schema values only when their documented meaning and consumers justify the change.

Acceptance: PATHC no longer claims every new DDS header shape is refused. PALOC describes the supported container version and preserved bytes accurately. Sidecar descriptions expose available constrained edits while retaining unavailable full authoring. Inventory and unrelated decoder/writer behavior are unchanged.

Completion: Pending.

### FMT-MESH-01: Make mesh and interchange limits accurate

- [ ] **FMT-MESH-01 complete:** Mesh and interchange rows state their supported operations, prerequisites, and output limits without overstating authoring.

Depends on: FMT-MODEL-01.

Work: Derive descriptions from the current authoring capability rules and import/export routes. Cover PAC/PAM/PAMLOD LOD restrictions, blocked/unproven exact operations, and the output of supported Free Edit workflows. Reconcile FBX, GLB, glTF, OBJ, and DAE claims. Replace the unconditional "Nothing outstanding." fallback with neutral language that does not infer complete support from missing metadata.

Acceptance: Exact game-format edits and new working-mesh output are distinguishable. FBX import names its Blender prerequisite. DAE import does not imply DAE export. Empty remaining text cannot claim all limitations are resolved. Existing writer gates remain authoritative and unchanged.

Completion: Pending.

### FMT-ROUTE-01: Verify and update usable workflow destinations

- [ ] **FMT-ROUTE-01 complete:** Each added or changed destination corresponds to an available workflow and states any prerequisite.

Depends on: FMT-DATA-01 and FMT-MESH-01.

Work: Verify the actual shell tool keys and UI entry points for structured sidecars, interchange formats, and Create New Item effect workflows. Cover `.pabgh`, `.pae`, and `.paem`; verify any `.pappt`, `.pathc`, or `.pabgb` route before advertising it. Investigate material-sidecar reachability without assuming that an existing dialog is exposed.

Acceptance: A link opens the correct tool, and its text explains any required archive selection, experimental mode, configured converter, or other context. A root-tab callback alone is not proof of a usable action. Workflow-managed edits are not described as unrestricted standalone editing. Record material-route evidence or its separate follow-up and accurate fallback here.

Completion: Pending.

### FMT-APP-01: Represent current application and package formats

- [ ] **FMT-APP-01 complete:** Optional application-format coverage includes the current `.cditem` and mesh interchange workflows with accurate provenance and version limits.

Depends on: FMT-MODEL-01 and the current package/workflow baseline from FMT-BASE-01.

Work: Apply the chosen presentation model to app-supported formats outside the shipped archive inventory. Recheck `.cditem` export version, accepted reader versions, experimental variants, and unknown-version handling against the current package service and visible workflows. Add only verified routes to Create New Item, Independent Items, or Virtual Loader.

Acceptance: `.cditem` is discoverable in the appropriate optional view, identified as an application package, and does not inflate game archive counts. Do not promise experimental v2 output where a producer still writes v1. Describe the actual supported versions and limitations without changing the package codec. Mesh interchange rows use the operations established in FMT-MESH-01.

Completion: Pending.

### FMT-FILTER-01: Implement clear visibility, search, and detail behavior

- [ ] **FMT-FILTER-01 complete:** The panel follows the agreed presence/editing contract and keeps search, detail selection, and labels consistent.

Depends on: FMT-MODEL-01, FMT-ROUTE-01, and FMT-APP-01.

Work: Preserve the default shipped-inventory view. Provide an explicit way to include application and non-shipped formats. Separate the presence predicate from supported editing where the agreed contract requires it. Explain that file counts come from stored inventory. Ensure filtering and selection refresh the correct detail and route.

Acceptance: Test every filter combination, including zero-count editable formats, import-only formats, read-only formats, and application packages. The optional view plus editable filter retains entries that actually support the defined editing operation. Unsupported operations do not qualify merely because import or export exists. Search and empty results do not leave stale details. Default inventory totals remain derived from the existing inventory.

Completion: Pending.

### FMT-DOCS-01: Synchronize documentation, generated reports, and labels

- [ ] **FMT-DOCS-01 complete:** The feature guide, capability report, localization metadata, and user-visible change note match the implemented behavior.

Depends on: FMT-DATA-01 through FMT-FILTER-01.

Work: Update `docs/features/format-explorer.md`, including accurate test references, inventory origin, optional app coverage, operation meanings, and remaining limits. Reconcile the report generator with the intended readable report layout, then regenerate the report and any changed stored summary using its actual supported command. Update affected localization keys/catalogues and regenerate the localization manifest only when keys, paths, sinks, or exclusions change. Add or update the relevant Unreleased changelog entry for the implemented user-visible change.

Acceptance: The read-only format report check succeeds and preserves understandable long limitation notes. Report totals agree with the actual archive entries. Localization checks match current instructions. Test references point to real tests. Release notes describe the user outcome and keep experimental/compatibility limits; no version bump.

Completion: Pending.

### FMT-TEST-01: Add and run focused behavior coverage

- [ ] **FMT-TEST-01 complete:** Targeted tests prove the changed catalogue, panel, and maintenance behavior, with evidence and limits recorded.

Depends on: Implement affected checks alongside FMT-MODEL-01 through FMT-DOCS-01; complete this task after their results agree.

Work: Use the existing test structure where suitable; add a small dedicated catalogue/panel test module only if needed. Cover operation semantics, filter combinations, verified link behavior and prerequisites, non-stale details, package/version display, and report freshness. Use the smallest real headless panel construction when executable Qt wiring changes. Do not rely solely on source-string assertions or tests that restate the implementation.

Acceptance: The exact affected checks pass under the project virtualenv, with pytest temporary data outside the repository. Record the test command, result, and source revision. Existing focused proof is reused where unchanged; unrelated failures are isolated and do not trigger broad test runs.

Completion: Pending.

### FMT-DONE-01: Finish the review and synchronize the handoff

- [ ] **FMT-DONE-01 complete:** Every required task is complete, claims agree with current source, and the plan and shared log are synchronized.

Depends on: All preceding implementation tasks.

Work: Recheck capabilities that concurrent agents changed, inspect task-owned diffs and generated changes, verify inventory and archive consumer compatibility, and confirm every completed task has one matching progress entry. Update Current handoff and status, retain source references and validation limits, and save an isolated local commit under current repository instructions.

Acceptance: No stale or unsupported claim remains among the scoped findings. No unrelated work is staged or overwritten. All required checkboxes and completion evidence are accurate, and `progress.md` remains a short shared completion list. Report any unresolved item openly instead of declaring the plan complete.

Completion: Pending.

## Validation

Use current commands from `docs/test-matrix.md`; this section identifies the relevant proof, not a request to run broad gates. Run tests with `.venv/Scripts/python.exe`, disable pytest cache creation when instructed, and allocate a unique pytest base temporary directory under the host's temporary directory.

The prior six passing synthetic nodes were:

```text
tests/test_pathc_format.py::PathcTests::test_register_a_dds_by_its_own_header
tests/test_pathc_format.py::PathcTests::test_dx10_formats_never_share_a_descriptor
tests/test_paloc_container.py::test_container_round_trip_preserves_original_compressed_bytes
tests/test_paloc_container.py::test_text_edits_and_added_names_keep_container_and_update_sizes
tests/test_paloc_container.py::test_malformed_containers_are_refused[version]
tests/test_structured_sidecar_edit_async.py::test_structured_sidecar_load_and_write_are_cancellable_and_transactional
```

Additional validation is selected by the changed contract:

- Catalogue behavior: discrete operations, display text, source kind, inventory preservation, and package version/prerequisite explanations.
- Panel behavior: all filter combinations, search, selection refresh, empty results, and actual tool callback routing with usable action context.
- Shared schema: the smallest existing contract checks for each consumer affected by a field or identifier change. Preserve the archive inventory; no new game scan is implied.
- Format report: `.venv/Scripts/python.exe -B tools/report_format_decode_progress.py` is the current read-only check. At the investigation baseline this script supported `--write`, not `--check`; verify its current CLI before invoking it. Regenerate only after agreeing the intended output and reviewing the diff.
- Localization: use the focused manifest `--check` from project instructions when applicable, and regenerate with `--write` only for meaningful key/path/sink changes.
- Planning-only verification: confirm unique FMT checkbox IDs, only FMT-DOC-01 checked, exactly one matching planning progress entry, preservation of prior shared entries, valid local source references, and a clean task diff.

These checks provide source and synthetic/headless evidence. They do not establish visible appearance or game compatibility. Record that distinction in the final implementation handoff.

## Source map

Paths below are relative to `D:\CLAUDETEST\CDMW Full`. They identify the inspection owners; use current symbols rather than stale line numbers.

| ID | Owning files and purpose |
| --- | --- |
| S1 | `tools/format_explorer/catalogue.py`: manifest loading, manual tool mapping, operation words, `moddable`, filtering, and inventory headline. |
| S2 | `tools/format_explorer/tab.py` and `cdmw/ui/shell/tool_tabs.py`: panel construction, filter/selection behavior, detail fallback, tool links, and shell activation. |
| S3 | `schemas/archive_content_capabilities.v1.json` and `schemas/archive_extension_inventory.json`: archive capability facts and stored counts. |
| S4 | `cdmw/domain/archives/content_capabilities.py` and `tools/dotnet_archive_backend/src/Cdmw.Archive.Content/ArchiveContentRegistry.cs`: archive runtime consumers to protect when metadata contracts change. |
| S5 | `cdmw/core/pathc_format.py`, `cdmw/services/new_item_planning.py`, `cdmw/services/new_item_mounted_base.py`, and `cdmw/services/virtual_loader_composition.py`: header registration and actual workflow call sites. |
| S6 | `cdmw/core/paloc_format.py`: flat/container parsing, strict version handling, and preservation during encoding. |
| S7 | `cdmw/ui/archive_browser/actions.py`, `cdmw/ui/archive_browser/binary_sidecar_actions.py`, and `cdmw/services/structured_sidecar_edit_service.py`: visible structured-sidecar action and bounded copy writes. |
| S8 | `cdmw/domain/mesh/authoring_capability.py`: exact authoring, LOD, operation, Free Edit, and output policy. |
| S9 | `cdmw/services/fbx_blender_conversion.py`, `cdmw/modding/mesh_exporter.py`, `cdmw/ui/mesh_editor/replacement_flow.py`, and `cdmw/ui/archive_browser/actions.py`: current interchange import/export routes. |
| S10 | `cdmw/services/independent_item_package.py`, `cdmw/ui/new_item/panels_output.py`, `cdmw/ui/new_item/independent_items_page.py`, and `cdmw/ui/new_item/virtual_loader_page.py`: package versions and visible create/import/load routes. |
| S11 | `cdmw/services/new_item_effect_planning.py` and `cdmw/ui/new_item/panels_perks.py`: bounded effect/emitter workflows and limitations. |
| S12 | `cdmw/ui/archive_browser/material_sidecar_actions.py`, `cdmw/ui/archive_browser/material_sidecar_document_controller.py`, and `cdmw/ui/archive_browser/material_sidecar_editor_dialog.py`: existing material editor code; reachable navigation still needs verification. |
| S13 | `tools/report_format_decode_progress.py`, `docs/features/format-decode-progress.md`, and `docs/features/format-explorer.md`: generated/report contract and feature guidance. |
| S14 | `tests/test_compact_shell.py`, `tests/test_localization_catalog_contracts.py`, `tests/test_pathc_format.py`, `tests/test_paloc_container.py`, and `tests/test_structured_sidecar_edit_async.py`: existing relevant proof; select exact cases instead of broad suites. |

## Definition of done

The feature accurately represents the current scoped archive and application workflows, gives verified destinations and honest limits, preserves inventory/backend contracts, and passes the focused checks for its changes. Every required task is checked only with evidence and a matching shared progress entry. Final reporting states any remaining limitation and the type of validation performed.

Planning is complete when this document and its FMT-DOC-01 progress entry are saved and verified. Implementation remains pending until the user starts the work.
