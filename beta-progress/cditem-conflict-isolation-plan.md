# .cditem Conflict Isolation and Independent Loading Plan

- Plan ID: CDISO
- Status: In progress. Implementation authorized on 2026-10-17; native feasibility gates remain open.
- Created: 2026-10-17, Europe/Stockholm.
- Project: D:\CLAUDETEST\CDMW Full
- Game reference: C:\games\Steam\steamapps\common\Crimson Desert
- Plan file: D:\CLAUDETEST\CDMW Full\beta-progress\cditem-conflict-isolation-plan.md
- Completion log: [progress.md](progress.md)
- Reviewed branch: RR/independent-item-packages
- Reviewed HEAD: d4b38e5082d4f9b4b4cce14f9ee2ecdb37994aaf, with concurrent uncommitted work.
- Current authorization: The user authorizes completing this plan, implementation, focused verification and controlled game tests without routine permission questions. The user now operates menus/gameplay and explicitly authorizes this chat to close or force-close Crimson Desert after coordinating any active measurement with its owning chat. Accepted save/game-data/reinstall risk remains in force; archives are not required by the independent route. Keep feature/progress and Astra/Pro evidence synchronized.

## Goal

Make supported new-item .cditem packages independent at every relevant ownership boundary: item identity, auxiliary records, game-visible resource paths, referenced resources, runtime registration, and saved identity.

The intended end state is that adding, updating, disabling, or removing item A does not overwrite another item's files or records, change the donor stock item, or require rebuilding and merging shared game files with other mods. Each package supplies its own item definitions and resources. A supported loader registers those contributions while preserving the definitions supplied by the game and other supported mods.

This plan preserves the full goal. Better conflict detection and automatic shared-table composition are useful existing protections, but do not by themselves complete the requirement to load without shared-file merging.

A loader-owned profile or manifest is permitted. The no-merge condition covers shared game data files, shared archive replacements, and generated compatibility patches.

The game can still have central in-memory registries. Unique, independently owned entries in those registries are compatible with this goal. Replacing one shared on-disk or virtual table with a combined table is a different mechanism and does not meet the final acceptance condition.

## What independence means

| Boundary | Required behavior |
| --- | --- |
| Package | Permanent UUID and stable local object symbols; update preserves identity and duplication creates a new one. |
| Game identity | Distinct retained numeric keys, names, localisation identities, and other registry keys for each owned object. |
| Resource | Separate game-visible paths and identities for mutable item resources, including embedded and implicit references. |
| Dependency | Every remaining borrowed resource or shared game integration is identified and justified. An unresolved edge prevents an independence claim. |
| Installation | Package A can be added or removed without overwriting B's contribution or editing original game/mod files. |
| Runtime | Separate item definitions and assets become usable without publishing combined replacement shared game data files or archive carriers. |
| Lifecycle | Updates, restart, removal, and save reload preserve the intended identity and do not make another package depend on a removed contributor. |

For the admitted item graph, independence includes stable intended appearance and behavior when a foreign mod changes a detached donor. Shared engine services remain platform requirements. Any borrowed item resource must be disclosed; it prevents a fully self-contained claim for that resource boundary.

Identical immutable bytes may still be reused internally after independent validation. Memory or storage deduplication must not merge logical ownership, mutable runtime objects, or game-visible resource identities.

The .cditem container also supports intentional edits to existing content, such as item.fields and texture.replace. Those operations cannot promise that contradictory edits to the same stock field or texture both take effect. Preserve those modules, but distinguish them from an isolated new-item contribution. A filename extension alone is not an isolation guarantee. Define a derived isolated-new-item admission result that rejects stock mutations, undeclared shared writes, and silent composition fallbacks. Add package metadata only when a concrete loader/consumer contract requires it.

Likewise, a package cannot control arbitrary native code, a foreign loader that replaces its hooks, or another tool that deliberately claims the same game identity. The enforceable boundary is explicit ownership and refusal of incompatible inputs within the supported loading route. Never silently renumber saved identities, select an arbitrary winning provider, or hide a missing feature to make a conflict disappear.

## Execution companion, 2026-10-18

For the user-requested coding, reverse engineering and unattended device-test workflow, start with [cditem-execution-goal.md](cditem-execution-goal.md). It adds process ownership, mouse/E menu automation, disposable-save testing, evidence, review and final-build delivery around the existing CDISO tasks.

[cditem-astra-pro-handoff.md](cditem-astra-pro-handoff.md) retains the open native questions and the required later-review format. Its initial entries are inherited research, not exhausted Sol attempts.

This feature plan remains authoritative for feature acceptance and completion. The R3 release section below remains a historical ownership record; refresh current ownership before resuming. Creating the execution documents adds no new implementation or game-test proof.

## Required progress tracking

These rules apply to every agent working from this plan.

1. Before the first implementation change, read this plan and progress.md. Create progress.md in this folder if it is missing.
2. Preserve the existing shared log and every other plan's entries. Never recreate or replace the log to start this work.
3. Use the stable CDISO task IDs below in both files. Each task has one authoritative checkbox here.
4. Mark a task [x] only after its acceptance conditions and relevant focused checks pass. Add a Completion note under that task with date, result, and evidence.
5. Append a short dated completion entry to progress.md in the same work session. Keep the log a simple chronological list of completed work.
6. Keep partial work, ownership claims, blockers, research limits, and next actions in Current handoff. Do not record unfinished implementation as completed.
7. Re-read the shared log immediately before changing it. Use a fresh content digest and a narrow append. If another agent has changed the file, read the new content and retry without discarding their work.
8. Split a task into stable subtasks before reporting a partial result as complete. A completed research task does not imply the corresponding implementation or game proof is complete.
9. If later evidence invalidates a completion, reopen its checkbox, correct its own completion entry, and explain the reason in Current handoff.
10. At handoff, check that every completed CDISO ID appears in both documents and that no pending task has a completion entry.

Completion-entry format:

    - YYYY-MM-DD | CDISO-OWN-01 | Isolated the supported resource graph; matching reference and ownership checks passed.

That line is a format example, not a completed task.

## Current handoff

### CDRUN execution checkpoint, 2026-10-18

Verified portable stock delivery: normal release at embedded revision `ce0ab5f5a369b85c8dec14cdc32d48b496b21598` is 175,520,265 bytes, SHA-256 `5f3483b898de1a9edd0cae38590fac9139c92270768ba84a7757545e20c9148b`. All 586 members, twelve Python joins, fourteen catalogues, four native payloads, default/Mesh startup and four actual safe portable probes pass. The actual delivered EXE completed exact copiedslot0 load, real forest/world/HUD observation and confirmed normal exit:7 successful actions,13/13 released scopes, zero action/cleanup failures. Three no-input image pauses and the earlier cancelled focus refusal remain retained; each decision was Root-inspected, so this is not a pause-free or general unattended classifier claim. Independent receipt/pixel/policy/cleanup audits pass. All 26 originals and metadata were exact before Cloud; all 4 setup files and foreign runtime/bootstrap remain original. Cloud is persisted ON/Up-to-date and Steam minimized; original payloads/inventory still match after 8 normal file timestamp deltas/0 directory deltas, without repair. Full 234-input/151,455,090,976-byte afterguard passes. `CDRUN-DELIVERY-01C` is complete; RH-01/RH-02/RH-03/RH-05, all 10 original feature parents and full native scenario/review/T20 delivery remain open. Passive 13–22 findings and actual attempts are in the existing Astra/Pro handoff. Evidence: `workspace/reports/cditem-execution/20261018-packaged-runner/`, `20261018-packaged-baseline-2/` and the existing native-review folder. The full goal remains active. The later idle SDK was closed before target open/import/native query when a new foreign owner acquired the project. Passive 24 proves default S+0x10 true is a refresh return, not completion. Those actual outcomes and restart conditions are retained.

The CURRENT complete restart ledger remains native batch32: `workspace/reports/cditem-execution/20261018-native-review/batch32-native-lifetime-initialization/provider/rea-complete-final-ledger.json`, 96,845,868 bytes/SHA-256 `5dd3ff2566281ddaaaeb7d8b76b6dc6c2ca910c1ebca4b2bbc6b8cee047637b1`,1,292 records/97 unknown revisions/16 identities. B44/Manual52 now proves actual numeric lookup on the exact frozen376,320-byte ASI/SHA `e1e9606d81bb6c9c6948f93f03eb830b93bd103c4a04faafbb9f498dbe88e41d`: game3892/startup thread10248, callback/original return verified,6816 primary entries, four stock keys/ordinals/names resolved and four false/FFFF results. The9401-byte result/SHA `b90bf57f4063953426a17c3e981e7c1f29aa5785a67c6d1858eb6f20c55e65b7` re-decodes exactly from retained native bytes. False resolution remains distinct from unused key, as B46 proves. Sequential header equality is not atomicity/readiness/admission. The user closed normally; first restoration hit WinError5. A later unchanged supported cleanup succeeded, with fresh four-file original hash matches, preserved Loadouts198/meta and quiet game/host/profile transaction. The795-byte restoration receipt/SHA `d2f271dab5f18e8c57cb20d695b139cc4861287ef3a623e9394859c9d9e66098` and all initial failure material are retained. B52 adds bounded recognized Windows-lock retries with all-target ownership and quiet checks; the complete23 recovery tests pass. No permission bypass, game control or extra live run occurred during cleanup. B48 declared-count validation remains committed with31 focused tests/21 subtests and real retained-copy checks; B49 resource mode/helper fixture remains15 cases with actual native parsing unexecuted. B50 captures complete typed record construction/Bool decode/native release source,7704 bytes/1772 instructions: materializer returns status pointer and ignores decode Bool; decoder receiver is Reader, and name-map values are record numeric keys. B51 now passes actual native allocation/constructor/Bool decode/release for the real donor twice and existing package base1990055/perks1990056/57/58 on game18460/startup thread6452. All six have exact IDs/names/cursors, native release pointer-clear and36 joined steps, with zero issues. The private396,800-byte ASI/SHA `8ed057340cd2bb394979b0b18bee74bf70b033b284a34624a090e8aba951a4ca` passes240 isolated C++ checks,49 decoder tests,21 final manual tests and no-session/state0. All40 frozen candidate pins verify. Normal closure/restoration passed; fresh original four hashes/mtimes, preserved Loadouts198/meta and quiet game/host/transaction are recorded in `batch51-unpublished-item-decode/live-result-audit.json`. Restoration795 bytes/SHA `8952439e456bdd51f84dd33e6aaf8e62efdf8614369c48e6583c468fe6c40cab`. Shared slot explicitly released. This is unpublished-record proof; coherent registration/private getter/backing/resource/first-ownership contracts remain open. User owns game/UI input. RH-01 coherent primary/aux/map publication, RH-02 private getter/backing/name/rematerialization, RH-03 private resource visibility/lifetime and RH-05 first saved ownership remain open. The public175,520,265-byte ce0ab5f5 portable/SHA `5f3483b898de1a9edd0cae38590fac9139c92270768ba84a7757545e20c9148b` remains unchanged and excludes these latest Python fixes/private prototypes. Native admission=false; all ten feature/full scenario/review/T20 parents remain open.

