# CDMW .cditem execution goal and unattended device testing

- Plan ID: `CDRUN`
- Created: 2026-10-18, Europe/Stockholm.
- Status: Execution underway. Recoverable baseline, research continuity and offline runner/save substeps are verified; native registration and live device/delivered-byte gates remain open.
- Primary execution model: the user's selected GPT-6.1 Sol with Max reasoning.
- Later reasoning review: the user's selected Astra or Pro session, using [the reasoning handoff](cditem-astra-pro-handoff.md).
- Project: `D:\CLAUDETEST\CDMW Full`.
- Game: `C:\games\Steam\steamapps\common\Crimson Desert`.
- Feature authority: [cditem-conflict-isolation-plan.md](cditem-conflict-isolation-plan.md).
- Shared completion log: [progress.md](progress.md).

## 1. Goal and relationship to the existing plan

Finish the remaining .cditem coding, reverse engineering, integration, and meaningful testing. Build the missing automation so the execution agent can start Crimson Desert on this device, activate mouse/keyboard input at its menu, load the intended test save, exercise the supported item scenarios, retain evidence, and clean up without the user operating the menu for each run. Deliver a freshly verified portable executable containing the completed changes.

The feature goal remains independent new items: separately owned identities, definitions, auxiliary records, resources, native registration, and saved identity. Adding, updating, disabling, or removing A must preserve B and compatible external contributions. The final independent route must not publish a combined replacement game definition table, index, mount file, or archive carrier, whether physical or virtual. A loader-owned profile and central engine registries containing independently owned entries are allowed.

This document is the execution and test-automation companion. It does not replace the feature contract, duplicate its completion checkboxes, or reopen completed beta fixes. Existing `CDISO-*` IDs remain the authority for feature completion. New `CDRUN-*` IDs below own only execution preparation, unattended testing, review, and delivery. The equal-scaling CDMW window check remains in its `WMDPI` plan.

A first supported item family and startup-only activation are useful milestones. They do not silently reduce the original goal. Record the exact supported scope and keep every unresolved required resource or behavior open. Intentional stock edits and optional acquisition integrations keep their existing, distinct compatibility claims. No package can guarantee coexistence with arbitrary foreign native code that replaces its hooks or deliberately claims its identities.

### First decisive native milestone

One independently backed item is admitted through a verified native operation, resolves by numeric ID and name, and survives ordinary cache eviction and rematerialization while the original ItemInfo inputs remain intact. Then prove two same-donor packages through that same route.

### Current request and execution scope

The user's 2026-10-18 request is to create a complete plan covering coding, reverse engineering, testing on this device including starting Crimson Desert, and a saved handoff for higher-reasoning review. This planning checkpoint writes documentation only.

When instructed to execute or continue this plan, perform the requested local implementation, relevant builds, controlled game launches, window input, capture, and tests as one workflow. Reuse that scope for routine subsequent runs instead of repeatedly asking the user to launch the game or press E. An old investigation-only or session-release note describes its earlier operation; it is not a new prohibition on an execution the user has requested.

Before a live run, make its exact package/profile, runtime files, test-save arrangement, process ownership, and recovery actions concrete in a run manifest. Follow existing launch confirmation and ownership contracts through their supported entry points. If a development caller needs to carry the already-given execution authorization, implement and test that explicit bounded contract; do not bypass guards or set a general enable flag.

Preserve original archives, existing mods, settings, profiles, shortcuts, layouts, and saves. Use copied assets and owned fixtures for mutations. Real PAMT/PAZ modification is not needed to meet the independent-loading goal and is outside this plan's normal route. Any genuinely additional destructive action, unresolved data replacement, external publication, or unrelated expansion needs its own concrete decision. Finish unaffected work before surfacing such a blocker.

## 2. Baseline to refresh at execution

These are retained observations, not fresh certification of the future execution environment.

| Area | Retained state | Required refresh |
| --- | --- | --- |
| Repository | Branch `RR/independent-item-packages`. The planning read observed HEAD `1eff824ca5a702c65e0b40a389fb352342722a8b`, following build commit `882e00f4`. The initial read had 17 modified tracked files. A later pre-write read had 49 modified tracked files and two untracked source files, still with an empty index, reflecting concurrent work. | Record the actual HEAD, index, dirty-file hashes, and source owners before editing. Other sessions can advance them. |
| Ordinary portable build | `0.11.0-alpha.23`, 177,944,219 bytes, SHA-256 `58bf4848ffebea365a8a6e0b916cffdd0903fd6b3e4269a0a813f667f774a861`. | Rehash the actual executable before reuse. A source change after packaging is not present in the old executable. |
| Isolation capability | The current archive/virtual implementation reports `isolated_new_item.admitted: false` and `shared_file_composition: true`. | Inspect the current capability owner. Keep this result honest until the new native route passes its gates. |
| Native executable evidence | `bin64\CrimsonDesert.exe`, 384,521,624 bytes, SHA-256 `57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7`. | Hash the installed and analysis inputs. An update invalidates unverified addresses and startup witnesses. |
| Windows access | A prior read-only check found runner session 1 equal to active console session 1, accessible input desktop `Default`, and a foreground window. No input was sent by that check. | Recheck the active, usable desktop and test capture/input. This observation is not game automation proof. |
| Menu behavior | User reports gamepad prompts after startup until mouse activity/click inside the game enables the keyboard E interaction. | Observe and support this state explicitly. |
| Loadouts and REA | Loadouts has separate active work and retained sealed v7.190/v7.191 deliveries. The old CDISO R3 provider timed out and its historical handoff records absence of its named PIDs. | Identify current owners and installations. Never assume the shared analysis database or game is free from an old PID check. |

The retained executable is `D:\CLAUDETEST\CDMW Full\dist\CrimsonDesertModWorkbench-0.11.0-alpha.23-windows-portable.exe`. Build evidence and its rollback location are in [test-build-readiness-plan.md](test-build-readiness-plan.md). Preserve that tested binary before producing a replacement. Its success establishes the completed earlier fixes, not native isolation.

