# CDMW test build readiness

- Plan ID: `BLD`
- Started: 2026-10-17 (Europe/Stockholm)
- Status: Completed; fresh portable test build verified.
- Baseline: `RR/independent-item-packages`, HEAD `591b53c607fa764c3163430c97e027517fe9eee3`.
- Shared completion log: `beta-progress/progress.md`.

## Goal and ownership

Finish the important packaging prerequisites identified by the readiness review and produce a fresh onefile test executable containing the completed beta fixes. The user requested this work after the review. Keep the current application version and preserve the prior portable executable as a rollback copy.

This task owns the local-research ignore rule, the current-source localization synchronization, its build evidence and the BLD entries in this folder. Preserve all existing translations and unrelated tracking edits. No game installation, archive/save mutation, publication, live input or shared REA/Ghidra ownership is part of this build.

The CDISO plan remains authoritative for native independent loading. Window/DPI still requires the physical equal-scaling monitor crossing. A successful package does not complete those tests or contracts.

## Required tasks

- [x] **BLD-BASE-01:** Verify the current source and build baseline, applicable instructions and retained work.
- [x] **BLD-L10N-01:** Synchronize generated localization against current source while retaining existing translations, then pass freshness and catalogue validation.
- [x] **BLD-EVIDENCE-01:** Classify the exact retained CDISO research directory as machine-local evidence, preserve its file inventory and pass the unchanged release preflight.
- [x] **BLD-PACKAGE-01:** Preserve the previous portable executable, run the normal onefile release build and pass its native, archive and packaged-startup checks.
- [x] **BLD-REVIEW-01:** Review retained isolation evidence, record exact remaining contracts, reconcile progress and save an isolated local commit for the completed changes.

## Baseline evidence

Localization freshness fails for the source manifest and all 14 catalogues, while language parity passes with 16,019 keys per catalogue. All 29 hashed Python release pins pass. Release preflight reports 415 unclassified research files and no generated-output blockers. The full research directory has 426 files and 313,189,622 bytes, including ignored evidence; its SHA-256 inventory is retained at `workspace/reports/cdmw-test-build-20261017T205143Z/research-inventory.json`.

The existing working tree has 17 modified tracked files: the CDISO plan, shared progress log and 15 localization files. The index is empty and there are no conflicts. The pre-existing localization diff is retained at `workspace/reports/cdmw-test-build-20261017T205143Z/preexisting-localization.patch`. All 423 untracked Git entries belong to the named CDISO investigation.

The current Rust Mesh Editor and C++ mesh-core executable/DLL hashes match their recorded successful verification. The portable executable under `dist/` has an October 14 timestamp. No CDMW application or mesh helper process was found during the build preparation check.

## Classification decision

The repository already keeps machine-local research and work products outside source control. Add only `/.work/tasks/2026-10-17-cditem-conflict-isolation/` to the ignore rules. Keep research files in place. Keep the release preflight logic and flags unchanged. Verify the exact rule with an actual research file, a similarly named sibling and unknown source outside the dated folder.

The packaging spec collects explicit application, resource and native paths. The scoped runtime/build search found no `.work/` dependency.

## Completion evidence

### BLD-EVIDENCE-01

The exact dated investigation rule passed `git check-ignore --no-index -v`: its research is ignored, while similarly named siblings and unknown source outside it remain visible. `python -B scripts/release_preflight.py` passed with no blockers. All 426 files and 313,189,622 bytes were rechecked against the retained SHA-256 inventory; no file was missing or changed. No release preflight implementation or flag was changed.

### BLD-L10N-01

Added the 29 current-source messages to English and translated them in the other 13 built-in languages, preserving all existing translations. Updated only semantic manifest changes rather than unrelated source-line movement. The French word `contribution` legitimately retains the source spelling and was added to the reviewed source-identical inventory. The first build attempt identified that missing inventory entry; its failed-attempt log is retained.