B53 completes the selected native cache/name ABI: 677 physical bytes/189 instructions;7,880 isolated checks/124 genuine maintenance calls/five reverse callbacks pass with explicit clock/release helpers. Exact maintenance is WORD phase+60/modulo60, QWORD expiry<=clock and separate body-cache release. A conservative total-count ceiling65476 avoids scan wrap for all phases; unsafe65535/phase0 cycles in a bounded arithmetic model and was not executed natively. Reverse ABI is owner RCX/key-pointer RDX/output-pointer R8, with direct unchecked resident-name borrowing and existing-output precedence. Capture/fixture pins and the required private getter/stable-name/detour-unwind implementation are in `batch53-private-row-cache-lifetime/findings.md`. No game/provider/install operation occurred; Fast Start owns the peer measurement slot after Loadouts200 installation. Native admission=false; original feature/full scenario/review/T20 parents remain open.

B54 implements private getter/stable-name routing with exact full native entry guards, pre-execution14-byte patches and process-lifetime registered unwind storage.152 isolated checks pass, including14 Windows virtual-unwind boundary cases, two actual caught prefix traps, native stock passthrough, cold owned-name return and same-entry rematerialization after native maintenance with explicit fixture helpers. Initial FF25 resume failed actual unwind at getter+14; preserved first code/binary/log and corrected R11 transfer now pass. Engine allocation/decode is not executed in this B54 fixture; the next cache implementation must combine B51 actual native operations with immutable backing, checked publication and caller serialization. No game/install/provider action or new manual test occurred. Full details/attempts are in `batch54-private-getter-name-routing/findings.md`; native admission=false and original feature/T20 parents stay open.

B55 implements checked private cache ownership behind the typed routing callback: native Bool/cursor/identity gates before slot/expiry publication, resident hits, immutable-backing re-decode after eviction, all-slot cleanup preflight and stop/quarantine on uncertain ownership.214 checks/24 isolated cases pass, including an actual native constructor/decoder false path and native maintenance with explicit engine helpers. A release-reentry reproducer caught retrieval of a dying record; the busy guard/stop-before-sibling fix passes and original code/EXE/log remain retained. Real engine allocation/successful decode/destructor/game cache integration is still pending for this cache; B51 remains its separate positive ABI proof. Next is the exact integrated early-startup diagnostic; no new game/install/provider action occurred. See `batch55-checked-native-cache/findings.md`; native admission/full original feature/T20 parents remain open.

B56 freezes the integrated private getter/name/cache/real-maintenance diagnostic at412,672 bytes/SHA `0045b6ff4c16f69594392751ab70974a7708265392004a7a1bf3f1ce05898359`. Six isolated C++ modes/1,039 checks,133 strict decoder and29 manual-caller tests pass; exact ASI no-session/state0 and all73 candidate pins verify. The fixture executes actual native lookup/maintenance with explicit construction helpers; real engine construction through this integrated cache is not yet game-tested. The four existing private rows must each show checked cold decode/hit, stable owned names, native eviction, cold name without construction, rematerialization and explicit release with90 exact steps. Occupied keys includingFFFF, virtual-ordinal conflicts, source/hook drift and release reentry refuse. Typed/malformed result refusals retain raw evidence and allow cleanup. The new manual launcher is `20261018-integrated-cache-manual/CDItem cache test.cmd`; its21,069-byte manifest/SHA `4effa768d0d93aa75cfe324e0c1f995b86df1e363aa605db1a10499b154580f2` binds73 files. Fast Start owns the game/install/measurement/provider lane and has been sent the ready-candidate handoff request; no new game/install/close/input/provider operation occurred. The human now explicitly authorizes game closure/force-closure after chat coordination without another permission question. RH-01 coherent central admission, RH-02 ordinary reader lifetime, RH-03 resources and RH-05 inventory/persistence remain open; native admission/full feature/T20 remain false/open. Evidence/attempts: `batch56-integrated-private-cache/findings.md`.

B49 continuation qualifies eight complete resource roots,6,581 physical bytes/1,728 instructions. Its isolated fixture passes15 cases/15 calls of the unchanged native initializer using explicit PAPGT/availability/PAMT/diagnostic test helpers and owned empty names. Exact mode1 is required: modes2/255 can return success without checking/loading any group; mode1 with all255 optional groups absent can also succeed without a load call. A later mandatory or PAMT failure follows earlier successful helper calls. Selected fixture paths preserve source/input bytes/LastError and do not dereference guarded tuple/S pointers; actual engine parsing/allocation/context and resource loading are unexecuted. Constructor/global-byte and PAPGT TLS/context+808 writes rule out assuming off-list preparation is wholly private. Findings, exact executable/source pins and unresolved publication/context/coverage questions are in `workspace/reports/cditem-execution/20261018-native-review/batch49-resource-mode1-abi/`. B44/Manual52 live lookup is verified and original setup restored; user owns game input. No game/install/provider operation or public rebuild occurred. Canonical ledger remains B32, native admission=false and all original native feature/scenario/review/delivery parents remain open.

Passive native batches 25–29 resolve both constructed context+0x48 slots to the same constant-true leaf, qualify the complete PA named-pipe update and its actual S+0x138 callback dispatcher, and join S+0x1f0 to Enter/LeaveCriticalSection plus deleting cleanup. The registered zero-tag raw-I callback selects a direct call; no index lifetime lease or retirement participation in that critical section is established. The next questions are the concrete I+8 association and actual reader/retirement joins, not another decode of the solved virtual slots or141371a40 local drain. The literal-encoding helper failure and read-only lookup errors are retained. A fresh native census finds a different foreign provider lineage still owning the project; no new Root SDK or native query was started. All171 packaged source pins, the delivered ce0ab5f5 portable and the complete canonical ledger remain exact. RH-01/RH-02/RH-03/RH-05 and all original open feature/native parents remain open. Reports and the concrete restart packet are retained under `workspace/reports/cditem-execution/20261018-native-review/batch25-default-context-slot48/` through `batch29-pa-lock-operations/`.

Passive native batches 5–9 remain outside the unchanged canonical ledger. The after-all-successful-+0x60 point at `0x14fa45af1` remains conditional; actual completion callbacks, whole-startup failure/readiness and native admission remain open. The resource-only witness completed in the copied stock world: exact read-only menu/world replays confirm one mode 1 backend, with world count=capacity=1 and no observed spare slot. Branch 0 preparation exposes context/index/callback references before provider insertion, so off-list construction alone does not withhold publication. Deleting-destructor/lazy-group-load qualification now proves a local drain, while external callback participation and the index+8 concrete child remain unresolved. The observer invoked no engine function and wrote no game memory. The fifth disposable cycle ended normally; all 26 originals and metadata were restored before Cloud ON, all 4 setup files and foreign runtime/bootstrap remain original, and the game/session host are gone. Cloud is persisted ON/Up-to-date and Steam returned to minimized library; original payloads/inventory still match after 7 recorded normal timestamp changes. The cancelled focus refusal and 2 no-input exit-image pauses are retained; this witness does not replace the prior 2 clean acceptance cycles. Production source/native payload/delivered executable are unchanged. All 234 retained source fingerprints/151,455,090,976 bytes match after a fresh full rehash. The 05:18 UTC audit finds a newer foreign owner in the same REA project; no new provider was started or adopted. Evidence: `workspace/reports/cditem-execution/20261018-native-live-witness/` and `20261018-native-review/batch7-live-mode1-review/`. Full native feature/T20 remain open.

Completed native continuation: the fourth owned provider imported all 1,278 prior evidence records/95 unknown revisions and retained every canonical row in `workspace/reports/cditem-execution/20261018-native-review/batch4-registration-boundary/provider/rea-complete-final-ledger.json` (96,795,800 bytes; SHA-256 `1f9817603690170007cd5fbe690836d0d4ecef371f8826d27b18d93d43e3a3ad`; 1,289 records/97 revisions across 16 IDs). Supported target/session close and graceful shutdown passed at 03:32:32.075 UTC; 03:33:57.1009448 UTC verification found no owned processes/project locks, session open:false and unchanged project metadata. New source proves the ignored normal decoder failure, object-only unwind cleanup, copied/borrowed reverse-name consumers and concrete indexed resource provider. First-instance acquisition is separately unresolved at RH-05. No production source, delivered executable, game, installation, archive or save was changed by this continuation.

Execution baseline was `d4988932d2fe68cabc12dedc29f66a0f35fdd88a`; offline work is commit `9ebaebab`, approved translations `367052df`, and final runner/save framework `98ae737c46cb8967cc42d15c7f5dc02680920e13`. The 17 pre-existing dirty paths/hunks remain preserved. [The execution goal](cditem-execution-goal.md) and [reasoning handoff](cditem-astra-pro-handoff.md) record exact implementation, source/device/build proof, cleanup and native restart questions. No original CDISO parent is newly complete.

The installed/analysis game pins match. Final verification passes all 234 source guards / 151,455,090,976 bytes and the four original generation files. All four disposable contexts restored 26 original files and metadata before Cloud. Consecutive clean cycles3/4 each finished seven actions with no failures; independent audits accepted both. Original CDMW setup and Cloud ON/Up to date/minimized library are restored. Final inventory/bytes remain exact; normal Cloud synchronization changed eleven recorded file timestamps. Foreign Loadouts v7.192 is preserved; no source archive was mutated.

The development CLI defaults to read-only inspection. Evidence-bound execute/resume/cancel, physical F/SPACE/hold, exact exit confirmation and bounded cleanup recovery pass focused and independent source checks. Final owner suites pass runner 105, controller CLI 5, offline/live saves 30/66, setup 17 and execution 87; earlier broader readiness is retained. Two consecutive clean fresh stock launch/load/exit/restoration cycles passed without user input. Independent-item scenarios and exact delivered-byte game proof remain open.

All four owned native batches exported and closed gracefully. The fourth complete 1,289-record/97-revision ledger preserves all prior canonical rows;03:33:57.1009448 UTC session/PID/project-lock cleanup passes. New static evidence proves the normal decoder-false path before unguarded publication, object-only unwind cleanup, actual copied/borrowed reverse-name consumers and the concrete indexed resource provider/order/failure. Reviewed formatter escape, coherent publication/rollback, package backing, private source ingestion and full retirement remain unresolved. RH-05 distinguishes the reference tool's exemplar eligibility from a newly source-joined ordinary constructor/UID/planner/apply path; successful first ownership remains unproved. These source facts do not admit native calls or close any original CDISO parent; exact reports, attempts, correction and restart contracts remain in the handoff.

The bounded Steam probes, four guarded exchanges and two consecutive clean stock cycles passed, with final saves/setup/Cloud restored. The normal portable release passed at embedded source revision `98ae737c46cb8967cc42d15c7f5dc02680920e13`: 175,507,262 bytes; SHA-256 `051e0e8c2a3420c2d5e578ed0d1471c9858f770a5d13266124e368b339ff8e7f`. All 586 members, packaged native/default/Mesh startup, six service code objects and fourteen catalogues passed exact checks. Delivered ASI/session hashes equal the actual stock-cycle bytes. This remains a verified partial delivery: native admission, positive/refusal/save-reload and full T20 are blocked by RH-01/RH-02/RH-03. Full native review/scenarios/delivery and all ten feature parents remain open; evidence, rollback, cleanup and concrete probes are in [the reasoning handoff](cditem-astra-pro-handoff.md).


- Continuation status (2026-10-17): Completed the scoped CDISO-RES-01A, CDISO-DEP-01A and CDISO-ID-01A compiler/validation work without requiring user testing. Compiler revision is now 10; portable v1/v2 schemas, UUIDs and numeric ranges are unchanged. These improvements use the existing composed backend. No new native capability is admitted. Continuation source baseline is e0224bb63c290f950c42b56d9a5639c5a69969e0.