## 3. Tracking and working rules

Read the current global and project `AGENTS.md`, this document, the feature plan's current handoff, and `progress.md` before work. Use the relevant local skills when their actual code surface changes, including archive mutation, asynchronous UI work, or Mesh validation. `docs/test-matrix.md` owns current test commands.

Only one agent owns live desktop input and the game session. Only one verified owner operates a given REA/Ghidra provider. Other agents can inspect retained evidence, review code, or work on nonoverlapping files. Assign files before edits. Never let independent workers install loaders, change the shared profile, or drive the same game.

At every meaningful checkpoint:

1. Record the hypothesis, change or query, actual result, evidence location, and next discriminating step.
2. Update the owning feature checkbox only when its acceptance checks pass. Keep partial findings in the handoff.
3. Append one short completed-item entry to `progress.md` at the same checkpoint. Do not log pending tasks as completed.
4. Read both shared files immediately before writing; use fresh SHA-256 preconditions and targeted patches. Preserve other agents' entries and avoid duplicate IDs.
5. Retain machine evidence outside source control, under `workspace/reports/cditem-execution/<UTC-run-id>/`. Preserve the existing dated research directory.
6. Save task-owned code and documentation in scoped local commits after focused verification. Do not stage unrelated changes, game assets, reports, builds, or captures.
7. Keep the user informed during long work. Run long builds, hashing, and research asynchronously with short polling intervals and persistent logs.

Do not restart a completed investigation merely because the conversation changed. Do not create a second identity system, generic runtime, or progress log.

## 4. Required execution tasks

The documentation item was completed by planning. Execution completion below follows actual evidence; scoped offline substeps do not close their live/native parents.

- [x] **CDRUN-DOC-01:** Create and verify this execution plan, the populated reasoning handoff, the feature-plan cross-reference, and the matching shared progress entry.
- [x] **CDRUN-BASE-01:** Establish current source, process, installation, profile, save, and artifact ownership with a recoverable baseline.
- [x] **CDRUN-PREP-01A:** Prepare and retain a current-compiler candidate for the same four saved packages, without publishing or changing installed state.
- [x] **CDRUN-REA-01:** Establish safe research ownership and a resumable, complete evidence/unknown ledger.
- [x] **CDRUN-AUTO-01:** Implement and test the process-bound capture, input, menu, loading, timeout, and recovery runner.
- [x] **CDRUN-AUTO-01A:** Verify the read-only inspection/synthetic policy and bounded Windows capture/input primitives; live execute/resume and acceptance are not included.
- [x] **CDRUN-AUTO-01B:** Verify evidence-bound execute/resume/cancel and observed menu/confirmation policy, independently correct guardian timing/late-input release, and retain first real capture/menu/deadline/cancellation evidence; successful load cycles remain separate.
- [x] **CDRUN-SAVE-01:** Establish and verify the disposable test-save route, autosave/shared-metadata coverage, cloud behavior, and restoration contract.
- [x] **CDRUN-SAVE-01A:** Verify whole-tree exchange/restoration and interruption recovery on independently copied offline fixtures; live roots remain refused.
- [x] **CDRUN-SAVE-01B:** Observe and journal per-game Cloud ON/OFF/ON, causal account binding and OFF persistence across normal client/service shutdown/reopen; original enabled state restored. This does not certify a live save exchange.
- [x] **CDRUN-SAVE-01C:** Implement explicit evidence-bound live context and exact four-file CDMW setup rollback; fix five independent findings and verify source/recovery fixtures before first real use.
- [x] **CDRUN-SAVE-01D:** Complete the first actual guarded whole-root exchange, stopped-writer output retention and exact restoration of all 26 original save files/metadata after the owned calibration game; world/autosave and final setup/Cloud restoration remain separate.
- [x] **CDRUN-LAUNCH-01:** Complete two consecutive fresh game-launch/load/cleanup cycles without user input, including the gamepad-prompt activation case.
- [ ] **CDRUN-SCENARIO-01:** Implement automated acquisition, equip/unequip, resource-use, cache, and persistence scenarios with measurable results.
- [ ] **CDRUN-REVIEW-01:** Independently review native contracts, changed code, evidence, failures, and the actual supported scope.
- [x] **CDRUN-REVIEW-01A:** Independently review and correct the available partial runner/save implementation and its source/evidence limits.
- [ ] **CDRUN-DELIVERY-01:** Build and verify the final portable executable and native artifacts, and repeat essential device checks using those exact delivered bytes.
- [x] **CDRUN-DELIVERY-01A:** Apply the explicitly approved14-message Archive Locations prerequisite, preserve baseline hunks and pass unchanged catalogue validation before the normal release retry.
- [x] **CDRUN-DELIVERY-01B:** Build the verified partial portable artifact, pass packaged member/native/startup checks, and verify embedded code/catalogue/native-byte identities; native positive/refusal/save-reload and full T20 remain open.
- [x] **CDRUN-HANDOFF-01:** Reconcile every unresolved item into a reasoning or operational handoff, with retained evidence and a concrete restart step.
- [x] **CDRUN-CLOSE-01:** Reconcile all feature and execution outcomes, verify cleanup, and report the final artifact and remaining limits accurately.

### Mapping to the existing feature tasks

The following table routes work; it is not another checklist.