The second normal release build passed `scripts/generate_ui_localization_manifest.py --check` and `scripts/validate_ui_localization_catalogs.py`: 14 built-in languages, 16,048 keys each. It also passed all 29 hashed release dependency pins and release preflight before native compilation. Evidence is retained in `workspace/reports/cdmw-test-build-20261017T205143Z/build-attempt-02.log`.

### Remaining isolation and hardware work

The five retained R3 notes were reviewed without taking over REA/Ghidra or launching a game. They do not establish coherent additive ItemInfo registration with primary capacity, ordinal metadata, both lookup maps and durable backing. Required auxiliary ordinal ordering, repeat finalization, thread/allocator rules and later rematerialization also remain unproved. The selected headers replace primary storage; derived-vector growth and lookup callback registration do not admit new primary rows.

Private socket loading still lacks the writer of mesh member `+0x68`, the concrete manager dispatch and cache/descriptor lifetime. The examined PAPPT loop skips the third string payload. Its real `character/bin__/*.pappt` enumeration is a useful next lead, but provider visibility, ordering and duplicate publication still need evidence. Existing source continues to report `isolated_new_item.admitted: false` and `shared_file_composition: true`; no guard was relaxed.

All ten original pending CDISO tasks remain open in their owning plan. The WMDPI-06 equal-scaling physical monitor crossing also remains open. These are limits on feature completion and runtime proof, rather than blockers for testing the completed fixes in a rebuilt ordinary application.

### BLD-PACKAGE-01

Completed the normal `build_pyside6_app.ps1 -Mode onefile -BuildProfile release` run at 2026-10-17 21:11:57 UTC (23:11:57 Europe/Stockholm), exit code 0. The application version remains `0.11.0-alpha.23`.

- Native release helper builds and their provenance checks passed. The Rust Mesh Editor hash remains `b9772dfc50a4a4d59ef9e0bdac96bdff95e07351260ce132e81993112007db04`.
- Full archive backend: 41 checks passed; native archive-core and virtual-loader protocol tests also passed.
- Onefile archive: all 588 embedded members validated.
- Extracted texture helper self-test and full archive backend synthetic probe passed.
- Packaged startup reached `post_construction` for both `default` and `mesh_builder`; Rust Edit Mesh and bundled mesh-core/OpenImageIO resolution were verified.

The fresh executable is `dist/CrimsonDesertModWorkbench-0.11.0-alpha.23-windows-portable.exe`, 177,944,219 bytes, SHA-256 `58bf4848ffebea365a8a6e0b916cffdd0903fd6b3e4269a0a813f667f774a861`. The prior executable is retained at `workspace/reports/cdmw-test-build-20261017T205143Z/rollback/CrimsonDesertModWorkbench-0.11.0-alpha.23-before-test-build.exe`, 175,023,035 bytes, SHA-256 `fe24aefa05d712a205c7f14c02ee3acf4f8509d8857c1a33ff6b3421eccf5355`. Both files were rehashed after the build and match the recorded identities.

The build transcript and machine-readable outcome are `workspace/reports/cdmw-test-build-20261017T205143Z/build-attempt-02.log` and `build-attempt-02.json`. This proves the current working-tree package and its startup, including preserved pre-existing source metadata. It does not claim a full nonvisual suite, visible UI correctness or real-game isolation.

### BLD-REVIEW-01

The retained-contract review is recorded above. The isolated change contains 29 new entries in each catalogue, three existing manifest keys with semantic origin changes, the French reviewed-term entry, the dated ignore rule and this task's progress records. The localization index was projected from hash-verified baseline deltas; the pre-existing QApplication message and 1,131 informational manifest entry changes were kept outside that commit. Existing translations and other agents' CDISO tracking work remain preserved.

The projection and staged-blob verification are retained in `workspace/reports/cdmw-test-build-20261017T205143Z/owned-localization-inspection.json` and `owned-localization-staging.json`. The isolated local commit records this completed BLD plan. The tested executable was built from the current working tree, including the preserved pre-existing metadata.