- Completed: CDISO-DOC-01, CDISO-BASE-01, CDISO-OWN-01, CDISO-ID-01, CDISO-RE-01 and the three continuation subtasks CDISO-RES-01A, CDISO-DEP-01A and CDISO-ID-01A. Ten original tasks remain open. RE-01 closes the selected discovery route with a scoped negative result; completing the three narrower source subtasks does not close their full resource/dependency parents.
- Implementation: The existing read-only inspection and ownership assessment now include supported private material DDS copies, conservative donor ItemInfo record separation and primary ASCII name-hash refusal. External ItemInfo directory/body key mismatches also refuse. The continuation verified 110 distinct focused cases, including 62 new cases, across the recorded runs. No full suite, native build, game launch or save operation was used.
- Next task: CDISO-RE-02 must establish a typed operation that adds capacity and registers independent ItemInfo and required auxiliary entries, including finalization and rematerialization. CDISO-RE-03 must connect resource loading to that definition route and close its resource-use and lifetime obligations. CDISO-RES-01 and CDISO-DEP-01 remain open: supported material DDS fields now have private copies, but the PAPPT socket consumer, residual item/resource dependencies and implicit native identities remain unproved. All donor DDS guards remain intact.
- Ownership and session state: Root integrated the independently reviewed resource and identity changes and owns the synchronized documentation. The separate CDISO research queue ended at its configured one-hour transport timeout; all completed results and a final inventory are retained. No matching owned analysis processes remained at the final check. Never submit through another investigation's queue or alter its launcher guards.
- Main unresolved condition: Prove a complete supported registration/discovery route for separate item definitions and resources without shared replacement files.
- Shared work: Original implementation baseline was 622758398594b90484f0abce2126dccb9b2f8fb0; this continuation starts at e0224bb63c290f950c42b56d9a5639c5a69969e0. Prior Window/DPI and Mesh/loader work is preserved. Pre-existing localization changes and the unrelated progress-log edit remain outside this task's commit. Native bytes, generated archives and private research receipts remain uncommitted.
- Completion of the full goal: Pending. Do not close CDISO-DONE-01 using source inspection, conflict refusals, or ordinary composed-VFS output as substitutes for the required game behavior.

### Automatically verified continuation, 2026-10-17

The user authorized all feasible work that can be completed without user testing. The three scoped subtasks below are complete; the original native and full-isolation tasks remain open.

| Completed subtask | Result | Retained boundary |
| --- | --- | --- |
| CDISO-RES-01A | Exact unqualified ITexture path fields in owned template/imported/variant/companion materials now use validated, stable private DDS copies. One source copy is reused within each item; unrelated material bytes and explicit imported destinations are preserved. | Unsupported DDS layouts keep an explicit borrowed binding. Other resource types, socket descriptors, physics/rig/animation and native discovery/lifetime are not admitted. Donor DDS conflict guards remain mandatory. |
| CDISO-DEP-01A | The donor's own ItemInfo row can coexist with external or typed field edits after a distinct compiled key/name/hash and absence of retained donor identities are established. The clone's bytes and bindings survive both orders, updates and removal. | Exact author-source hashes and index witnesses stay mandatory. Direct/transitive borrowed records, opaque donor tokens, non-ASCII/NUL names and incomplete table cases keep the guard. External directory/body key disagreement refuses before composition. |
| CDISO-ID-01A | Primary CDI_UUID names are checked for known 32-bit aliases under an explicit ASCII lowercase model against selected packages, stock/external rows and active/disabled/removed reservations. | No Unicode/CRT locale, auxiliary-name, native lookup or persistence guarantee is inferred. Same-owner update/reinstall keeps the identity. |

The private DDS copier uses the existing registration and collision owners. Its new logical accounting applies to independent additions through _Planner.add and to automatic extraction before reading the source payload; it does not claim to redesign every repository output path. Namespace-qualified material references remain unwalked and explicitly clear source-reference closure, preserving source-carrier verification.

The donor exception is deliberately narrow. A valid external ItemInfo body whose three repeated key DWORDs disagreed with the directory was accepted by both resolvers before the new consistency check. Both corrected reproductions then passed with attributed refusal and unchanged fixture files. A first malformed fixture was already rejected by the existing local-string decoder and is not counted as evidence of the gap.

Validation covers 110 distinct selected cases, including 62 new cases: 17 donor/identity-consistency cases, 17 primary-name cases, 16 private-DDS cases, ten exact-field parser cases and two namespace-closure cases. The final identity/dependency run passed all 52 selected cases in 17.19 seconds. Resource/graph/variant/imported-profile checks passed; the one stock-collision fixture failure in that earlier 35-case run was corrected and passed in the final identity run. Existing source/index guards, compiler-rebuild requirements, report admission and archive/virtual lifecycle checks passed. The test changes replace old unconditional-donor expectations with explicit borrowed-record cases, isolate temporary virtual profiles from host process state, and update stale compiler-cache/hash-callback fixtures. The production game-running guard is unchanged.

Before implementation, two material-copy cases failed while ordinary authoring passed; two detached-donor cases failed while explicit-donor-reference controls passed; and all four managed UUID hash-alias cases failed to refuse. A known pair of distinct UUID4 names hashes to 0xab4bfdfe under ASCII lowercasing: CDI_3940d897d80049ccbbd9cf59d9cce27b and CDI_71e0100e5b4c4c88a891843a775a115e. A separate stock-safe witness pairs CDI_e2e5d4ea3ad14dbab0c523e9f2c9189e with StockAlias_101450 at 0x50034b30. These are source-derived mathematical collisions and automated preflight checks, not observed game failures.

| Synthetic one-texture copy cost | Delta |
| --- | ---: |
| Owned DDS outputs / DDS bytes | +1 / +144 bytes |
| Material bytes / logical owned resource bytes | +16 / +160 bytes |
| PATHC bytes | +24 bytes |
| Portable input blobs, package ZIP size and exact source pins | Unchanged |

The single control/private compiler observations were 0.034293/0.013235 seconds; their order/cache bias does not support a speedup claim. On the Windows project environment, the donor guard's three-sample medians were 0.75 ms for a 64 KiB owned DDS, 13.10 ms for 4 MiB and 52.34 ms for 16 MiB. These fixtures publish nothing to the actual game. Native CPU/GPU cost, actual game storage and appearance remain unmeasured. The compact receipt is .work/tasks/2026-10-17-cditem-conflict-isolation/continuation/verification.json.

Offline native work repinned both selected executables to SHA-256 57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7, 384,521,624 bytes. Selected direct callers still lead to the known materializer, lazy/eager paths and invalid sentinel; the generic insertion scan is truncated and proves no absence of other APIs. The observed helper 0x14038ac90 jumps to 0x1488046b0..0x14880475c and maps an external DWORD key to a WORD ordinal or 0xffff through owner 0x146d69a70. The decoder stores the result at +0x40 without checking its return flag. This resolves one auxiliary dependency edge, not an append operation. The second observed owner and a store-shaped lead still lack an established registration contract.

The retained native name-hash arithmetic matches calculate_pa_checksum/hashlittle with seed 0xC5EDE across 201 independently transcribed Python cases. The observed materializer normalizes a C string before hashing and inserts the name hash separately from the directory's numeric lookup, motivating both new identity guards. No native function was invoked. Typed capacity growth, all auxiliary owners/fixups, atomic publication/failure cleanup, valid phase/thread/allocator use, finalization, rematerialization and persistence remain open. No new REA session was started. Source notes and exact receipts are retained under .work/tasks/2026-10-17-cditem-conflict-isolation/continuation/native; the earlier RE-01 rejection and R2 timeout record remain unchanged.

### Implemented ownership boundary

The inspector uses the normal v1/v2 readers and per-package compiler/dependency checks, then reports proposed identity reservations, current additions, compiled string/localisation/prefab/icon/texture identities, deliberate stock edits, exact package links, source table descriptors and decoded item references. Proposed reservations include retained and retired identities; new inspection allocations are not committed. Package metadata cannot grant isolation. Both current backends still report shared-file composition and reject the stronger isolated-new-item claim.

Resource nodes distinguish owned output bytes from borrowed source bytes and record known target/source bindings, SHA-256, layout evidence and outgoing references. Contribution and authoring roles describe the inspected compiler graph. They do not prove engine use or donor detachment. Unknown ItemInfo roots, skeleton/animation/physics lookups, caches and native lifetimes stay explicit. The 16,384-edge diagnostic limit marks partial inventory and reachability while the original source audit continues. Existing source hashes, compatibility guards and reference-closure semantics are preserved.

Validation: 20 new inspection/reference cases cover same-name private outputs in both package orders and both current backends, v2 stock edits, hybrid packages, exact provider links, forged metadata, strict read-only refusal, nested resources, source-role distinctions and diagnostic overflow. Fourteen collision cases cover both orders and batch/active/disabled/removed owners, ambiguous hash paths and case-normalized external paths. Eleven pre-existing coexistence/lifecycle cases and two effect cases complete the 47-case selected run (18.32 seconds); two unchanged-physics roundtrip/resolution cases additionally passed (1.17 seconds). The corrected sidecar source mapping uses the existing basename adapter and only records an original sidecar when it exists.

### Retained two-package inspection before compiler revision 10

A single read-only inspection of retained `test1.cditem` and `test2.cditem` against the existing virtual route succeeded on 2026-10-17. Their exact ZIP hashes match the baseline. Each contribution has six private outputs, 124 borrowed resources in the audit, 31 shared-file outputs and ten unresolved graph boundaries. Only one borrowed path is reached from the decoded contribution: `character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0001.sockets.xml`. The other borrowed audit nodes include authoring-validation inputs; their count is not a count of proven runtime dependencies. Both graphs fit within the edge inventory limit, while reference closure and isolated-new-item admission remain false.

The inspection proposed distinct retained bindings and private paths, returned `published: false`, and invoked no publication or game/save operation. It took 27.712 seconds with a 1,958,670,336-byte process peak working set. These are one-run whole-inspection observations, not an incremental-cost comparison. Full private report: `.work/tasks/2026-10-17-cditem-conflict-isolation/inspection/retained-test1-test2-20261017T125409Z-27e8a402.json`, 473,041 bytes, SHA-256 `0edd6ae4f08e0b2980965a328ba0561a90f2719c5ac8331bee77750b76f7aa9f`.

### Socket descriptor boundary

A single additional source read validated the contribution-reachable socket descriptor against both retained package reports and the current archive witnesses. The descriptor is 912 bytes, SHA-256 `8e522988f191bdd4faa2447761ef3602520bb06720b95eecb20903ff61af88a0`, at offset 44,768,768 in `0009/0.paz`; its index SHA-256 is `c561ae348ba6dea65b0460686dec089b65291bbbeec439643d42bc5f4ead05b9`. It contains five flat `Socket` rows with name, parent, rotation and translation fields. `StackEquipInfo` and `VertexSocketList` are empty. Four sockets bind `B_Weapon_0001`; `Store_Pivot_Socket` has an empty parent. These exact bytes contain no file paths or descriptor self-name.