| Feature owner | Work still required |
| --- | --- |
| `CDISO-RE-02` | Complete typed native definition registration, publication, auxiliary linking, failure, lifetime, and reload contracts. |
| `CDISO-RE-03` | Complete additive resource discovery, delivery, parsing, use, caching, and retirement contracts. |
| `CDISO-RES-01` | Own every required resource in the admitted graph and rewrite proven explicit and implicit references. |
| `CDISO-DEP-01` | Detach the donor and close or disclose every remaining dependency, including auxiliary definitions. |
| `CDISO-DECIDE-01` | Select a route and supported scope from positive evidence, retaining the no-shared-composition requirement. |
| `CDISO-RUN-01` | Implement the per-package native route and connect it to the existing package/loader system. |
| `CDISO-COEX-01` | Preserve compatible external mods and refuse genuine identity, resource, or hook conflicts. |
| `CDISO-LIFE-01` | Prove cache reload, restart, update, disable, removal, reinstall, and saved identity behavior. |
| `CDISO-VERIFY-01` | Complete the feature matrix with source, binary, package, native, and visible evidence. |
| `CDISO-DONE-01` | Close only the verified scope, with final review, documentation, and delivery evidence. |

These ten feature tasks were open at planning. Earlier ownership, retained-ID, private DDS, donor-row, collision, and bounded research results remain useful completed work.

## 5. Phase A: baseline, ownership, and research continuity

### CDRUN-BASE-01

Record a baseline manifest before mutation:

- HEAD and all task-relevant dirty source hashes; existing staged changes and other owners.
- Current game executable, Steam launcher, ASI bootstrap, CDMW runtime, and any installed Loadouts identity and hashes.
- Exact process IDs, creation times, executable paths, and ownership evidence for CDMW, game, helper, and analysis processes.
- Selected physical and virtual mods, the saved profile, generation, retained identity ledger, and referenced package hashes.
- Original game/archive fingerprints through the established source-guard protocol.
- Actual save path, account/slot layout, known current settings, and verified independent recovery copies.
- The last good portable executable, native artifacts, and rollback locations.

An already running game is not automatically a test session. Do not close, attach to, or replace it merely to clear the way. A process started elsewhere must remain outside this runner unless its owner deliberately transfers it with enough evidence. Recheck for a launch race immediately before process creation.

Use a new owned build/stage/report directory where required. Never configure or rebuild over the sealed Loadouts v7.190/v7.191 stages. Re-inventory the current installation instead of assuming v7.191 is still installed.

Acceptance: every intended test mutation has an exact owner, prior state, and recovery path; unrelated baseline content is retained. No unowned game, loader, or profile is modified.

### CDRUN-REA-01

Start with the R3 ownership handoff in the source map. Confirm current provider ownership, target, queue, and any in-flight request. A historical PID being absent does not prove current availability. Preserve lock files and another owner's process or queue.

If the shared database is owned, continue retained-source analysis, resource work, tests, or runner development. Record the operational dependency. Use an independent analysis project only through an established supported workflow that preserves the shared database and its evidence.

For a new owned session, use a new queue, verify the installed/analysis hash, import the appropriate complete ledger, and record the actual session identity. Preserve every imported evidence/unknown record. Use bounded queries against observed addresses and valid function extents.

Export a complete ledger after meaningful research batches and before releasing an owned provider or approaching its hard timeout. Verify the export path, size, hash, evidence count, unknown revisions, and preservation of imported records. Close only the owned provider after in-flight work is settled. On a timeout, retain the last complete export and every later request/result and state exactly what was not exported or closed.

Acceptance: another session can resume from the recorded target, full ledger, query history, unresolved contracts, and verified ownership state without adopting an unknown process.

## 6. Phase B: close native contracts and supported resource ownership

Work on `CDISO-RE-02` and `CDISO-RE-03` first, while independent resource and runner work proceeds in parallel. Use the actual retained results instead of replaying the old query plan's superseded questions.

### Definition registration

Establish one coherent operation covering:

- Primary array capacity, count, ordinal metadata, expiry storage, limits, and allocations.
- Numeric-key insertion and name/hash publication, duplicate behavior, and all retained name-pointer lifetimes.
- Auxiliary registries and load order. Known dependencies include LocalStringInfoManager and MaterialMatchInfoManager.
- Record construction/decoding with a demonstrated success signal and validation of required fields.
- The valid startup phase and thread, before relevant dependent use/finalization, with the allocator and engine ownership understood.
- Derived-index finalization, including append/reset behavior and failure after mutation.
- A publication boundary and failure behavior that preserve existing registrations. If rollback is unproved, reject before publication or abort the controlled initialization.
- Durable per-package backing and routing when normal maintenance evicts a record or clears shared body data.
- Numeric/name lookup, restart, and persistence expectations.

Retained constraints: the selected header replaces primary storage; the materializer assumes a valid ordinal and does not establish admission; selected callbacks perform lookups against existing records; derived-vector growth is not primary-registry growth. Some failed auxiliary conversions store `0xffff`. Normal decoder return alone is not sufficient proof of successful parsing.

The owner has 16-bit ordinal/count fields. Establish exact bounds and refusal behavior; do not assume another slot is representable. Do not infer a complete engine structure from isolated writes.

Use a proved native insertion operation if available. Otherwise, justify a narrow adapter against complete storage, map, lifetime, and failure contracts. A mock registry, raw pointer write, count increment, or second header call cannot close this gate.

### Resource discovery and donor detachment

For each resource family in the admitted item graph, establish discovery/enumeration, identity/hash lookup, byte delivery, parsing, actual use, cache behavior, and retirement. Include model, material, texture, icon, localization, auxiliary definitions, and any required sockets, physics, animation, or effects.

Use exact private resource names and identities. Rewrite only understood references and retain unknown edges. Inspect both explicit paths and implicit native identities. Deduplication may share immutable storage after validation, but not mutable ownership or game-visible identity.

Existing Loadouts private PAC/material/prefab/DDS evidence is a lead. It does not prove the entire CDMW item or complete mesh-plus-private-texture use. Keep source/build receipt identity and visual acceptance separate.

Concrete retained leads include native `character/bin__/*.pappt` enumeration, provider visibility and ordering, duplicate handling, negative caching, the mesh member `+0x68` name writer, actual socket manager dispatch, insertion, cleanup, and mapping lifetime. The examined PAPPT loop skips its third serialized string; changing that field alone does not prove private socket resolution.