The supported PAPPT parser exposes an explicit `sockets_path`, and the current clone preserves it: the donor mesh stem `0036` and both compiled stems still point to descriptor `0001`. A future narrow copy candidate can preserve these descriptor bytes and all attachment names while rebinding only added PAPPT records. The existing XML patcher, historical v43 note and source tests do not prove native admission of a new descriptor path. No socket-descriptor copy adapter or socket donor-guard exception was enabled. Residual ItemInfo donor references, borrowed HKX and implicit rig/animation/physics dependencies remain separate unresolved boundaries.

The read completed in 15.684 seconds with source revision validation, without package recompilation or publication. Private report: `.work/tasks/2026-10-17-cditem-conflict-isolation/inspection/socket-boundary-20261017T131817Z-a4ee39e2.json`, 9,147 bytes, SHA-256 `089b238120b48b1d8582d018fb5ba91480e879466cad3f36e8065dbdf3750f1f`. This records the selected source layout and existing bindings; it is not game, cache or private-path discovery proof.

### Native research continuation, 2026-10-17

Both the installed executable and retained analysis copy were rehashed at 384,521,624 bytes with SHA-256 `57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7`. The PE exception directory contains 244,444 runtime-function records. It independently bounds the old large caller at `0x1425bbb90..0x1425c1530` (22,944 bytes), body helper at `0x1425c5230..0x1425c5599`, header helper at `0x1425c55a0..0x1425c5976`, constructor at `0x142412710..0x142412b1f` and relocated initializer at `0x14f4c09f0..0x14f4c0b19`. These are PE exception intervals, not a complete control-flow or ABI claim.

Exact instruction and diagnostic-string observations correct the earlier candidate interpretation: the large caller checks that each family's `_invalid` singleton is null, invokes its initializer, then checks that it became valid. The `iteminfo` reference at `0x1425bc118` is on the initialization-failure logging path. The 0x440 allocation establishes an invalid/default ItemInfo object; the real ordinal getter now confirms its failed-lookup fallback role, while individual field meanings and full lifetime contracts remain separate questions. The downstream `0x141aaf460` entry is an E9 stub to `0x14cf35a90..0x14cf35b7c` (236 bytes, SHA-256 `9ef06d0070d196a6fbe8cda0c6cce3f5b4c27b92e0b26c38ee2b365a43f10ab9`). Pinned instructions and R2 decompilation agree that this helper allocates and initializes a separate 0xa0 object, publishes `0x146ce5298`, and returns zero status. Its type and collection role remain unknown; no source parser or additive item insertion API has been established by this chain.

The output-slot helper `0x14136a9c0..0x14136aa25` (101 bytes, SHA-256 `4bb98839b6cab7315c9029190d52eac4ea799882532270ab75f1d4b8236cf05c`) calls a pointee helper and a TLS-selected release-like function before clearing the output slot on normal return. This confirms the header-absence reset branch, while pointee destruction and allocator/lifetime contracts still require separate proof. Source bytes at `0x14f4c0a84` establish a zero DWORD at offset 0; calling it an item key remains an inference. Likewise the offset-0x20 assignment is a global pointer value after string-like checks, with no established empty-string or storage-ownership contract.

The real ItemInfo owner is global `0x146d69aa8`. Pinned RTTI names identify `pa::ItemInfoManager` and its `StaticInfoManager2<ItemKey,ItemInfo,...>` base. The constructor at `0x14f4e9220..0x14f4e93ef` stores the supplied provider at owner+0x10 and registers callback records. The family factory at `0x1425b6ef0..0x1425bb937` allocates the 0x168-byte owner, stores it in one of 149 family slots, and invokes its global-publishing virtual method. This identifies a shared provider and one current ItemInfo owner. The selected outer dispatcher's unqualified load policy is now established below; the concrete provider receiver and a safe typed extension operation remain separate questions.

| Observed ItemInfo operation | Source-backed result | Implementation consequence |
| --- | --- | --- |
| Header load, `0x14241b8d0..0x14241bcbe` | Reads the 16-bit count and overwrites the owner's current count; nonzero input replaces primary pointer/expiry storage while metadata pairs append using the existing count at owner+0x30, without a shown reset. Missing input and late failure take different paths, with mutations already made before some failures. | Calling this unchanged for a second source is not safe additive registration; transactional recovery is unproved. |
| Key and ordinal lookup, `0x148802fb0..0x14880304c` and `0x14038ab60..0x14038ac88` | Numeric keys resolve through the owner's map to a 16-bit ordinal. A populated slot returns its object; otherwise the getter loads one unqualified `iteminfo` body cache and materializes that ordinal, with the invalid singleton as fallback. | A separate owner or initial object allocation alone does not integrate normal game lookup or future reload. |
| Materialization, `0x14038ae70..0x14038b125` | Allocates/constructs a record for an existing ordinal, decodes fields, registers its name hash and publishes its slot. It neither grows the count nor creates the numeric key mapping. If the field decoder returns normally, its Boolean result is ignored. | A zero materializer status is not a complete parse check. Diagnostic abort/exception behavior and full field ownership remain unproved. |
| Key insertion, `0x140390ad0` and its split intervals | An existing numeric key returns the existing node; the header path ignores the returned insertion flag. | This caller does not supply a complete duplicate refusal contract for an additive loader. |
| Finalization, `0x142417160..0x142419733` | Rebuilds derived indexes and validates catalogue relationships while reading items through the global getter. Some field decoding also resolves auxiliary keys through another live registry. | Every required registry, linking order and derived index remains part of the definition gate. |
| Maintenance, `0x14241bcc0..0x14241bd7b` | Visits a rotating subset of ordinal slots and clears expired records through `0x14038d9d0`; it can also clear the cached body buffer. The record-slot helper explicitly stores null on normal return. | Per-package backing data and rematerialization must remain correct after eviction. The clock units, complete allocator/destructor contract, callback phase and saved identity are not established. |

These observations reject treating a header loader or record materializer as a ready independent-registration API. They do not prove that every other native route is absent. No game function, registry write, new runtime hook or capability was enabled.

#### Selected discovery route: scoped rejection

The owner factory caller at `0x1427c1650` passes its holder through `0x1425c3740`, then `0x1425bb940`. The latter is an E9 entry to `0x14fa45a60`. Pinned instructions across the dispatcher's adjacent PE fragments show a 149-owner header loop calling vtable+0x20 with R8 explicitly zero, followed by a 149-owner eager-body loop calling vtable+0x60 with R8 explicitly zero. Follow-on phases call +0x28, +0x30, +0x38 and +0x40, including the known ItemInfo finalization slot. Status failures leave through the shown error branches; the loaded flag is set only after the successful final phase. This direct flow does not enumerate ItemInfo qualifiers or independently named definition sources.

The preceding 2,086-byte `0x1425c3740..0x1425c3f66` source interval does enumerate through provider+0x58, but the exact arguments are `gamedata/binarymisc__/bin/` and `*.OverridedLevelListBinary`. It reads those supporting buffers into the holder's collection. That enumeration is not evidence of ItemInfo source discovery. The final source-window checkpoint retains 768 bytes from `0x14fa45a60` and 160 bytes at each argument-string address. The dispatcher reaches its return/error paths within the five adjacent PE fragments ending at `0x14fa45cb4`; the larger sample also contains adjacent bytes and is not itself a claimed function extent.

The repeated-header rejection also follows directly from the owner layout. For two disjoint positive-count definition sets of M and N records, an unchanged second header installs a current count of N and replaces the normal lookup array with N slots. That cannot represent M+N distinct entries through the observed lookup. Existing map entries do not supply additional slots. Resetting first also leaves only the second set. Supplying a cumulative header would reintroduce a combined replacement table. A different typed operation or higher-level native contract could still be viable, but it has not been established by this selected route.

Proven argument use includes owner/status-output/qualifier in RCX/RDX/R8 for the header and owner/status-output/ordinal/reader in RCX/RDX/R8/R9 for materialization. These are observed call/data-flow roles, not permission to invoke the functions. Startup thread, allocation ownership, callback scheduling, auxiliary families, failure cleanup, backing-source recovery and save behavior still prevent CDISO-RE-02 and backend selection from closing.

Final source checkpoint: `.work/tasks/2026-10-17-cditem-conflict-isolation/native/pe-cdiso-final-load-windows.json`, 23,267 bytes, SHA-256 `83b942e6dfd75f1e0540499bcfe07d8ad332082cb20d2dee08b6901cdb028265`. The 768-byte dispatcher sample has SHA-256 `049c6dfcf9ca94d7778a611efd7ed34deea2d1491db38f69ef8b175e10b8f07e`. Both executable pins were revalidated by this source read. The two final Ghidra requests were not processed before the transport timeout; these last conclusions use independently decoded original bytes, with no decompilation result claimed for those requests.

Detailed caller, ABI-role, cleanup and session observations are retained in `.work/tasks/2026-10-17-cditem-conflict-isolation/native/native-research-notes-final.md`, 44,854 bytes, SHA-256 `ec8ac60fc9e8229c2680096c06cbb5e9f9460f2e463cb699a3b7f901f3ebbfb0`. This private research note preserves the decisive phase call addresses and source-fragment qualifications; it does not extend the production runtime contract.

#### Native resource discovery and retained use

The separately traced resource manager at `0x14129efb0..0x14129f8eb` requires a leading slash, performs cache lookup and a guarded retry, selects a registered factory through `0x14129c250`, and on a true miss creates, publishes and schedules a resource. Factory absence refuses before byte delivery. Factory-key helper `0x141293410` recognizes a final XML extension and selects the preceding compound suffix; the selected socket pathname would produce `sockets.xml`. Its actual PAPPT consumer and any corresponding registered factory entry remain untraced, so this does not admit private sockets.

Cache lookup `0x140479f80` compares the stored hash and then wrapper identity or string equality, continuing after a same-hash mismatch. Hash leaf `0x141364780..0x141364d04` and equality target `0x148859bb0` operate on the supplied bytes without character folding or slash rewriting; earlier caller normalization is not ruled out. Exact continuation windows close the short-fragment comparison evidence gap. The prefab routine skips acquisition for retained nondeleted state at least 5; Loadouts correctly requires exactly state 5 for readiness. State 6 semantics, negative-cache recovery, eviction and replacement under a retained name remain unproved.

Current Loadouts source supplies immutable private PAC, DDS, material and prefab inputs to native caller-owned buffers through selected guarded provider/receiver sites. It preserves native decoding and uses private session/attempt identities with retained leases. This is a concrete resource route, while the ItemInfo provider's matching vtable offsets do not prove the same receiver identity. No corresponding route has been integrated into CDMW's independent item loader.

Retained session `08DB483DBC974C63827A35B96083023A`, labeled `runtime-editor-2976-v7.185`, records a private PAC with matching native parser observation and state 5, private material and prefab at state 5, and all five native DDS stages returning true. Exact receipts match a 148-byte DDS header followed by 5,592,432 payload bytes, 2048 x 2048 dimensions and twelve mips. Scene events 38, 41 and 42 connect private mesh assignment, returned native completion and a valid component-to-mesh link for the same attempt, ticket and component. Later routing-window expiry does not independently prove a detach.

The same retained state reports `texture_bound_to_mesh=false`, zero matching material sets and `scene_applied=false` for complete external mesh plus custom texture. Visual success and GPU retirement remain unverified. Its reporting label is not bound by these receipts to a reporting binary hash, source commit or historical host hash; current executable/source pins are separate evidence. These positive resource and attachment observations therefore do not close complete texture use, independent definitions, update/removal, startup or save acceptance.

Private resource receipt checkpoint: `.work/tasks/2026-10-17-cditem-conflict-isolation/native/loadouts-private-resource-receipts.json`, 25,071 bytes, SHA-256 `9ef52fde295f319e540a398ae3f8039db5efae7c123a7a65295f7f814c405d58`. The selected state is 35,787 bytes, SHA-256 `9381b375c2cd029e19f4fa756e3c3ce191fb5a4c6a5fce4c4f15b05369adcaf1`. CDISO-RE-03, CDISO-RES-01 and CDISO-DEP-01 remain open; the narrower evidence does not justify a generic resource-family or donor-detachment claim.

Task-owned probes and raw evidence are under `.work/tasks/2026-10-17-cditem-conflict-isolation/native` and remain outside commits. R1 restored all 1,158 prior evidence records and 86 unknown revisions, but its native attempts failed the existing warm launcher's research-root precondition. The guard was preserved. R1 exported a byte-identical bundle, confirmed `open:false` and shut down with exit code zero. The separately owned R2 session uses a fresh subdirectory of the configured `Crimson Loadouts/out/research/rea-core-20261013/temp` root and restored the same evidence with 12 current unknown heads.

R2 successfully decompiled the source-proven jump target: evidence `ev_b1a52a3e839c73f10f1754d080ba14bc2dab2fd00d584e44ff59f69468ba92d2`. Queries at the unregistered stub returned `invalid_request`. The warm index's empty `iteminfo` xrefs result (`ev_9710b0f497c4632239bfc3bb534c97b7a90704c513dbbe721b7c53de9a8118f8`) is demonstrably incomplete because pinned source instructions include the diagnostic LEA. An empty index result is not evidence of absent native references. A bounded source-byte scan found nine ItemInfo-name candidates; the direct body/header call lists were truncated at 128 retained hits each and remain candidate observations until decoded. The selected source-wrapper/parser intervals are now pinned for actual caller analysis. R2 reached ThinkForge's original 3,600,000 ms process timeout before the final two queries and planned export/close commands. The transport receipt reports terminated, running false and exit code 1; a subsequent check found no matching owned node, Java or command-shell processes. This was not a graceful provider close, and no post-query provider export or open:false acknowledgement is claimed. All 39 completed result files, including three errors and 31 returned evidence records, remain intact. The two unprocessed commands are identified in `.work/tasks/2026-10-17-cditem-conflict-isolation/native/r2-retained-query-inventory.json`, 14,572 bytes, SHA-256 `8d84d14f93d76a926b302460fe9be81cfd04f26474c28bc400be37da0634e611`. The inventory pins each completed result and preserves the original restore-bundle identity; it is not a substitute export. Future native work must use a fresh owned session and preserve these retained records.

## Investigation findings

### Implementation baseline and expected cases, recorded before source edits

The recorded implementation baseline used compiler revision 9; frozen v1 schema digest is fc8a618214bba0ebdbe4187f39dffc5f206ae71e31158f0cf06ad273cbcf1d1c. Adapters are item-v1 1, envelope-v2 4, iteminfo-fields 2, package-links 1, dds-pathc 2, flat-icon-registry 2 and texture-replace 1.

| Case | Expected baseline result | Maintained owner |
| --- | --- | --- |
| Two items from the same donor, both package orders | Distinct destination IDs, names and owned resources; shared tables are still composed | tests/test_independent_items.py, independent authors and imported mesh/icon/material tests |
| Template texture replacement | Borrowed texture changes remain a named dependency conflict; private bytes alone do not prove donor detachment | tests/test_independent_item_compatibility.py and reference-audit checks |
| Template ItemInfo or required equipment record edit | Refuse with external provider, file and required record identified before publication | test_required_record_conflict_identifies_mod_file_and_record |
| Unrelated records in the same table plus update/removal | Preserve unrelated records and other package identities through the existing composed route | test_disjoint_external_records_survive_two_items_update_and_removal |
| Foreign numeric ID or owned ID claim | Reserve foreign IDs and refuse takeover of issued ownership; never silently renumber | test_external_item_ids_are_reserved_and_owned_duplicates_are_refused |
| Final loading output | Current output remains PAMT/PAZ plus PAPGT/PATHC composition; no independent-native claim | virtual_loader_composition.py and native/cdmw_virtual_loader/runtime.cpp |

The four retained G2 packages were rehashed without extraction or mutation. All remain v1, template 1000080, with 165 source dependencies including 114 DDS and two HKX entries. Exact ZIP identities are:

| Package | UUID | SHA-256 | ZIP bytes | Declared blob bytes |
| --- | --- | --- | ---: | ---: |
| test1.cditem | 0f5f3f64ad524d8bb4bd265a6eed49bc | 8e6e16f67f389a1350a903e952f00a3ba38a6c36f0733f1a439ebaf5a4034d10 | 25960861 | 45348459 |
| test2.cditem | 82ccd97c91b841f59bc4770dd4e11b42 | 9410a5446a272ef99598b7746245744db5f874b0d11741612a8cdccf2df752ae | 25960824 | 45348459 |
| test3.cditem | 38964ba4008c44519e088f0177261985 | 5c068ed903fbf4a25b55086299e154dda9637c948c7b5baec133ac603855a870 | 5366025 | 12458911 |
| test4.cditem | 8fdde31a1eb940afa68934b604388460 | 80333ff61f9d11501f3766df4c89c0c5e8cba339a7e7724d5756b020ba1aa283 | 5366029 | 12458917 |

Source hashes at this baseline: independent_item_references.py 39a09f6f16e3a5f15f0b79b0eabedc181da1869f5b40009f480daad85cbf8433; independent_item_compatibility.py f8a3d3baba4e3b0c69314a2052395fa6a3b9c8b2009f4eb0bd4a6e4f5e8f71cb; independent_item_package.py a773492a80cbc7a042bdebbdcf5fcc0559baf8bed22845757c67cb2b91f47963; independent_item_install.py b0fdc8aa1c01d89fffd5907e927b57bd4531d0e40948840365b36ff53ea519b3; compilation.py 7b224016cd902dfc999d1e768fede282b6337ae37c254ec3ea1ad706d82876e3; virtual_loader_composition.py a57c6d4f7b1911fe085339cd5b9c386900bbd4417baef6aa7205ebcd34073ac6; native runtime.cpp 70ea9466452d322132f8aa4d2ee8d26c972811915f2e98ad9cf47aa523bfb6c6.

### Current .cditem ownership is real, but loading is still composed

The existing design already provides permanent package identity, retained local bindings, collision refusal, separate owned records/resources, and independent update/removal. The v1 container carries a recipe and validated content-addressed blobs, rather than a replacement copy of every game table. This is a useful base to extend. The installation contract explicitly relies on CDMW composing shared outputs. [S1, S2, S5]

The current virtual route also composes supported contributions into one private archive pair and shared metadata. At inspection, the saved profile in the supplied game folder selected four packages and mapped 0036/0.pamt, 0036/0.paz, meta/0.papgt, and meta/0.pathc. It was generation bbf65bdaf90146ee835b1ff2093ab7c1. This is a metadata observation, not a new game run or a fresh verification of every snapshot payload. Private output keeps the original files unchanged, but it remains a combined representation of multiple contributions. [S6, S7, G1]

The native loader redirects exact normalized paths to prepared snapshot files and returns real file handles. It does not itself parse .cditem, allocate item IDs, or create typed game definitions. Its foreign-hook guard rejects unsupported coexistence. The general game_redirection_approved gate remains false; separate documented controlled game observations do not expand that public gate. [S7, S8]

### The strongest near-term opportunity is separating donor provenance from actual use

The current audit starts from owned additions but also explicitly visits every existing template-family file and each template part's prefab/socket path. At the recorded baseline, compatibility unconditionally started its required ItemInfo set with spec.template_key, then protected transitive item, equipment-type, and status dependencies. CDISO-DEP-01A now removes only a proved detached donor row from that set. Actual borrowed references, source evidence and unknown boundaries retain their checks. [S3, S4]

The retained test1.cditem through test4.cditem packages all have different identities and use template key 1000080. Each manifest declares 165 source dependencies, including 114 DDS entries and two HKX entries, despite using imported models. These counts describe declared dependencies, not proof that the final item consumes every listed file at runtime. They give a concrete baseline for separating compile-time provenance, validation inputs, genuinely borrowed resources, and fully detached resources. [G2]

The improvement is to prove the final resource and record graph, then stop treating a fully detached donor as a required runtime dependency. Maintain the original source evidence needed to validate and reproduce the package. Preserve real references to shared equipment types, status definitions, ingredients, sockets, rigs, or other content until their ownership or borrowing contract is known. The existing performance/source-guard work must remain intact. [S3, S4, S10]

### Private filenames alone do not establish full resource independence

Existing code already understands several prefab, model-sidecar, material/effect, texture, and supported physics boundaries. Reuse those adapters. The current audit intentionally records an incomplete reference closure for borrowed HKX and other borrowed formats whose outgoing references are not parsed. A copied mesh, renamed file, or matching hash does not prove that implicit sidecars, embedded references, material names, cache identities, or physics/skeleton bindings were detached. [S2, S3, S9]

Allocation also has concrete engine-facing limits: the current numeric pool is 1,990,000 through 1,999,999, and some stem/reference rewrites preserve byte length. Stable package UUIDs must continue to map to retained engine-compatible identities. Arbitrarily extending names, using a UUID as every game filename, or enlarging the numeric range is not an evidence-based fix. [S5]

### Intentional shared edits need a distinct claim

Version 2 supports item.fields and texture.replace operations on existing content, and package.links can declare dependencies between packages. Those are useful supported operations, but contradictory assignments cannot both become the final value of one shared target. Package links validate declared providers and pins; they do not currently relocate arbitrary game references or create native runtime handles. An isolation claim must be derived from the admitted contribution, not from the .cditem extension. [S1, S2]

Creating an independent item also differs from inserting that item into an existing shop, group, recipe, drop set, or world consumer. Such acquisition integrations can still introduce shared state. The independent-item audit allows supported additive shop insertion and refuses stock replacement routes; the full loading goal must prove equivalent additive behavior for every integration it advertises. [S2, S4]

### Fresh REA evidence narrows the native research

The current installed executable was read and hashed without executing it: 384,521,624 bytes, SHA-256 57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7. REA's existing Ghidra 12.1.4 MCP session reported the same target hash for its CrimsonDesert-1.0.0.2976.exe analysis. The session was reused for static queries; no game function was called. [G3, R0]

Initial interior-address and string/xref queries did not recover the documented candidates in the provider's indexed analysis. A separate read of the PE exception directory supplied candidate entry ranges, after which focused REA dossiers returned pseudocode for the loading helpers. These negative index results therefore must not be described as absence of native functionality. [R1, R2]

| Candidate | Observed evidence | What remains unproven |
| --- | --- | --- |
| VA 0x1425c5230, RVA 0x25c5230 | Recovered body helper selects ordinary or qualified filename, then invokes a resource-provider operation through vtable offset 0x40 and returns a buffer/result. | It does not establish additive ItemInfo registration or repeated-load behavior. |
| VA 0x1425c55a0, RVA 0x25c55a0 | Recovered header helper uses matching filename selection, tests a provider operation at offset 0x68, and conditionally reads through offset 0x40. | Exact provider types, absence semantics, caller contract, and ownership need confirmation. |
| VA 0x142412520, RVA 0x2412520 | File bytes contain a relative jump to 0x14f4c09f0. The target allocates 0x440 bytes, calls 0x142412710, replaces global 0x146cfd9b8 after an ownership-helper call, writes fields, and calls another initializer. | The 2026-10-17 continuation identifies the global as the ItemInfo invalid/default sentinel through exact diagnostics. Field meanings, cleanup and lifetime remain separate questions; this is not a proven per-item insertion API. |
| VA 0x142412710 | Recovered pseudocode initializes many fields and sentinel values in the allocated object. | Typed layout, ownership, insertion semantics, finalization, and save lookup are not established. |
| VA 0x1425bbb90 | PE exception metadata covers the earlier iteminfo-reference address 0x1425bc118. | The wider REA query ended with Connection closed and returned no usable dossier. Caller-chain proof remains open. |