Complete low-risk copies/reference rewrites for proven formats while engine research continues. A resource family needed by the chosen item cannot be hidden or silently borrowed to claim full donor detachment.

### Architecture decision and first implementation

Record a positive `CDISO-DECIDE-01` decision before exposing the new capability. Reuse the existing UUID/binding ledger, compatibility services, loader/session leases, source guards, cancellation, and provenance.

Start with packages loaded at game startup. Updates take effect on the next start. Live package hot reload is not required for this first route; ordinary cache eviction and rematerialization remain required.

Keep packages data-only. Change package/protocol metadata only when a real consumer requires it, and update existing consumers/tests. Preserve existing composed backends and their stated limits. Never silently route an independent request through composition.

Implement the smallest usable native item and resource graph, then two same-donor items. Keep capability admission false until its actual supported path and required live checks pass.

## 7. Phase C: unattended Windows game runner

### CDRUN-AUTO-01: implementation shape

Use a thin development CLI and existing service boundaries. Proposed entry point: `scripts/run_cditem_device_tests.py`, with focused supporting modules and tests chosen after inspecting existing owners. This is a proposed file, not a command that already exists.

Reuse supported CDMW launch/profile/backup services and native session host. Reuse Windows interop patterns where valid, but do not assume a mesh-child input helper already understands a game window. Production UI behavior remains in its current owners; slow work stays off the UI thread.

The runner needs inspect/preflight, execute/resume, and report behavior. Its default inspection mode must send no input or start a game. An execution manifest names exact packages, profile, save arrangement, artifact hashes, allowed actions, and timeouts. It is not a permission bypass or a substitute for native guards.

Bind every action and receipt to a unique run ID and the verified game PID, creation time, executable path/hash, window, and session. Refuse stale/reused PIDs, an unexpected replacement process, changed inputs, or a mismatched installed runtime. Serialize profile changes and installation under the existing leases.

Implement and validate target-window capture. `scripts/window_frame_capture.py` is verified for CDMW, not automatically for Crimson Desert. Prove fresh game pixels are visible to the agent. If capture is black or unavailable, establish another supported capture route. Expose images through the local image viewer or an actual working bridge; the existence of a PNG is not visual inspection.

Use correctly declared Windows x64 input structures, verify injected event counts, and release every button/key the runner pressed on exit. Verify the current foreground PID/window immediately before input. Compute positions from the observed client rectangle and current DPI. Do not click unrelated windows, use blind key spam, or turn a requested focus change into proof that focus succeeded.

### Required state transitions

| State | Required observation and next action |
| --- | --- |
| Preflight | Baseline, ownership, file guards, usable desktop, capture capability, and permitted test context are ready. |
| Launching | Start through the existing supported Steam/controlled launch route. Bind the newly created game process and retain host/runtime readiness evidence. |
| Title/menu observed | Confirm the owned window and current screen. Runtime readiness at 100% is not a title-screen or gameplay observation. |
| Input activation | Bring the verified window forward; observe it; move the mouse inside a safe client-area position and click when appropriate. |
| Keyboard/menu ready | Capture again. If the click advanced the screen, handle that new state. Otherwise verify the E action is available, then send E down/up once and observe the result. |
| Test-save selection | Follow the observed menu to the exact disposable test save. Verify slot identity and avoid a guessed Continue target. |
| Loading | Wait on bounded state/progress observations. Do not send gameplay input during an unrecognized loading or modal state. |
| Gameplay ready | Confirm the intended save/character and fresh world/character state tied to this run, with visible evidence. |
| Scenario running | Run one explicit scenario, check its assertions, collect evidence, and finish input before the next scenario. |
| Cleanup/recovery | Retain results, close only the owned process, settle writers, restore only owned state under the tested contract, and verify the result. |

Unknown screens, lost focus, user intervention, stale telemetry, a missing window, or an unexpected process lead to a recorded pause/failure and release of held input. Resume only after new evidence establishes the state. A click that already advanced the menu must not be followed blindly by E.

Use monotonic, configurable per-state deadlines. Separate slow source verification from menu and load deadlines. Record initial measured timings and bounded headroom. A large verified-input scan must not look like a hung menu. Automatic retries require a diagnosed recoverable cause; stop repeated identical attempts without new evidence.

Offline runner tests must exercise state transitions, click-advances-menu, gamepad-prompt activation, focus loss, wrong/reused PID, variable loading times, stale receipts, unexpected dialogs, input release, timeout, and recovery. Synthetic input tests establish runner policy only. Live acceptance remains separate.

### CDRUN-SAVE-01: disposable saves and preservation

Establish the actual route before loading a test save or changing persistent gameplay state. The existing CDMW save-backup and copied-evidence services do not redirect live saves, prove their origin, or automatically restore them.

1. Discover the live save root, account/slot membership, autosaves, shared indexes/metadata, and writes performed during startup/loading.
2. Establish a supported disposable save/profile root if available. Prove that the game actually reads and writes it.
3. If a separate root is unavailable, design a bounded, journaled test-context exchange and restoration route. Validate it on independent copied fixtures first. Identify every affected file and writer; a copied manual slot alone is insufficient.
4. Retain immutable recovery copies with complete inventories and hashes. Use independent files, not links back to live data. Keep each experiment's inputs and post-attempt outputs separate.
5. Inspect Steam Cloud upload/download behavior and its timing. Establish a concrete plan that prevents test writes or later synchronization from replacing original state. Preserve current settings and do not silently change account-wide cloud behavior.
6. Verify the chosen test context, backup, profile, package bindings, and producing context before each run. Fresh hashes prove bytes, not save origin or compatibility.
7. Close the owned game and settle relevant writers before taking a consistent save-file snapshot, exchanging the test context, or restoring it. Compare current files with the runner's expected state. Preserve unexpected or concurrently changed files and stop restoration instead of overwriting them.
8. Verify exact restoration of the original inventory and bytes, including initially absent paths, plus any applicable cloud state. Retain test results and recovery material.