The inspected strings are %s%s.staticinfobody and %s%s.%s.staticinfobody, with matching staticinfoheader forms. The qualifier comparison uses base. The directory pointers name gamedata/binarystaticinfo__/bin/ and gamedata/binarystaticinfo__/bin_dev/. The recovered helpers describe selecting a named source; they do not establish directory enumeration, loading every uniquely named package, or appending definitions to an existing live registry. [R2, R3, G3]

The dossiers have a material analysis limitation: the provider reports one-byte function bodies while returning larger pseudocode, and its direct-call/reference arrays do not describe the recovered path completely. PE unwind intervals corroborate separate candidate ranges, but neither source establishes a complete typed call graph. Treat the pseudocode as a research lead, preserve the warnings, and verify instruction boundaries and the caller contract before any runtime use. The session connection closed during the wider family query; successful earlier results are saved. No session restart, annotations, runtime attach, or game launch was performed. [R2, R3, R4]

### The full goal needs two engine capabilities

A supported route must both add typed item/auxiliary definitions and make previously unknown owned resources discoverable. The resource question can block the goal on its own: an engine lookup may reject an unknown path/hash before CreateFileW/CreateFile2 is called. Delivering bytes at file-open time is insufficient unless the engine can first resolve those identities without an edited shared PATHC/PAPGT/archive index. Trace positive and negative lookup behavior and cache lifetime. This is an explicit research question, not a claimed observation of an already-proven failure. [S6, S8; inference]

Two candidate routes remain worth pursuing: verified discovery of multiple independent definition sources, or typed registration plus additive resource discovery. A single coordinated loader may still own a profile manifest and central in-memory registries. It must not require combined replacement game tables, shared archive carriers, or generated compatibility patches to claim completion.

A primary-source comparison with Crimson Desert VFS reinforces the distinction: that project's documented mechanism also composes mod contributions into final game files. Its existence does not prove a native no-merge registry route. [W1]

## Relationship to existing work

This is the dedicated plan for item independence and loading without shared-file merging.

- [Mesh Editor, Create New Item, and Virtual Loader improvement plan](mesh-editor-cditem-virtual-loader-plan.md) owns cache/performance work, source-verification roles and guards, prepared-output reuse, and associated measurements. Reuse that work. This plan adds the semantic distinction between donor inputs and the resources the final item actually uses; it does not authorize removing those source guards.
- [Universal .cditem support plan](../docs/plans/active/cditem-universal-format.md) describes existing v2 field, texture, package-link, semantic-export, and save-evidence work. Its completed modules are the baseline, not tasks to repeat here.
- Existing independent-item and virtual-loader contracts remain authoritative for their current backends. New guarantees must be reflected in their owning documentation after implementation is proven.
- Broad new character, body, hair, quest, audio, and world adapters are outside this focused equipment-isolation plan. A later adapter must satisfy the same ownership principles before claiming equivalent support.

## Architecture decision

| Route | Useful result | Does it meet the final no-shared-file-merge goal? |
| --- | --- | --- |
| Extend private resource ownership under today's compiler | Removes supported donor-resource coupling while retaining the current trusted package and lifecycle code | No. It is an incremental improvement while tables are still composed. |
| Native discovery of multiple independent definition sources | Lets the game load distinct item definition sets through a verified native mechanism | Only if every necessary registry and resource works without a combined replacement manifest/table. |
| Typed runtime registration plus private resource resolution | Registers owned definitions and resources directly, using one coordinated runtime | Candidate for the full goal; construction, publication, references, lifetime, and saves must be proven. |
| Redirect a shared table request to a combined private table | Keeps original disk files unchanged and avoids manual user merging | No. This is the current class of composition mechanism. |
| Show a custom mesh on an existing inventory definition | Can demonstrate resource loading | No. It does not establish a separate persistent item definition. |

Investigate native multi-source discovery first where evidence supports it. If it is not a usable extension point, investigate typed registration. Reuse the existing loader and ownership services where justified; do not create a competing generic runtime or a second source of identity truth.

The current backend can remain available for existing packages. Its limitations must stay visible. An unavailable independent backend must not silently fall back to shared-table composition while reporting the new guarantee.

## Execution priority

Phase headings group work; they do not require broad resource cloning before engine feasibility is known. Reconfirm the baseline and ownership contract, then prioritize the independent definition and resource-discovery gates. Pursue low-risk ownership improvements in parallel where they do not duplicate concurrent work. Establish the smallest supported two-item proof before expanding to additional resource families. If native loading remains blocked, report resource detachment as a partial improvement and leave the full goal open.

## Phase 0: preserve the baseline and define the contract

- [x] **CDISO-DOC-01: Complete the read-only investigation and create this plan.**

  Acceptance: Record current source findings, the actual REA result and its limits, implementation gates, and shared progress rules. Save the plan in beta-progress and append the matching documentation completion entry without changing source or game files.

  Completion: 2026-10-17. Investigation and plan completed. Evidence and limits are recorded below. Project edits are limited to this plan and its own entry in progress.md. REA query/result scratch artifacts are identified in the evidence section; implementation tasks remain unchecked.

- [x] **CDISO-BASE-01: Reconfirm current owners and capture decisive isolation cases.**

  Work: Read current instructions, this plan, the shared progress log, and relevant concurrent changes. Select representative existing item packages and the smallest maintained fixture cases. Record exact source/compiler/package identities and claim the files or narrow shared hunks to be changed.

  Acceptance: The baseline distinguishes separate identity, private resources, borrowed dependencies, shared-record additions, and actual loading behavior. At minimum include two items from one donor, a template-texture replacement, a template ItemInfo edit, independent update/removal, and one foreign ID collision. Record expected results before changing code. Reuse existing measurements and test evidence where unchanged; no broad suite or game launch is needed for this baseline.

  Completion: 2026-10-17. Current local/global instructions, shared log, compiler 9, seven source hashes and four retained package ZIP identities recorded above before source changes. Expected donor texture/record, two-item, lifecycle and foreign-collision outcomes are explicit. Eleven existing focused cases passed in 11.63 seconds, covering both authoring orders, mesh/icon/material references, required records, unrelated-table lifecycle and foreign IDs. These are owned-fixture checks of the existing composed route, not game or native isolation proof.

- [x] **CDISO-OWN-01: Derive an explicit ownership and dependency assessment.**

  Work: Extend the existing compiler/audit data where needed to distinguish authoring provenance from runtime dependencies. For each owned record or resource, identify stable symbol, destination binding/path, outgoing references, source evidence, supported layout, and ownership/lifetime. Include implicit sidecars, derived basenames, registry hashes, variants, and runtime-only lookup rules.

  Acceptance: Inspection can explain whether an item owns the relevant graph, still borrows resources, edits existing content, or contains an unverified boundary. Claimed isolation is derived from validated content and adapters, not trusted metadata. Deliberate item.fields/texture.replace edits and package.links dependencies remain correctly represented. Old v1/v2 behavior and capability refusal are preserved. Use existing owners instead of creating a universal abstraction without a concrete consumer.

  Completion (2026-10-17): Implemented the derived bounded resource graph and its read-only inspection consumer, with explicit source/contribution roles, output identities, stock edits, package dependencies and unresolved native boundaries. All 20 new inspection/reference cases pass within the 47-case selected regression run; two additional unchanged-physics cases pass. No package metadata, source-compatibility rule, compiler output or native loading capability was expanded.

## Phase 1: remove supported resource and donor coupling

- [ ] **CDISO-RES-01: Extend private resource ownership where the reference graph is proven.**

  Depends on: CDISO-OWN-01.

  Work: Reuse existing family/material/effect relocation. Identify resources that remain shared, and make private copies only where their complete reference layout and runtime lookup behavior are understood. Rewrite every relevant reference and registry identity to the item's stable binding. Evaluate textures, material sidecars, companion models/prefabs, effects and their emitters/presets, icons, and supported unchanged physics separately.

  Acceptance: Two packages derived from the same donor keep distinct owned identities and paths. Changing or removing one does not change the other. Replacing the donor's supported texture or other detached resource affects the donor as expected while the private copies retain their intended bytes and bindings. Nested and implicit references resolve correctly. Unknown physics, skeleton, animation, or other layouts remain explicitly unverified; never perform blind binary string replacement or label borrowed unknown resources private.

  Preserve existing byte-validation, size/cancellation limits, and validated immutable sharing. Measure additional package size and runtime/storage cost for the actual resource families changed.

- [x] **CDISO-RES-01A: Isolate supported material DDS references in copied item meshes.**

  Subtask of: CDISO-RES-01. Scope is independent-package compilation of copied template, imported and selected-variant/companion model materials through existing texture registration. Ordinary loose authoring behavior stays within its current contract.

  Acceptance: Parse and rewrite only complete admitted model-property ResourceReferencePath texture attributes. Copy validated DDS bytes to stable private destinations, preserve all unrelated material bytes and exact author-source witnesses, and reject ambiguous paths and resource-limit violations. Unsupported layouts refuse private-copy admission and retain an explicit borrowed binding. Both package orders, independent update/removal, reference binding and incremental package/storage cost are checked automatically. Socket descriptors, non-DDS edges, native discovery and game appearance remain separate proof.

  Completion (2026-10-17): Implemented and verified exact typed-field private DDS copying, stable source-derived paths, preserved imported destinations, source-digest evidence and bounded independent additions. All 16 new private-texture cases, ten parser cases and two namespace-closure cases pass, along with existing graph/variant/imported-profile checks. A v1/v2 pair passes both orders and archive/virtual update/removal with actual final material-to-DDS byte assertions. Portable inputs/source pins are unchanged and the measured logical copy cost is recorded above. This closes the supported copying subset only; CDISO-RES-01 and donor DDS/native gates remain open.

- [ ] **CDISO-DEP-01: Retain donor provenance without unnecessary runtime dependency protection.**

  Depends on: CDISO-OWN-01 and the relevant CDISO-RES-01 proof.

  Work: Review the unconditional donor-family and template-record roots in the current audits. Separate inputs needed to compile/validate a package from resources and records its final output actually references. Narrow external-mod conflict requirements only when the final graph and supported runtime behavior prove the donor is no longer required.

  Acceptance: A proven detached item can coexist with an external edit to its donor without inheriting that edit or changing the donor. A genuinely borrowed item, equipment type, status, crafting ingredient, socket/perk, physics resource, or other dependency remains protected according to its contract. Exact author-source compatibility, index witnesses, changed-during-read checks, and the native dependency guards are preserved. This task is not blanket permission to relax package hashes or to certify a new game build.