Changes needed for this development workflow must be explicit, tested code. Do not weaken existing save/protocol checks to make an experiment run. Do not invent a save migration or edit original save contents to repair a missing provider.

If safe save containment is unresolved, continue static work and offline runner development. Title-only automation may continue only after its startup writes and cloud effects have a verified preservation/recovery route. Otherwise mark all game launches blocked by that exact missing contract. Mark load/persistence scenarios blocked until their own containment is established. If the issue is native save routing, place it in the reasoning handoff; if it is account access, cloud state, or an unavailable desktop, classify it operationally.

### CDRUN-LAUNCH-01: automation acceptance

Complete at least two consecutive fresh game process launches that:

- start from no owned game process;
- handle the initial gamepad-prompt/mouse activation condition;
- load the selected test save and confirm gameplay;
- perform one small verified scenario, which may use an existing stock item or another harmless baseline action so runner acceptance can finish independently of native registration;
- capture evidence and complete verified cleanup;
- require no user clicks or key presses.

Fresh game starts do not require forcibly closing another user's Steam client. Record whether Steam was already running. Test a cold Steam route only when the owned setup permits it.

The first live run validates/calibrates the automation, including capture and safe click locations. Agent-driven observation is allowed; it does not require the user to operate the menu. Two passing startup cycles close only the runner gate, not native item isolation.

## 8. Phase D: scenario driver and native integration

### CDRUN-SCENARIO-01

Implement a small set of measurable game actions for the chosen item family:

- acquire the exact new item;
- inspect inventory name/icon and numeric identity;
- equip, observe supported appearance/behavior, and unequip;
- cause or observe normal resource/record unloading and rematerialization;
- save the intended disposable slot, restart, and reload the correct bytes;
- repeat after package updates, removal, and restoration.

Use an existing verified UI or native inventory route. If an acquisition or equipment API is missing, establish its own arguments, phase/thread, ownership, limits, and result contract through bounded research before calling it. The existence of a Loadouts stock-item action is not proof that arbitrary new IDs work. Current read-only source inspection confirms that its Prepare path requires an already owned exemplar of the exact selected WORD in carried bank 1. RH-05 retains the first-instance acquisition question; no native guard was removed or call admitted.

Optional shop/group integration must remain separately identified. A test-only acquisition convenience must not conceal a combined shared-table dependency in the claimed independent package. Avoid turning the runner into a second product or broad gameplay bot.

Bind requests/results to the current run and exact item. Record both the action result and observed state. A process still running, a returned function, an image file, or a save hash change cannot stand in for the corresponding feature assertion.

Before the first native mutation, independently review the complete proposed call/storage contract. Begin with one minimal item on the disposable context. Expand after the first milestone passes. Verify the real parse result, both lookup maps, required auxiliary references, stock controls, and durable backing. Test normal cache eviction separately from restart.

## 9. Required device and feature matrix

Run the smallest positive slice first, then the full applicable matrix for every resource/item family admitted into the final scope. Record a result for each row. A blocked family remains visible.

| ID | Scenario | Required evidence |
| --- | --- | --- |
| T01 | Baseline stock game/profile | Intended stock controls resolve and appear correctly; starting artifact/profile/save identity is known. |
| T02 | One independent item A | Numeric ID and name resolve; required references are valid; original records remain intact. |
| T03 | Actual private resources | Expected package bytes reach the native resource path and are used for the model/material/texture/icon/name and other required resources; retain visible checks. |
| T04 | A alone, B alone, A+B | Same-donor items keep distinct identity and intended appearance/behavior. |
| T05 | Reverse activation order | Both items and saved identities remain stable; no arbitrary winning provider or renumbering. |
| T06 | Compatible external contributions | External rows/resources and sampled stock behavior remain effective. Use owned test-mod copies; preserve real installed mods. |
| T07 | External donor definition/resource change | The donor change remains effective while private items retain their intended independent result. |
| T08 | Duplicates and unsupported inputs | UUID/ID/name/hash/path conflicts, missing dependencies, malformed data, unknown builds/hooks, and relevant limits refuse before unsafe partial admission. |
| T09 | Failure during preparation/publication | Fixture and controlled-probe evidence covers actual failure boundaries, cancellation, allocation/initialization failures where safely testable, and recovery. Do not fabricate a dangerous live failure. |
| T10 | Normal eviction and rematerialization | Observe nonresidency and a later successful reload from A's own backing, with B/stock unaffected. A restart alone does not pass this row. |
| T11 | Save, exit, restart, reload | Correct objects and state return from the intended saved bytes with identical bindings. |
| T12 | Name update and asset/behavior update | Test these separately. Saved item identity stays stable and the intended supported changes take effect. |
| T13 | Disable/remove A while retaining B | B remains correct; A follows the explicit verified missing-provider policy. No identity is reused. |
| T14 | Reinstall A | Retained identity resolves to A, with observed save behavior. Do not claim recreation of state discarded by an intervening save. |
| T15 | Load absent-provider save without intended saving | Retain exact input/output and detect autosave or shared metadata changes; record observed object state or refusal. |
| T16 | Save with provider absent | On an established disposable context, record the actual outcome, writer/finalization evidence, changed/unchanged/missing members, and post-attempt bytes. |
| T17 | Restore provider and load the post-attempt bytes | Load exactly T16's retained output. Restoring the original pre-removal save does not pass this scenario. |
| T18 | No shared composition | Inspect outputs and actual routing. No combined replacement definition/index/mount/carrier implements the independent claim. |
| T19 | Automated startup and recovery | Gamepad prompt, click/E, load, focus-loss/timeout handling, and two successful unattended cycles have run-bound evidence. |
| T20 | Final delivered artifacts | Essential positive, refusal, save/reload, and automated startup checks use the exact packaged executable and native files supplied to the user. |