- [x] **CDISO-DEP-01A: Distinguish a detached donor ItemInfo row from final borrowed records.**

  Subtask of: CDISO-DEP-01. Scope is the unconditional donor ItemInfo root, not donor resource detachment or native independence.

  Acceptance: A validated separately keyed/named compiled record with no residual template-key reference can preserve an external donor-only record edit while keeping its own final bytes. Final direct/transitive item, equipment and status references remain protected. Exact author-source hashes, index witnesses and changed-during-read checks remain enforced in current install/profile/rebuild/composition routes. Ambiguous or incomplete final records retain the conservative donor root.

  Completion (2026-10-17): Implemented a conservative final-record donor exception while retaining exact source hashes, source/index guards and all borrowed/transitive obligations. All 17 new donor/identity-consistency cases pass, including external and typed edits in both orders, retained compilation, removal, explicit/opaque donor references, non-ASCII/NUL names and attributed external directory/body-key mismatch refusal. The final 52-case identity/dependency run also passes existing compatibility and mixed-field protections. CDISO-DEP-01 remains open for the full resource/native dependency closure.

- [x] **CDISO-ID-01: Verify complete identity isolation and preserve stable bindings.**

  Depends on: CDISO-OWN-01.

  Work: Extend checks only for identity families newly admitted by this plan. Audit numeric records, case-normalized paths/names, localisation keys, texture registrations, material/effect identities, aliases, and implicit filename conventions. Reuse the UUID ledger and retired reservations.

  Acceptance: New packages cannot take existing stock, external, active, disabled, or retired owned identities. Same-package update keeps bindings; duplication receives its own bindings. Artificial path/hash/name collisions refuse before publication and identify the owners. Installation order does not change already issued bindings. Separate installations retain the existing .cdprofile transfer requirement. Do not widen numeric ranges or fixed-width names without independent engine and save evidence.

  Completion (2026-10-17): Audited the existing admitted identity families and retained lifecycle reservations. Improved collision attribution to include package title/UUID, conflicting resource paths, and external or retired owners. Ambiguous hash refusals retain all known conflicting paths. Fourteen collision cases and the baseline two-order lifecycle/profile-transfer checks pass within the 47-case selected run. Numeric pools, fixed-width names, schemas and compilation stamps remain unchanged; any future native identity family still requires its own admission proof.

- [x] **CDISO-ID-01A: Refuse proven ASCII aliases of managed primary ItemInfo names.**

  Subtask of: CDISO-ID-01. Scope is the existing generated CDI_UUID primary name under the observed 32-bit hash and an explicit ASCII lowercase model. Auxiliary names, Unicode/CRT locale behavior and native lookup/lifetime remain separate proof.

  Acceptance: A real pair of distinct valid UUID4 package names with the same ASCII-lowercase hash is refused before publication in both package orders and both preparation targets. Stock and external ItemInfo names, active/disabled/removed reservations and same-owner update/reinstall are covered. Diagnostics identify names and owners. Derive reservations from the existing UUID ledger without a new schema, numeric range, package rewrite or positive native capability claim.

  Completion (2026-10-17): Implemented the primary-name preflight before allocation/reuse through the existing UUID ledger. All 17 cases pass, including the real UUID pair, a separate stock-safe cross-corpus witness, both orders/targets, external priority, active/disabled/removed reservations and same-owner update/reinstall. No hash was mocked to create the decisive collisions. The existing clean-stock validator and clone invariants remain intact. Arbitrary Unicode, other native aliases and positive runtime capability remain unproved.

## Phase 2: establish a route without shared replacement files

- [x] **CDISO-RE-01: Prove or reject native multi-source definition discovery.**

  Work: Continue from the exact REA candidates below. Trace callers, qualifiers, file construction, load order, parser/table ownership, and repeated-load behavior. Determine whether a qualifier selects a variant of one family or whether additional independently named sources actually add definitions.

  Acceptance: Record the exact executable identity, function boundaries, calling conventions as far as proven, decisive caller/callee evidence, and limitations. A later controlled probe must expose two separate definition sets while leaving original ItemInfo and associated shared files unchanged, then inspect actual item lookup and every required auxiliary registry. A filename string, attempted file open, or parser success alone is insufficient. If a new shared discovery manifest must be merged, record that remaining dependency rather than calling the route complete.

  Completion: 2026-10-17. Rejected the selected ordinary/qualified static-info route as an unchanged mechanism for independent definition append. Exact executable pins, owner/parser/lookup boundaries, header replacement and metadata append, fixed unqualified startup phases, unrelated override-list enumeration, and record eviction/rematerialization are recorded in Current handoff and retained source evidence. This is a scoped negative research result. It proves no positive two-source loading capability and no absence of other native routes; the controlled two-source and auxiliary-lookup requirement still applies before admitting any positive backend.

- [ ] **CDISO-RE-02: Prove typed definition registration.**

  Work: Identify the native construction/parsing, insertion, duplicate detection, lookup, linking/finalization, and destruction/lifetime chain for ItemInfo and every auxiliary definition used by the selected equipment scope. Keep the separate resource-discovery gate below explicit; typed record insertion alone does not establish renderable resource loading.

  Acceptance: Document receiver and argument meanings, valid startup phase/thread, allocators, record/storage ownership, auxiliary fixups, cache behavior, failure cleanup, and persistence lookup. Do not assume a table-loader entry, an inventory type ID, or a mesh-loading function is an insertion API. No raw registry write, hard-coded unverified function invocation, or omitted finalization step may be used as proof.

- [ ] **CDISO-RE-03: Prove additive discovery of entirely new resource identities.**

  Work: Trace path normalization, name/hash formation, catalogue and resource-manager lookup, archive/offset resolution, texture/material registration, file access, and caches for the selected mesh/prefab/texture scope. Determine where an unknown resource is rejected before a file-open hook can help.

  Acceptance: A supported route makes new owned identities discoverable without composing shared PATHC/PAPGT/PAMT or another shared game index. Evidence distinguishes resource admission, byte delivery, and successful use. Record implicit naming rules, aliases, duplicate handling, negative lookup caching, startup timing, and lifetime. Unknown skeleton/physics or other resource families remain outside the stronger claim until proven.

- [ ] **CDISO-DECIDE-01: Select the proven backend and define its exact supported scope.**

  Depends on: CDISO-RE-01 and CDISO-RE-02 findings sufficient to choose a definition route, and CDISO-RE-03 proof of the resource route.

  Work: Choose the simplest supported mechanism that can meet the full goal. Specify the definition/resource contribution format, runtime capability/version, ownership model, source/build guards, and integration with the existing compiler and loader. Retain .cditem's data-only format; introduce a required capability or module only if an actual new consumer contract needs it.

  Acceptance: The design states which shared-file outputs disappear, which game registries remain central, and which integrations remain shared by choice. It includes ItemInfo, prefab/model registration, strings/localisation/icons, textures/materials, and any admitted recipe/reward/dye/effect records. The plan must not proceed to runtime implementation from guessed signatures. If neither route is proven, record the blocker and next narrow research question, and leave the full goal pending.

## Phase 3: implement the supported independent route

- [ ] **CDISO-RUN-01: Implement per-package registration and resource loading.**

  Depends on: CDISO-DECIDE-01, plus the relevant ownership, resource, and identity tasks.

  Work: Compile validated per-package contributions outside runtime file hooks. Register them at the proven phase through the selected engine mechanism, using retained bindings and private resource paths. Extend current compiler/protocol/provenance records where required. Keep lifetime and error handling explicit. Start with the smallest two-item proof using one donor and separately changed visuals, then expand only after the definition and resource paths work together.

  Acceptance: Supported independent packages reach the game without combined replacement ItemInfo, localisation, prefab/string/icon, texture-registry, or archive-mount files being used as a hidden substitute. Original game and external-mod files remain unchanged. Validate contributions before publication and prove whether the engine copies or borrows each buffer/object. Keep storage alive for the complete required lifetime. Partial registration cannot leave a usable half-item, overwrite another provider, or report success. Use only a proven recovery path; if safe rollback cannot be established, reject before publication or abort the controlled initialization session. Do not invent destructive registry cleanup. Bound storage, decoding, handles, and startup work. Initial startup-only support is acceptable; live reload is a separate capability until its lifetime behavior is proven.

- [ ] **CDISO-COEX-01: Preserve compatible external mods and identify true overlap.**

  Depends on: CDISO-RUN-01.

  Work: Validate coexistence with the selected ordinary replacement-mod and runtime-loader configurations. Preserve existing foreign-hook detection until a supported cooperation contract proves a replacement. Separate creating an item from adding it to an existing shop/group or changing a shared world consumer.

  Acceptance: Unrelated external table/resource edits survive and the private item remains correct. Shared stock resources can change only where the isolated item has no remaining dependency on them. Deliberate edits to the same existing field/resource remain explicit conflicts. Another loader or ASI cannot silently replace CDMW's supported path. No unknown plugin receives an untested compatibility claim. Optional acquisition integrations identify their remaining shared-state rules and cannot silently reduce the item's advertised guarantee.

- [ ] **CDISO-LIFE-01: Verify independent update, removal, and persistent identity.**

  Depends on: CDISO-RUN-01.

  Work: Reuse existing journals, retained packages, compilation identities, .cdprofile transfer, runtime receipts, and save-evidence owners. Verify stable identity through restart, compatible update, disable/remove/reinstall, and missing-provider situations. Keep resource lifetime aligned with the chosen startup-only or later live capability.

  Acceptance: Removing A leaves B's definitions/resources usable and never reuses A's saved IDs implicitly. Existing save references resolve to the intended package after supported updates/reinstalls. Missing-provider, changed-binding, and cross-computer cases have explicit, tested outcomes. A backup or registry receipt alone is not proof that saving without a provider is safe. Any controlled game/save experiment uses a reviewed disposable selection and records actual outcomes; preserve the existing evidence distinction.

## Phase 4: verify the goal and close only proven scope

- [ ] **CDISO-VERIFY-01: Run the focused coexistence and independence matrix.**

  Work: Add only the tests/probes required by the changed contracts, using the existing owners below. Compare both package orders on fresh bindings where relevant, then verify that issued bindings remain fixed. Use source/fixture tests for structural and publication contracts and separately scoped game observations for rendering, inventory, and persistence.

  Acceptance matrix:

  | Case | Required result |
  | --- | --- |
  | Two packages from one donor, different visuals | Both remain distinct items with distinct owned graph identities. |
  | Same-name packages with different UUIDs | Player-facing naming does not merge technical ownership. |
  | Shared validated bytes | Update/remove one owner cannot change the other owner's binding or resource lifetime. |
  | External donor ItemInfo or resource edit | Detached item remains correct; real remaining dependency is reported instead of bypassed. |
  | Unrelated external records in the same former shared file | External contribution survives without requiring a combined replacement file for the isolated items. |
  | Different writes to an intentionally shared target | Clear refusal or an explicit supported shared-operation contract, never a silent winner. |
  | Engine-normalized name/hash/cache identity with same donor and both load orders | Independent lookup and distinct mutable ownership, including implicit names and aliases. |
  | Numeric, string, path, or hash collision | Refusal before partial publication; no renumbering of retained saved bindings. |
  | Update, disable, removal, restart, reinstallation | Only the intended contribution changes; reserved identities and other packages remain intact. |
  | Broken/missing resource or unsupported graph edge | No false independence/readiness result and no partial usable publication. |
  | Game/update or foreign-hook mismatch | Accurate unsupported result through the existing guard. |
  | Inventory, equip/unequip, model/material/icon/name lookup | Actual selected game proof for the supported package/resource scope. |
  | Save/reload and missing provider | Actual recorded outcome; no inference from file-open traces or backups alone. |
  | Final output inventory | No combined shared-definition/registry/carrier replacement files used to satisfy the isolated route. |