A refusal passes only its explicit refusal criterion. It does not convert unexecuted persistence or visual scenarios into passes. If a missing-provider policy does not satisfy the feature plan's required behavior, keep the relevant task open and report the limitation.

Reuse `scripts/capture_virtual_save_evidence.py` and `virtual_save_experiment_protocol.py` for the six-stage absent-provider evidence where applicable: baseline, absent_before_load, absent_loaded, absent_saved, restored_before_load, restored_loaded. The tools operate on copies and do not prove gameplay or save production. Preserve failures, missing files, autosaves, and unknown producer/origin states rather than filling them with expected values.

Every scenario ends as `passed`, `failed`, `blocked`, or `not_run`. Include assertions, observations, and the reason for any missing check. Distinguish source, synthetic, native, visible, and persistence evidence.

### Separate CDMW monitor check

When two equal-scaling physical displays are available, complete `WMDPI-06` with CDMW's Mesh window closed and open, retaining current source/helper identity. It needs CDMW, not Crimson Desert. Follow its owning plan; do not change display scaling or substitute same-monitor movement. If unavailable, report the hardware gap separately and continue CDISO work. The deferred optional DPI optimization is not newly required.

## 10. Evidence, crash recovery, and review

Each run directory needs a concise human report and a machine-readable result. Include:

- run ID, timestamps, model/session owner, command arguments and exit codes;
- source commit and dirty source manifest, package UUIDs/hashes, bindings, profile and generation;
- exact game, launcher, bootstrap, CDMW executable, native runtime/helper hashes and build provenance;
- current process identities, owned window/client geometry/DPI, state transitions, input sent, and result observations;
- target-window screenshots and native/log receipts with freshness and provenance;
- test-save inputs, recovery material, post-attempt outputs, and lineage limitations;
- every scenario's assertions and outcome, plus cleanup/restoration inventory;
- remaining questions and links to the reasoning/operational handoff.

Use bounded reports and image sets. Do not commit machine assets or a full game-data dump. A report must be readable without replaying an entire terminal transcript. The reviewer can request bounded raw evidence for a disputed claim.

Persist the active run manifest and a write-ahead journal before each installation or save-context exchange. Record the original, intended, and observed states. On restart, inspect unfinished owned runs before permitting another launch. Revalidate every recorded PID, process creation time, and file state; resume or recover only that run. Provide cancellation and a bounded supervisor or equivalent recovery mechanism for held input and interrupted cleanup. A connection loss, terminated runner, or stalled Codex session must not start a second competing game process. A `finally` block alone does not meet this recovery requirement.

On crash or timeout, retain evidence before recovery. Stop input, release only held inputs owned by the runner, and attempt ordinary close of the owned game. Force termination is reserved for a verified hung owned process with preserved evidence. Recheck PID and creation time. Do not kill an unrelated game, Steam, Ghidra, or helper process.

Retry after a concrete diagnosis and an explicit change or recoverable condition. If input/capture fails, do not diagnose it as item corruption. If native data fails, keep that separate from menu automation.

`CDRUN-REVIEW-01` requires an independent source/evidence review of registration, resources, save containment, runner state transitions, negative cases, and the exact claimed support. Reviewers must inspect decisive evidence and relevant code, not only the implementer's summary. Fix supported findings and rerun their focused checks. Save unresolved reasoning issues as described below.

## 11. Higher-reasoning handoff and stopping rules

Maintain [cditem-astra-pro-handoff.md](cditem-astra-pro-handoff.md) as the compact review entry point. It is initially populated with inherited open questions and retained sources; this does not mean Sol has already exhausted them.

Escalate a specific question when:

- a needed native call/layout/lifetime contract still cannot be justified after distinct evidence-driven attempts;
- disassembly, decompilation, or runtime results contradict each other and the contradiction blocks a safe implementation;
- a reproducible failure survives targeted diagnosis and review without an explained cause;
- independent review finds an unresolved ownership, publication, cache, or persistence gap;
- a supported scope or missing-provider decision cannot meet the original goal without a new technical answer.

After repeated attempts that no longer reduce the named unknown, write the handoff rather than repeating the same query or changing an unsupported assumption. Three distinct unsuccessful hypothesis tests are a useful checkpoint, not an automatic abandonment rule. Continue when there is a concrete new discriminating test and justified scope.

Each review item must contain:

1. ID, linked `CDISO/CDRUN` task, status, priority, and one exact question.
2. Why it blocks the next operation and which acceptance rows are affected.
3. Current source/dirty-state, binary/package/profile/save identities.
4. Proven facts, hypotheses, counterevidence, and bounded raw evidence paths.
5. Attempts with commands/query IDs, actual results, and what each ruled out.
6. Candidate explanations and the smallest next query or controlled experiment.
7. Relevant code/patch location and build/test commands.
8. Game/REA process ownership, installed test changes, save/restoration state, and remaining cleanup.
9. Full ledger export path/hash/counts and any results newer than that export.
10. A direct restart instruction for an Astra or Pro session.

Use `reasoning_review_needed` only for a real reasoning question. Label unavailable tools, owned/busy sessions, missing hardware, locked desktops, credentials, or unresolved external access as operational blockers with a concrete resume condition. Save-isolation uncertainty may contain both categories; separate them.

Saving a handoff does not close the blocked feature task or finish the overall goal. Continue every independent useful task. Do not change the user's model defaults or invoke another paid model silently. The saved packet is ready for the user's chosen later review session.

Before ending any execution session, complete `CDRUN-HANDOFF-01` by accounting for every unresolved row and every running process. If nothing remains, state that no escalation is needed and retain the resolved question history.

## 12. Final build, delivery, and completion decision

For `CDRUN-DELIVERY-01`, first finish focused tests at their actual owners. Use the project virtualenv and unique pytest base temp under the system temporary directory. Reuse unchanged passing evidence; broaden only for a changed cross-cutting contract or the final requested readiness check.