- [ ] **CDISO-DONE-01: Close the verified scope and report the remaining limits.**

  Depends on: All tasks needed for the advertised supported route, including CDISO-VERIFY-01.

  Work: Inspect task-owned diffs, update the nearest owning contracts and user-facing descriptions, and synchronize all completion entries. Apply existing release validation rules only for release/protocol/native surfaces actually changed.

  Acceptance: The supported package class demonstrably meets the goal without shared-file merging. Claims identify exact game/build/backend/resource scope. Every completed task has evidence and a matching progress entry. Any unsupported resource family, native coexistence case, or save behavior remains explicit. If only resource detachment or automatic composition is complete, report that useful partial result and leave this final checkbox unchecked.

## Validation and authorization boundaries

This investigation did not run application suites, build binaries, launch the game, invoke candidate game functions, or change archives. Document verification checks the saved plan, task IDs, checkbox state, source references, and matching progress entry.

During implementation, select the smallest meaningful existing test owner and add a reproducer only for an actual changed behavior. Read the current docs/test-matrix.md and applicable AGENTS.md instructions. Do not run smoke, mesh-unit, full, packaging, or unrelated native builds just because the checkout is dirty.

Useful existing owners include:

- tests/test_independent_item_compatibility.py
- tests/test_independent_item_resource_sharing.py
- tests/test_independent_item_identity_deletion.py
- tests/test_independent_item_physics.py
- tests/test_independent_item_regressions.py
- tests/test_independent_item_v2.py
- tests/test_independent_package_links.py
- tests/test_independent_texture_conflicts.py
- tests/test_independent_item_semantic_routes.py
- tests/test_virtual_loader.py
- tests/test_virtual_loader_native.py
- tests/test_virtual_loader_runtime.py
- tests/test_virtual_loader_saves.py
- tests/test_virtual_session_receipt.py

Choose exact cases for the relevant phase rather than running that entire list automatically. A normal focused command uses the project virtualenv and a unique pytest base temp under the system temporary directory. The initial investigation verified documentation only. The authorized implementation now has the focused results and retained-package inspection recorded above; native, game and save acceptance remain open.

A later runtime or game experiment requires the exact test scope and disposable save selection to be settled under applicable project rules. Complete offline preparation first and reuse any authorization already provided for that scope. Reading this plan alone grants no permission to launch, attach, mutate archives, alter saves, install a runtime, publish, or release.

## Evidence and source map

### Source snapshots

Paths below are absolute. Line positions can move because other agents are editing this checkout; use the named function or section and re-read current content before implementation.

| ID | Source and relevant owner |
| --- | --- |
| S1 | D:\CLAUDETEST\CDMW Full\cdmw\ui\new_item\INDEPENDENT_ITEMS.md, portable-package contract, supported-format matrix, ownership, package links, capacity, and runtime limits. |
| S2 | D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_package.py, audit_plan, _prepared_spec, and from_plan. Read SHA-256: 02ceb444d7750523816167630a28a1cf73f528b8d873527f4b9f247e09652141. |
| S3 | D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_references.py, audit_references, donor roots near lines 100-110 and closure decisions. Read SHA-256: 39a09f6f16e3a5f15f0b79b0eabedc181da1869f5b40009f480daad85cbf8433. |
| S4 | D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_compatibility.py, ExternalMods.payload, _folder_metadata, _required_keys at line 291, check_package_dependencies at line 367, and compose_underlay. Read SHA-256: f8a3d3baba4e3b0c69314a2052395fa6a3b9c8b2009f4eb0bd4a6e4f5e8f71cb. |
| S5 | D:\CLAUDETEST\CDMW Full\cdmw\domain\new_item\allocation.py, retained allocation range, suggest_stem, fixed-width relocation, and localisation keys; D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_install.py, retained ownership/binding resolution. |
| S6 | D:\CLAUDETEST\CDMW Full\cdmw\services\virtual_loader_composition.py, compose_underlay and compose_layer_payloads near lines 126-129, PATHC registration near lines 150-163, and final archive/metadata output. |
| S7 | D:\CLAUDETEST\CDMW Full\cdmw\ui\new_item\VIRTUAL_LOADER.md, support matrix near line 408 and Native discovery and registration research near line 644. Final read SHA-256: ba3ba3e8e19698e86fdcd40d1f70548cae7b3a6425af20d1d0fd8ee27b83fa4a. |
| S8 | D:\CLAUDETEST\CDMW Full\native\cdmw_virtual_loader\runtime.cpp, redirected and CreateFile wrappers near lines 56-91, foreign import checks near lines 195-227, snapshot maps near lines 299-305; protocol.hpp, game_redirection_approved; README.md, runtime boundaries. |
| S9 | D:\CLAUDETEST\CDMW Full\tests\test_independent_item_compatibility.py, test_required_record_conflict_identifies_mod_file_and_record and test_external_item_ids_are_reserved_and_owned_duplicates_are_refused; D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_physics.py, existing verified-copy contract. Existing tests were inspected, not executed in this investigation. |
| S10 | D:\CLAUDETEST\CDMW Full\beta-progress\mesh-editor-cditem-virtual-loader-plan.md and D:\CLAUDETEST\CDMW Full\docs\plans\active\cditem-universal-format.md, concurrent work and existing completed capabilities. |

### Installed data observations

- G1: C:\games\Steam\steamapps\common\Crimson Desert\.cdmw\virtual-loader\profile.json. Generation bbf65bdaf90146ee835b1ff2093ab7c1; four selected packages and four mapped files. Stored output hashes were read as metadata, not re-established by hashing those output files.
- G2: D:\CLAUDETEST\Crimson Loadouts\.work\tasks\2026-10-15-install-combined\root\retained-virtual-packages\test1.cditem through test4.cditem. Only bounded ZIP item.json metadata was inspected, with no extraction. Identities: 0f5f3f64ad524d8bb4bd265a6eed49bc, 82ccd97c91b841f59bc4770dd4e11b42, 38964ba4008c44519e088f0177261985, and 8fdde31a1eb940afa68934b604388460. Each declares template 1000080 and 165 dependencies. Blob counts are 5, 5, 10, and 10.
- G3: C:\games\Steam\steamapps\common\Crimson Desert\bin64\CrimsonDesert.exe. SHA-256 57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7, 384,521,624 bytes. Size/mtime did not change during the hash read. PE image base 0x140000000. Exception directory RVA 0x170de000, size 2,933,328 bytes. Relevant begin/end-exclusive ranges are 0x1425bbb90..0x1425c1530, 0x1425c5230..0x1425c5599, 0x1425c55a0..0x1425c5976, and 0x142412710..0x142412b1f. These are PE runtime-function records, not a complete Ghidra function-body claim.
- G3 string locations: VA 0x145a9ad18 and 0x145a9ad30 for body formats, 0x145a9ad48 and 0x145a9ad60 for header formats, 0x14570e720 for base. Directory pointers at 0x145547bd8 and 0x145547be0 point to strings at 0x1459b8820 and 0x1459b87f8. Raw bytes at VA 0x142412520 start E9 CB E4 0A 0D, which yields relative jump target 0x14f4c09f0.

### REA MCP evidence

Existing session root:

    D:\CLAUDETEST\Crimson Loadouts\.work\tasks\2026-10-16-workflow-weapon-styles\root\provider\rea-2026-10-16T23-24-12-188Z

Analysis target:

    D:\CLAUDETEST\Crimson Loadouts\.build-rea-trial-20261006\source\CrimsonDesert-1.0.0.2976.exe

R0: 800-cdiso-session-result.json reports the exact G3 target hash and Ghidra 12.1.4 binding, analysis run 16b5ba65-9693-4362-9a9a-04078d7d19c1, profile digest c0b448eae484fa89750708edcd6e67c63f95a980e946041532b2a9a7bd202e52. Provider process-lineage observation is unavailable; do not infer runtime freshness from that field.

| ID | Saved result | REA Evidence ID |
| --- | --- | --- |
| R1 | 801-cdiso-resolve-result.json, iteminfo interior not_in_procedure | ev_e0f8f0ca840dd9458b0b9eac0ac52b6d3d2289562ccb77bdf2191e31639ca2a6 |
| R1 | 802-cdiso-resolve-result.json, body-format interior not_in_procedure | ev_8d581d91909d580ac31d63408d60d5d99ca15a8a2cf229e5e7d4aada9fbd5b3e |
| R1 | 804-cdiso-strings-result.json, indexed staticinfobody search returned no strings | ev_486045843de89e228f06ab1a522995e335e9942415263724bccd2497dbe15bb9 |
| R1 | 805-cdiso-segments-result.json, analyzed mappings/image base | ev_f04506046c043e9d1d0299c70e1353e3d55f951a4a77c54335ce59bdeed00127 |
| R2 | 812-cdiso-body-loader-result.json, analyze_function 0x1425c5230 | ev_437483c1050f0a9fdd111bd5ae7f9ee899206a0763f6f65c2304860f0620f93e |
| R2 | 813-cdiso-header-loader-result.json, analyze_function 0x1425c55a0 | ev_a558bcd4545529be0ec5187cd999030e2c55626f70849ea251f8832df2cdf004 |
| R3 | 810-cdiso-loader-target-result.json, analyze_function 0x14f4c09f0 | ev_7e3a9fe19dcad26dbb763b4292c1b26b2e9f2bbe684d6a13409aef5f25f3e2a1 |
| R3 | 811-cdiso-manager-constructor-result.json, analyze_function 0x142412710 | ev_fafb505eb5ab6bc38e0908d47aebb11fa01d8835ba6eb44f0b3e4b47daf686fc |

R4: 814-cdiso-family-initialization-result.json records Connection closed during analyze_function 0x1425bbb90. No successful dossier or evidence ID was returned to this client. The reason for closure was not established. The request filename containing manager is a working label, not proof of the native object's type.

The session was accessed through its existing command queue with new, uniquely named query files. Those files and the generated REA results are investigation scratch artifacts. No existing provider script/configuration, game executable, game archive, or CDMW source file was edited. The existing session was not explicitly closed or restarted by this task.

### External primary reference

- W1: [Crimson Desert VFS source and README](https://github.com/liuhVIP/CD_Mods_Loader_VFS), inspected 2026-10-16 UTC. Its documented final-file composition and load-order behavior are a comparison, not proof of CDMW implementation or native engine registration.


## Decision at this handoff

Further improvement is justified. The current package/identity system provides a strong base, while borrowed resources and shared-table loading remain separate limits.

Ownership assessment, retained identity diagnostics and the three bounded compiler/validation subtasks are implemented and verified. Private DDS copying and donor-record separation improve the current composed route; they do not complete resource or native isolation. The selected ordinary/qualified static-info route has a scoped negative conclusion, so it must not be reused unchanged as an additive registration API. The next definition question is a typed operation that expands the normal owner's capacity and registers per-package records with complete auxiliary linking, failure handling and rematerialization. The next socket question is the actual PAPPT consumer's accepted private-name and lifetime contract. Existing resource loading and mesh attachment evidence narrows the remaining resource gate but does not close complete texture use or lifecycle. No backend is selected while those contracts remain open. Ten original tasks remain pending, including the final requirement to load separate owned contributions without replacing shared game files.