Representative existing commands, to select after reading the current test matrix:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_independent_item_compatibility.py -q --basetemp "$env:TEMP\cdmw-cdrun-<run-id>"
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader_native.py -q --basetemp "$env:TEMP\cdmw-cdrun-native-<run-id>"
.\.venv\Scripts\python.exe scripts\generate_ui_localization_manifest.py --check
```

Replace `<run-id>` with the actual unique run ID. These examples do not replace the additional exact tests required by changed identity, resource, save, or runner behavior.

Build relevant native components after their source contracts change and validate their provenance. For the final requested portable delivery, use the normal release builder:

```powershell
.\build_pyside6_app.ps1 -Mode onefile -BuildProfile release
```

The final release build is part of execution/delivery, not this documentation-only checkpoint. Preserve the previous executable first. Keep the current application version unless the user separately requests a version change. Do not tag, sign, push, or publish.

Verify packaged member completeness, runtime/helper provenance, bundled helper behavior, and default/Mesh startup through the existing builder gates. Repeat T20 using the exact delivered binaries; a source-tree run cannot certify a different packaged runtime. Retain the artifact's absolute path, size, SHA-256, source manifest/commit, build log, installed test identities, and rollback path.

Update the relevant feature docs, test matrix, and supported-scope description. Add user-visible changes under Unreleased where needed and synchronize localization only for actual semantic changes. Reconcile existing CDISO checkboxes, CDRUN checkboxes, shared progress, and the reasoning handoff. Commit only completed task-owned changes.

Final outcome must use one of these meanings:

- **Full goal verified:** all requirements of the authoritative feature plan and the execution/delivery gates are satisfied. A working first family or other subset remains a verified partial delivery until the remaining required scope is completed, unless the user explicitly changes the goal.
- **Verified partial delivery:** useful implemented changes and their exact tests/artifact are supplied, while remaining required work is clearly listed and stays open.
- **Blocked with retained work:** the next necessary operation has a concrete blocker; completed independent work, evidence, cleanup state, and review/resume packet are saved.

A new .exe, two successful launches, or a saved escalation file alone cannot justify full completion. Report the separate WMDPI hardware gap if it remains.

## 13. Source and restart map

Paths are absolute so another local session can open them. Re-read current source rather than relying on retained line numbers.

| Purpose | Source |
| --- | --- |
| Feature contract and current task state | `D:\CLAUDETEST\CDMW Full\beta-progress\cditem-conflict-isolation-plan.md` |
| Shared completed work | `D:\CLAUDETEST\CDMW Full\beta-progress\progress.md` |
| Last verified ordinary build | `D:\CLAUDETEST\CDMW Full\beta-progress\test-build-readiness-plan.md` |
| Native registration constraints | `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\analysis\registration\registration-evidence.md` and `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\analysis\registration\request-plan.md` |
| Latest socket consumer evidence | `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\analysis\sockets\socket-consumer-evidence.md` |
| Earlier socket reviews | `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\analysis\sockets\independent-socket-cache-review.md` and `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\analysis\sockets\independent-sidecar-review.md` |
| REA ownership/restart | `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\session-handoff-20261017T1802Z.md` |
| Retained full ledger | `D:\CLAUDETEST\CDMW Full\.work\tasks\2026-10-17-cditem-conflict-isolation\native-r3\rea-checkpoint-contracts.json` |
| Capability/ownership assessment | `D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_isolation.py` and `D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_references.py` |
| Package compatibility/identity | `D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_compatibility.py`, `D:\CLAUDETEST\CDMW Full\cdmw\services\independent_item_install.py`, and `D:\CLAUDETEST\CDMW Full\cdmw\domain\new_item\allocation.py` |
| Loader/session/guards | `D:\CLAUDETEST\CDMW Full\native\cdmw_virtual_loader\README.md`, with runtime, session, bootstrap and protocol sources in `D:\CLAUDETEST\CDMW Full\native\cdmw_virtual_loader` |
| Current product launch/save contract | `D:\CLAUDETEST\CDMW Full\cdmw\ui\new_item\VIRTUAL_LOADER.md` |
| Save preparation/evidence | `D:\CLAUDETEST\CDMW Full\cdmw\services\virtual_loader_saves.py`, `D:\CLAUDETEST\CDMW Full\cdmw\services\virtual_save_experiment_protocol.py`, and `D:\CLAUDETEST\CDMW Full\scripts\capture_virtual_save_evidence.py` |
| Existing input/capture candidates | `D:\CLAUDETEST\CDMW Full\tools\mesh_harness\win32_input.py` and `D:\CLAUDETEST\CDMW Full\scripts\window_frame_capture.py` |
| Canonical checks | `D:\CLAUDETEST\CDMW Full\docs\test-matrix.md` |
| Remaining monitor check | `D:\CLAUDETEST\CDMW Full\beta-progress\window-move-dpi-smoothness-plan.md` |

The retained R3 ledger has 95,576,962 bytes, SHA-256 `ad062cc74a59cb49ac7d73076ee1c403319bfb32b4c062a334649a3f73e70c41`, 1,200 evidence records, and 89 unknown revisions across 13 IDs. Those are historical export facts. Size/hash it before import and preserve any newer owner ledger.

### Start/resume instruction

Execute this plan from the current filesystem state. Start with CDRUN-BASE-01 and ownership, then work on native registration/resource questions and the unattended runner in parallel where ownership permits. Complete offline preparation, establish the test-save route, and perform the controlled device tests as their gates become ready. Keep feature completion in the existing CDISO plan and completed events in progress.md. Save any unresolved reasoning question in the Astra/Pro handoff, retain operational blockers separately, and continue unaffected useful work. Finish with exact artifact/evidence/cleanup status rather than another proposal.

### Planning verification

To complete CDRUN-DOC-01, verify task IDs, links/source paths, the unchanged ten open feature tasks, an honest initial handoff, safe startup/save handling, the paired progress entry, and a task-scoped diff. No game launch, application suite, native build, or packaging is required to verify these documentation changes.

## Execution checkpoint, 2026-10-18

Completed native continuation: the fourth owned provider imported all 1,278 prior evidence records/95 unknown revisions and retained every canonical row in `workspace/reports/cditem-execution/20261018-native-review/batch4-registration-boundary/provider/rea-complete-final-ledger.json` (96,795,800 bytes; SHA-256 `1f9817603690170007cd5fbe690836d0d4ecef371f8826d27b18d93d43e3a3ad`; 1,289 records/97 revisions across 16 IDs). Supported target/session close and graceful shutdown passed at 03:32:32.075 UTC; 03:33:57.1009448 UTC verification found no owned processes/project locks, session open:false and unchanged project metadata. New source proves the ignored normal decoder failure, object-only unwind cleanup, copied/borrowed reverse-name consumers and concrete indexed resource provider. First-instance acquisition is separately unresolved at RH-05. No production source, delivered executable, game, installation, archive or save was changed by this continuation.

The paired CDRUN entries in [progress.md](progress.md) record completed baseline/research continuity and scoped offline substeps. The native feature tasks stay in their original CDISO owner. Detailed attempts and current blockers are in [the handoff](cditem-astra-pro-handoff.md).

- Baseline and recovery: `workspace/reports/cditem-execution/20261017T231206Z/baseline.json`, `baseline-context.json`, `source-guard-refresh.json`, `original-saves/`, `original-bookkeeping/`, `original-bin64-settings/` and `rollback/`. Source guard refresh passed all 234 files / 151,455,090,976 bytes; all four prepared files match. Existing save/profile/installed-loader bytes are preserved.
- Available development entry point: `scripts/run_cditem_device_tests.py`; default inspect/replay remain zero input/launch. Exact-manifest preflight/execute/resume/cancel bind an already supported-launched live context. Process-bound F/SPACE/fixed 1.25-second hold, exact exit confirmation and bounded recovery passed source/independent checks and two clean real stock cycles without user input.
- Selected readiness: retained earlier 106 distinct nonvisual cases plus focused final owners: runner 105, controller CLI 5, offline/live saves 30/66, setup 17 and execution 87. Independent source/recovery and both actual retained-cycle audits passed. Unchanged broad suites were not rerun; native-item and packaged-device proof remain separate.
- Save/Cloud evidence: all four contexts restored the original 26 files and whole-root metadata exactly before Cloud. Consecutive clean cycles3/4 finished seven actions each, no failures, and nine/eight released scopes. Exact four-file setup is restored; Cloud is ON/Up to date and Steam minimized. Final inventory/bytes remain exact; normal Cloud synchronization changed eleven retained file timestamps, with no post-sync repair. Final source/archive and installed-state checks pass.
- Profile preparation: current-compiler four-package candidate remains read-only and unpublished. The separate temporary stock setup was used only for controlled cycles and has now been recovered through its exact four-file contract. Original profile generation `bbf65bdaf90146ee835b1ff2093ab7c1` is restored; no source archive changed.
- Independent source review: `workspace/reports/cditem-execution/20261018-runner-review/review.md`. Seven findings were corrected. Approval review rejected deletion of the owned TEMP alias fixture, stating only `blocked by policy`; the exact retained path is in that report, with no workaround attempted.
- Native research history: four owned pinned batches preserve complete imported history. Latest final export is 96,795,800 bytes / SHA-256 `1f9817603690170007cd5fbe690836d0d4ecef371f8826d27b18d93d43e3a3ad`, 1,289 evidence/97 unknown revisions across 16 IDs. All four providers closed gracefully; final 03:33:57.1009448 UTC verification finds no owned/related PIDs/project locks and session open:false. New fourth-batch source and independent review establish normal false-decoder publication, object-only unwind cleanup, copied/borrowed reverse-name consumers and the concrete indexed resource provider. Formatter escape, coherent publication/failure, durable package backing/private index ingestion and retirement remain open. The reference stock Add route requires an already owned same-WORD exemplar; RH-05 separately retains the first-instance question. The linked handoff contains exact reports/hashes, corrected and failed attempts, and next discriminating contracts.
- External installation: the other chat installed sealed Loadouts v7.192 ASI-only during execution; its SHA-256 is `12b45299438009eda376cc8a77c17fa82bb8a1f55a53a834e3f354960c372b57`. That change is preserved and invalidates reuse of the initial foreign ASI pin for a later run.
- Delivery result: normal onefile release passed at source revision `98ae737c46cb8967cc42d15c7f5dc02680920e13`. Portable size 175,507,262 bytes; SHA-256 `051e0e8c2a3420c2d5e578ed0d1471c9858f770a5d13266124e368b339ff8e7f`. All 586 members, native probes/provenance and default/Mesh Builder startup pass. Six embedded service modules and fourteen catalogues match source; delivered ASI/session bytes equal the real stock-cycle payloads. Full native T20 remains blocked. Exact receipt, rollback, original failed verifier and corrected proof are retained in the baseline evidence directory.

Verified partial delivery: T01/T19 have actual stock launch/load/world/exit and two clean consecutive source-runner cycles. Source/embedded-code equivalence and identical delivered native payload hashes are verified; the actual packaged executable passes startup/native probes. Original saves/setup/Cloud and process cleanup pass with eleven honest post-sync timestamp deltas. Native positive/refusal, acquisition/equip/coexistence/cache/saved identity and full T20 remain blocked by RH-01/RH-02/RH-03 and the first-instance acquisition prerequisite RH-05. Their ten original feature parents, scenario, full review and full delivery gates stay open. Handoff and accurate partial-delivery reconciliation are complete; the full goal is not complete. WMDPI equal-scaling hardware proof remains separate.
