# CDMW .cditem execution goal and unattended device testing

- Plan ID: `CDRUN`
- Created: 2026-10-18, Europe/Stockholm.
- Status: Verified partial portable stock delivery, actual private native cache/eviction/rematerialization and independently audited closure/restoration. Central registration/resources/first ownership and full native scenario/review/T20 delivery remain open; execution continues.
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

### Updated test-risk preference, 2026-10-18

The user explicitly accepts broken saves or a required game reinstall and asks for speed, automatic testing/deployment within this task, and no questions that stop the work. This supersedes repeated save/game-data preservation routines for future experiments. Reuse prepared inputs and the existing test setup; run focused checks for the behavior being changed, and reserve full preservation/identity audits for evidence that actually needs them. Record failed attempts and observed results honestly. Coordinate shared game/input and provider ownership with the other chat so both can continue useful work. Native independence and final artifact/scenario acceptance still require their actual results.

### Current manual testing preference, 2026-10-18

The user is home and will operate Crimson Desert menus/gameplay for the next tests. Continue coding, reverse engineering and offline checks; when a ready candidate needs confirmation, provide short exact actions, expected result and information to report back. The latest direct instruction grants full authority to close or force-close Crimson Desert without asking the user, with chat coordination to settle any active measurement. This closure authority supersedes the earlier prohibition on closing the game; it does not change the manual menu/gameplay preference. The accepted save/game-data/reinstall risk and request for automatic work remain in force. Retained unattended evidence remains valid for its tested scope; new manual runs must be labelled honestly.

### Current gaming hold, 2026-10-18

The user is going to play a game and explicitly requests no starting Crimson Desert for now. Continue all useful coding, retained research, offline tests and packaging preparation. Keep live launches/tests and shared game/install/input/closure activity on hold; both peer chats have acknowledged the instruction. Existing automatic testing and close/force-close authority remain available after the human directly releases this hold. The new B63 caller refuses every game-mutating entry point until that release is reflected in reviewed/re-frozen code and a fresh peer handover. The overall execution goal remains active.

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
- [x] **CDRUN-DELIVERY-01C:** Exposed and independently verified the portable device command, rebuilt, and completed the inspected guarded stock load/world/confirmed-exit baseline using the exact delivered EXE, with independently audited original-save/setup/Cloud cleanup. Image pauses/refusals are retained; full native T20 remains separate.
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

Verified portable stock delivery: normal release at embedded revision `ce0ab5f5a369b85c8dec14cdc32d48b496b21598` is 175,520,265 bytes, SHA-256 `5f3483b898de1a9edd0cae38590fac9139c92270768ba84a7757545e20c9148b`. All 586 members, twelve Python joins, fourteen catalogues, four native payloads, default/Mesh startup and four actual safe portable probes pass. The actual delivered EXE completed exact copiedslot0 load, real forest/world/HUD observation and confirmed normal exit:7 successful actions,13/13 released scopes, zero action/cleanup failures. Three no-input image pauses and the earlier cancelled focus refusal remain retained; each decision was Root-inspected, so this is not a pause-free or general unattended classifier claim. Independent receipt/pixel/policy/cleanup audits pass. All 26 originals and metadata were exact before Cloud; all 4 setup files and foreign runtime/bootstrap remain original. Cloud is persisted ON/Up-to-date and Steam minimized; original payloads/inventory still match after 8 normal file timestamp deltas/0 directory deltas, without repair. Full 234-input/151,455,090,976-byte afterguard passes. `CDRUN-DELIVERY-01C` is complete; RH-01/RH-02/RH-03/RH-05, all 10 original feature parents and full native scenario/review/T20 delivery remain open. Passive 13–22 findings and actual attempts are in the existing Astra/Pro handoff. Evidence: `workspace/reports/cditem-execution/20261018-packaged-runner/`, `20261018-packaged-baseline-2/` and the existing native-review folder. The full goal remains active. The later idle SDK was closed before target open/import/native query when a new foreign owner acquired the project. Passive 24 proves default S+0x10 true is a refresh return, not completion. Those actual outcomes and restart conditions are retained.

The CURRENT complete restart ledger remains native batch32: `workspace/reports/cditem-execution/20261018-native-review/batch32-native-lifetime-initialization/provider/rea-complete-final-ledger.json`, 96,845,868 bytes/SHA-256 `5dd3ff2566281ddaaaeb7d8b76b6dc6c2ca910c1ebca4b2bbc6b8cee047637b1`,1,292 records/97 unknown revisions/16 identities. B44/Manual52 now proves actual numeric lookup on the exact frozen376,320-byte ASI/SHA `e1e9606d81bb6c9c6948f93f03eb830b93bd103c4a04faafbb9f498dbe88e41d`: game3892/startup thread10248, callback/original return verified,6816 primary entries, four stock keys/ordinals/names resolved and four false/FFFF results. The9401-byte result/SHA `b90bf57f4063953426a17c3e981e7c1f29aa5785a67c6d1858eb6f20c55e65b7` re-decodes exactly from retained native bytes. False resolution remains distinct from unused key, as B46 proves. Sequential header equality is not atomicity/readiness/admission. The user closed normally; first restoration hit WinError5. A later unchanged supported cleanup succeeded, with fresh four-file original hash matches, preserved Loadouts198/meta and quiet game/host/profile transaction. The795-byte restoration receipt/SHA `d2f271dab5f18e8c57cb20d695b139cc4861287ef3a623e9394859c9d9e66098` and all initial failure material are retained. B52 adds bounded recognized Windows-lock retries with all-target ownership and quiet checks; the complete23 recovery tests pass. No permission bypass, game control or extra live run occurred during cleanup. B48 declared-count validation remains committed with31 focused tests/21 subtests and real retained-copy checks; B49 resource mode/helper fixture remains15 cases with actual native parsing unexecuted. B50 captures complete typed record construction/Bool decode/native release source,7704 bytes/1772 instructions: materializer returns status pointer and ignores decode Bool; decoder receiver is Reader, and name-map values are record numeric keys. B51 now passes actual native allocation/constructor/Bool decode/release for the real donor twice and existing package base1990055/perks1990056/57/58 on game18460/startup thread6452. All six have exact IDs/names/cursors, native release pointer-clear and36 joined steps, with zero issues. The private396,800-byte ASI/SHA `8ed057340cd2bb394979b0b18bee74bf70b033b284a34624a090e8aba951a4ca` passes240 isolated C++ checks,49 decoder tests,21 final manual tests and no-session/state0. All40 frozen candidate pins verify. Normal closure/restoration passed; fresh original four hashes/mtimes, preserved Loadouts198/meta and quiet game/host/transaction are recorded in `batch51-unpublished-item-decode/live-result-audit.json`. Restoration795 bytes/SHA `8952439e456bdd51f84dd33e6aaf8e62efdf8614369c48e6583c468fe6c40cab`. Shared slot explicitly released. This is unpublished-record proof; coherent registration/private getter/backing/resource/first-ownership contracts remain open. User owns game/UI input. RH-01 coherent primary/aux/map publication, RH-02 private getter/backing/name/rematerialization, RH-03 private resource visibility/lifetime and RH-05 first saved ownership remain open. The public175,520,265-byte ce0ab5f5 portable/SHA `5f3483b898de1a9edd0cae38590fac9139c92270768ba84a7757545e20c9148b` remains unchanged and excludes these latest Python fixes/private prototypes. Native admission=false; all ten feature/full scenario/review/T20 parents remain open.

B53 completes the selected native cache/name ABI: 677 physical bytes/189 instructions;7,880 isolated checks/124 genuine maintenance calls/five reverse callbacks pass with explicit clock/release helpers. Exact maintenance is WORD phase+60/modulo60, QWORD expiry<=clock and separate body-cache release. A conservative total-count ceiling65476 avoids scan wrap for all phases; unsafe65535/phase0 cycles in a bounded arithmetic model and was not executed natively. Reverse ABI is owner RCX/key-pointer RDX/output-pointer R8, with direct unchecked resident-name borrowing and existing-output precedence. Capture/fixture pins and the required private getter/stable-name/detour-unwind implementation are in `batch53-private-row-cache-lifetime/findings.md`. No game/provider/install operation occurred; Fast Start owns the peer measurement slot after Loadouts200 installation. Native admission=false; original feature/full scenario/review/T20 parents remain open.

B54 implements private getter/stable-name routing with exact full native entry guards, pre-execution14-byte patches and process-lifetime registered unwind storage.152 isolated checks pass, including14 Windows virtual-unwind boundary cases, two actual caught prefix traps, native stock passthrough, cold owned-name return and same-entry rematerialization after native maintenance with explicit fixture helpers. Initial FF25 resume failed actual unwind at getter+14; preserved first code/binary/log and corrected R11 transfer now pass. Engine allocation/decode is not executed in this B54 fixture; the next cache implementation must combine B51 actual native operations with immutable backing, checked publication and caller serialization. No game/install/provider action or new manual test occurred. Full details/attempts are in `batch54-private-getter-name-routing/findings.md`; native admission=false and original feature/T20 parents stay open.

B55 implements checked private cache ownership behind the typed routing callback: native Bool/cursor/identity gates before slot/expiry publication, resident hits, immutable-backing re-decode after eviction, all-slot cleanup preflight and stop/quarantine on uncertain ownership.214 checks/24 isolated cases pass, including an actual native constructor/decoder false path and native maintenance with explicit engine helpers. A release-reentry reproducer caught retrieval of a dying record; the busy guard/stop-before-sibling fix passes and original code/EXE/log remain retained. Real engine allocation/successful decode/destructor/game cache integration is still pending for this cache; B51 remains its separate positive ABI proof. Next is the exact integrated early-startup diagnostic; no new game/install/provider action occurred. See `batch55-checked-native-cache/findings.md`; native admission/full original feature/T20 parents remain open.

B56 freezes the integrated private getter/name/cache/real-maintenance diagnostic at412,672 bytes/SHA `0045b6ff4c16f69594392751ab70974a7708265392004a7a1bf3f1ce05898359`. Six isolated C++ modes/1,039 checks,133 strict decoder and29 manual-caller tests pass; exact ASI no-session/state0 and all73 candidate pins verify. The fixture executes actual native lookup/maintenance with explicit construction helpers; real engine construction through this integrated cache is not yet game-tested. The four existing private rows must each show checked cold decode/hit, stable owned names, native eviction, cold name without construction, rematerialization and explicit release with90 exact steps. Occupied keys includingFFFF, virtual-ordinal conflicts, source/hook drift and release reentry refuse. Typed/malformed result refusals retain raw evidence and allow cleanup. The new manual launcher is `20261018-integrated-cache-manual/CDItem cache test.cmd`; its21,069-byte manifest/SHA `4effa768d0d93aa75cfe324e0c1f995b86df1e363aa605db1a10499b154580f2` binds73 files. Fast Start owns the game/install/measurement/provider lane and has been sent the ready-candidate handoff request; no new game/install/close/input/provider operation occurred. The human now explicitly authorizes game closure/force-closure after chat coordination without another permission question. RH-01 coherent central admission, RH-02 ordinary reader lifetime, RH-03 resources and RH-05 inventory/persistence remain open; native admission/full feature/T20 remain false/open. Evidence/attempts: `batch56-integrated-private-cache/findings.md`.

B57 qualifies actual missing-key insertion and the shared native grow/rehash bodies with819 new physical bytes/233 instructions. 24 isolated cases/1,257 checks and48 actual insert calls pass for WORD numeric/DWORD name values, both mocked TLS heap selectors, empty maps, entry growth/copy/free,31-pair bucket rehash, distinct full keys with one hash and occupiedFFFF duplicates. Five additional native allocation-failure paths reach the exact fatal call arguments through explicit mocked delivery: new-node failure leaves a published bucket pair, empty-map failure leaves count2/null storage and rehash failure leaves count5/old3-bucket storage. A failed insert is not an atomic no-op; private preparation or verified whole-startup stop remains required. No engine heap/exception delivery/game insertion is claimed. The282,112-byte fixture/SHA `f0b399700920bdefe5a3e37e689969ce49b613a1a90ad6639b7b3258fcb57c16` and13,348-byte receipt/SHA `dac6100f516ee73e2e150851c6d2dbc1690a116c200862ebe5bad01f62eb8717` retain exact source,35 pins and actual preparation failures. B56 all73 frozen pins still verify; its game cycle awaits Fast Start's explicit measurement-slot handover. No game/install/close/input/provider action occurred. See `batch57-native-map-missing-insert/findings.md`; coherent central storage/phase/failure, ordinary lifetime, resources and saved ownership/full feature/T20 remain open, native admission=false.

B58 qualifies the actual ItemInfo name hash and a concrete native collision. The materializer calls CRT `_strlwr`, then the bounded byte-pointer/64-bit-length hash at141364780 and publishes its DWORD as the name-map key/hash. The1,412-byte body contains1,256 code bytes/359 instructions and156 bytes of3 jump tables; the initial all-instruction parser refused that data and corrected qualification retains it explicitly. 166,231 actual native hash calls match an independent byte reconstruction across alignment/length/padded-tail/private-name cases and a deterministic collision search. `cdi_hash_probe_59839` and `cdi_hash_probe_161356` both produce3155373675;65 composed native checks prove the second name insertion for1990059 returns the first1990055 mapping. Reject occupied normalized hashes before central publication; distinct strings alone are insufficient. Observed C-locale normalization is not game-locale proof. The7,689-byte receipt/SHA `e8b3e4ebbc9fbe26f364be35be67435ed3a577f0a6250527f751492d089014bf` pins23 inputs; prior B57/B56 pins remain exact. No game/install/close/input/provider operation occurred; Fast Start retains its measurement lane and B56 awaits actual game handover. See `batch58-item-name-hash/findings.md`; all original feature/full scenario/review/T20 parents remain open, native admission=false.

B59 rules out two neighboring routines as ItemInfo name readers: complete156/172-byte WORD numeric resolvers use different globals146d69ae0/146d69a70 and map+68, not ItemInfo owner146d69aa8/name map+38. The no-covering-unwind14880ddc0 target was refused rather than assigned a guessed API. Exact328 bytes/94 instructions and attempts are in `batch59-name-lookup-consumers/findings.md`;6,363-byte receipt/SHA `6825ec91bdcb8b2d3abbc42df03e65afdc9021f6647d0071ee796419b85b4811`. The legitimate main REA19776 owner acknowledged the queued finite query for the actual ItemInfo +38 DWORD reader/callers, anchored to writer14038b088; no Root provider query/adoption or broad common-hash scan occurred. Fast Start retains game/install/measurement and206 work; B56 all73 pins remain exact and its game cycle is deferred. No new game/install/close/input action. Native admission/all original feature/full scenario/review/T20 parents remain false/open.

B56/B60 now pass the actual integrated native private-cache cycle: run `cdrun-native-20261018T174647Z-fc95b29c`, token `07fb5ca7bd974c9e865cf7f6ec5c887d`, game13940/startup thread14780. All4 existing private rows1990055/56/57/58 at virtual ordinals6816..6819 complete2 genuine checked constructions,1resident hit, stable reverse names,1 controlled native maintenance eviction, cold name/redecode and1explicit release each, with90 exact joined steps and unchanged6816-count global headers. The exact412,672-byte ASI/SHA `0045b6ff4c16f69594392751ab70974a7708265392004a7a1bf3f1ce05898359` and89-pin controlled caller are verified;61 focused closure/caller tests pass. The caller sends no menu/gameplay input, posts owned WM_CLOSE then uses authorized birth-bound force closure, and restores the exact4 original bytes/mtimes. Fresh audit verifies205 foreign ASI/meta/startup OFF/ON backup and quiet game/host/transaction. The8,132-byte audit/SHA `a90f29e52702cae968dad7dc5ec2606b98cee85463f5c8a5d7387b0edb4f03e0` and2,099-byte release/SHA `017b0969dc838996bbb442638e8a653f7ebfcd181c998523796f664df6f8dab6` are retained; exclusive slot returned to Fast Start. This is private virtual-ordinal/forced-expiry cache proof, not central admission, native string-to-key lookup, natural scheduling/concurrent reader lifetime, resources or saved ownership. Actual attempts and finite negative provider-assist evidence are in `batch60-controlled-cache-startup/live-findings.md`; all10 original feature/full scenario/review/T20 parents remain open, native admission=false.

B61 implements immutable read-only native-map snapshots and typed identity preflight without source writes/native heap calls. 33 isolated cases/404 checks pass for both value widths, empty/actual rehashed maps, complete node/hash/value/counter joins, failed/malformed/changing reads, occupiedFFFF keys and existing/incoming name-hash collisions. Three actual native insert calls prepare fixture sources with explicit B57 helpers; no new game action occurred. The307,712-byte fixture/SHA `2c5b2d1ddcfe7dea04e0bbd8378dea7abe3079c0fa0ec902fa05250c95d74c9e` and4,829-byte receipt/SHA `d07c538ae3ea359b81e8ebf414230c219f1b2c782582d9297df91e6de5e0c589` retain16 exact inputs; all89 B60 pins remain exact. Source inspection rejects an unrelated hit-expiry refresh: ordinary getter resident returns directly, unlike the materializer's resident stamping path. Peer export1713/109 is separately hash-verified with1692→1710→1713 continuity; it is not promoted over canonical B32. Next is private native-heap map construction/readback/ownership before any central publication. See `batch61-native-map-snapshot/findings.md`; native admission/all original feature/full T20 parents remain open.

B62 implements the exact15-byte after-all-+60/before-first-+28 bridge at14fa45af1 against the complete596-byte/139-instruction dispatcher. 182 isolated checks pass:37 actual Windows unwind boundaries,4 actual caught SEH cases, all6 native dispatcher passes over149 fixture families, original return/completion/LastError, source guards and rollback/retention. Initial metadata restored RBX/RSI from the wrong frame at offset7; original code/EXE/log remain and3 fixed-establisher ranges correct it. The232-byte bridge deliberately clobbers only source-dead R11 for its return transfer, preserving other volatile GPR/XMM and replaying XOR. The281,600-byte fixture/SHA `b204e2eecdb4944ae2a57d0ed8cd7d7584d03109eb0f0313bea81cdd7dd10a5f` and10,220-byte receipt/SHA `1117b0b10b951c96eb73d5cebdc938f9e22a4217f2549c73d5430a8a57b103e3` pin34 inputs and real failed attempts. Family methods are explicit fixture callbacks; no actual game phase/all-reader exclusion or central publication is claimed. Next is a passive earlier-phase game observer with exact startup/callback/artifact joins; B60 late-callback proof is not substituted. See `batch62-native-prefinalizer-bridge/findings.md`; all original feature/full T20 parents remain open, native admission=false.

B63 implements the passive earlier-phase observer and a separately joined original callback. Eight native fixture cases/210 checks,80 strict decoder and32 caller tests pass, including actual different phase/callback threads and source/counter/controller/family/membership/missing-phase refusals. The421,888-byte private ASI/SHA `c81f0f16f14a5a51424e792256279dd64415d16ac235db54fb14ac43265d9142` remains inert/state0 outside a game session. Its62,432-byte candidate manifest/SHA `60ed83dc6bcb5fce917a1759fb27707a0fbc217d28233d64cc27e7cae07107b6` pins216 exact inputs, including unchanged B60/B62 evidence. The human is playing another game and forbids Crimson Desert starts for now. New caller install/launch/live-monitor/close/restore entry points explicitly refuse under this hold;6 cases verify refusal before any game action. No new game/install/input/closure/provider operation occurred. Actual earlier-phase readiness/membership, all-reader/failure semantics and central publication remain unproved; continue private map/storage code offline. Original failed fixture/decoder attempts and the direct-release/re-freeze/fresh-peer-handover requirement are retained in `batch63-native-early-phase-observer/findings.md`. Native admission/full feature/T20 remain open.

B64 implements completely unpublished typed numeric/name map preparation with cloned buckets/full12-byte nodes, preallocated final entry storage and exact native insert frames. 83 isolated cases/2,513 checks execute56 actual captured native inserts across both value widths/mocked heap/TLS families; existing full values/FFFF/indexes/caller counters and original source bytes remain exact. All five returned-null cloning positions clean up known private copies before insertion. Six post-native uncertainty modes quarantine without exposing/freeing guessed storage. Two additional native fatal paths leave partial private state (bucket pairs4/count3 or bucket count5/old3-bucket storage) while original maps remain exact/unfreed; terminal delivery is explicitly mocked. The334,848-byte fixture/SHA `fb6b571a261dce6e2cdcb59b5ca2b1365049875b2ba0b62073c559d21fe31cb4` and10,602-byte receipt/SHA `b4d8bdf5371d388777ce22fe6b738b1836557cab60828c9460a0621894e48c0b` retain36 pins and actual first/final attempts. B63 all216 pins remain exact and its live candidate stays explicitly on human gaming hold. No game/provider/install/input/closure/publication operation occurred. Paired preflight, genuine engine heap cleanup, primary/cookie/expiry/metadata joins, early exclusion/failure-stop, resources and saved ownership remain open; native admission/full feature/T20=false/open. See `batch64-private-map-preparation/findings.md`.

B65 qualifies the complete34-byte/six-instruction raw free leaf1413738b0 by closed control flow despite its absent PE unwind entry, reusing the exact105-byte allocator. 31 isolated cases/249 checks execute28 native allocations and29 native frees through explicit heap/TLS helpers; both families, sizes12/32/768, alignments0/4/16/64, selector127 and source-binding refusals pass. A selector-change witness proves free dispatch uses current TLS, so it does not establish cross-family cleanup. Two additional actual allocator fatal paths observe0xa0000002/flags1/count0/null through mocked terminal delivery. The274,432-byte fixture/SHA `60f6a1403c2983dfbca9077fd212d5b452962c3889c061ccf450acfa80729a11` and16,715-byte receipt/SHA `e7a6d49b67d5ebdf725713f4ec6340132df88b0d0e2ca903ff84037eccbad4e8` pin58 inputs. Actual engine heap/TLS/family stability and early readiness remain unproved. B64/B63 inputs unchanged; human gaming hold honored with no game/provider/install/input/close operation. Next wire exact heap helpers to unpublished private maps and preflight both maps before allocation, then join primary/cookie/expiry/metadata. Full central/resource/saved-ownership/native review/T20 remains open, native admission=false. See `batch65-native-raw-heap/findings.md`.

B66 couples both unpublished identity maps, preflighting numeric/name collisions, source/API/count/counter/ordinal shape before either allocates and deriving full key/name-hash/WORD-ordinal joins from the same definitions. 60 isolated cases/2,376 checks execute366 exact native raw allocations,466 raw frees and144 native inserts across both explicit heap/TLS families. Neither map is exposed on second-map copy failure, native-output/C++ uncertainty or any of3 actual native fatal child paths; both original maps remain exact/unfreed. Terminal delivery remains mocked. The313,344-byte fixture/SHA `26ca2ab378307764b15b14eb52351d2d982c9421d50b69bb148a410e939a3f20` and20,734-byte receipt/SHA `01534f1edc2576a448122cc9e24a446814df985b867a226ff84e094732f9a024` retain72 pins. B64 wording is clarified: uncertain owner cleanup never occurs, while the isolated mock arena resets at case teardown; this is not engine reclamation proof. B63 all216 pins unchanged and human gaming hold honored; no game/provider/install/input/close/publication operation occurred. Real owner/primary/cookie/expiry/metadata joins, engine heap/readiness/exclusion/failure-stop, resources and saved ownership/native review/T20 remain open, native admission=false. See `batch66-paired-private-identity-maps/findings.md`.

B67 recovers R3's already identified owner-argument native name callback1414e1d80->1414e1550, correcting the later overly broad unresolved-reader statement from a global-load-only search. Fresh544-byte/159-instruction capture matches the original9b64ed... source hash.36 isolated native calls/2,662 checks pass with exact hash, actual selected CRT copies/lowercase, full DWORD/cold-primary/output precedence/miss/empty/collision cases and explicit string/TLS helpers. It reads the passed owner+38 without a global-owner or primary-slot load; constructor-registered owner pointers and global dispatcher precedence still matter. The275,456-byte fixture/SHA `bbbf7b4a7dbf6f743c17ac7e3cffda05507e183e726bddc9ac7b280589dbefcf` and27,398-byte receipt/SHA `a24ce7528f6893e23a092d81440db18f5ab0f92004d6c37a9c0f32928a6aafab` retain95 pins and the real padding-build refusal/fix. B66/B63 inputs unchanged; gaming hold honored with no game/provider/install/input/close action. Actual engine string/locale/phase, global dispatch, coherent primary/map publication/resources/saved ownership/full native review/T20 remain open, native admission=false. See `batch67-retained-native-name-callback/findings.md`.

B68 implements immutable stock count/cookie/primary/expiry/eight-byte metadata/numeric/name/resident-key joins. 40 isolated cases/686 checks pass, with3 native calls preparing valid fixture aliases; capture itself performs no native heap/insertion/write. Canonical metadata ordinals, live name targets and resident leading IDs join, while compatible aliases/FFFF occupancy/cold slots survive. Full array/map/node/bucket/entry/header rereads reject observed changes and expose no partial result. The300,032-byte fixture/SHA `265f8844cc78ffafd5aaefeacfd4f460bd9d41ae4717814bd4d24402b0acfcad` and31,447-byte receipt/SHA `aca793846830438819ba2689eb191551dbdf4d37ff6838d23779d2ea8e64bc63` retain110 pins and the real C3538 build refusal/fix. Sequential observations are not a reader lease/atomic snapshot. Frozen B63 does not contain B64-B68; a new passive candidate/wire/caller is required for actual joins. All B63 pins unchanged, gaming hold honored, no game/provider/install/input/close action. Coherent private storage/publication/all readers/failure/resource/saved-ownership/native review/T20 remain open, native admission=false. See `batch68-stock-storage-joins/findings.md`.

B69 prepares the new private before-finalizer/after-callback stock witness, retaining the B63 phase/controller/thread evidence and B68 complete count/cookie/primary/expiry/metadata/numeric/name/resident joins. The final443,392-byte ASI/SHA `df8d41faddd45704df96d049c32bfe59174ec8d16334056846522bcc14757246` passes inert no-session verification; 40 storage cases/698 checks,13 native fixture modes/403 checks,6 real local Win32 transport cases,76 strict decoder and39 caller tests pass. The144,992-byte candidate/SHA `717eb684fd35c44d0db162f7ad328465853e26a7f1d0c4274c8f8b3639177a34` retains504 verified pins, including unchanged B63/B68 inputs. Review caught phase completion being published before stock flush; the final tested shared publisher flushes stock first, then phase, and actual write-failure cases retain partial files truthfully. Initial/intermediate source/artifacts and actual results remain. The caller refuses every mutating path under the direct human gaming hold; no game/provider/install/input/close action or fresh peer handover occurred. This is offline fixture proof, with no atomic snapshot, reader lease or native admission claim. After direct human release, re-freeze the caller and obtain a fresh exact-candidate peer handover before one bounded owned startup/closure/restoration cycle. Central publication/all readers/materializer/backing/resources/first saved ownership and all original feature/scenario/review/delivery/T20 parents stay open, native_admission=false. See `workspace/reports/cditem-execution/20261018-native-review/batch69-native-stock-witness/findings.md`.

The explicitly authorized ChatGPT/ThinkForge source reviewer has one bounded RH-01 assignment: test coherent publication through the existing registered owner, including mixed map-header reader interleavings versus stable capacities. The exact question, hypotheses, rejected routes, retained source and output ownership are in `workspace/reports/cditem-execution/20261018-chatgpt-re-assist/cdmw-reply.md`; output is limited to that folder, with no implementation/tracking/provider/game ownership transfer. Review findings remain pending.

B70 couples unpublished primary/cookie/expiry/metadata arrays with both B66 identity maps, preserving borrowed stock records and adding cold slots only. All source/API/count/identity/collision/counter preflights precede raw allocation, and a complete B68 structural join must succeed before the prepared view is exposed. The first strict Release build/native run pass:70 isolated cases/3,402 checks,574 raw allocator-leaf calls,722 raw free-leaf calls and192 native numeric/name insertions during bundle preparation, plus4 separately captured native fatal child paths. Both explicit heap/TLS families, aliases, spare metadata capacity, actual3-to5 map growth, all13 array/map-clone returned-null positions, post-native uncertainty and final joined-read refusal are covered. Known raw arrays never free borrowed stock records; uncertain map allocations stay retained until isolated arena teardown. The331,776-byte fixture/SHA `41a894f863666619ed7712f3d14b03bcc11db723cecdaf3c621c6b6fa5f31727` and150,919-byte receipt/SHA `3da8c78503fec97392e58bb05e787fcd25f7e975a7f09936d9256af4b0a5dff1` retain525 verified pins including unchanged B69 inputs. Metadata offsets remain opaque DWORDs; no appended backing stream, record lease, engine heap/readiness, publication or startup recovery is proved. B69/public portable stay unchanged; no game/provider/install/input/close operation occurred under the direct human hold. External RH-01 source review remains pending. All original feature/scenario/review/delivery/T20 parents remain open, native_admission=false. See `workspace/reports/cditem-execution/20261018-native-review/batch70-unpublished-storage-bundle/findings.md`.

B71 qualifies the second direct ItemInfo materializer caller:321-byte/83-instruction bulk reader14f4fc1e0, public E9 14241b790, statically bound by RTTI to ItemInfoManager vtable1459be2e8 slot+60. It bypasses getter14038ab60, uses one Reader at cursor0 and does not seek metadata offsets; replay after resident rows therefore supplies no append transaction. Both selected direct calls are instruction-boundary verified, with no all-indirect-consumer absence claim.14 fixture modes/65,891 checks pass through the unchanged bulk source/public thunk, including the65,476-row loop bound and one mode with the actual693-byte resident materializer plus a direct native resident call using invalid Reader1. Other materializer modes and file/clock/body-release helpers remain explicit spies. Load/failure/status-pointer/body-retirement behavior and the conditional resident-prefix cursor mismatch are retained. The278,016-byte fixture/SHA `89f24ba2a07225d8ed58472e22c6d2c997636a55141c76b582f2c70f618ba91d` and163,493-byte receipt/SHA `f3b76ec229cfe968116336d9d101277d8200b116ed4b5960eee638a3e951b4cf` retain570 verified pins and both passing build/run versions. No game/provider/install/input/close action occurred under the human hold; B69/B70/public portable remain unchanged. An additive source note is saved for the bounded reviewer at20261018-chatgpt-re-assist/owner-update-b71.md. Private backing/materializer/metadata coverage, actual reader lease/phase/failure, resources and saved ownership/full feature/T20 remain open, native_admission=false. See `workspace/reports/cditem-execution/20261018-native-review/batch71-item-body-consumers/findings.md`.

B72 reconciles the completed independent RH-01 review. Exact11,099-byte report/SHA `301329f5dd89e15d3bbca391669f57b77b127c0f1e6a0dcbeee3cb1794340f1c`,10,298-byte evidence/SHA `6e6d0d55fef66cf86b307d32bf83b8c5406508ef26c54d29c82fb94b76a34f4d` and all19 reviewed input hashes match. The callback can retain old divisor3 then read new five-bucket storage, falsely missing existing hash5 even under a hypothetical indivisible header swap; actual startup overlap is unproved. B64 preserves indices/key/value prefixes. Fixed buckets with entries-first/buckets-second/count-last works only in the selected immutable retained-backing model; it is not a complete-owner publication proof. The reviewer reports13 model checks,364 existing-key hits and110 added hits/34 old misses/zero invalid reads. This Codex process verified source/inputs but did not rerun the model, whose source is absent from the delivered pair. RH-01 stays open on caller readiness/exclusion/last-use and all-consumer semantics. See20261018-chatgpt-re-assist/publication-review.md and 20261018-native-review/batch72-publication-review-reconciliation/findings.md under workspace/reports/cditem-execution/.

B73 source-qualifies global name entry142157ec0->14e4f0800 as bool(C-string,DWORD-output), with full379-byte/public-thunk guards. Four complete dispatcher/caller roots total1,328 bytes/352 instructions.15 native cases/111 checks execute14 top-level calls with real CRT atoi/strncpy_s and explicit zero-flag participants/handle/context helpers. Native dispatch resets output, continues participants after a hit and can return true/zero through a permitted numeric fallback. Reverse caller142157d10 copies borrowed text;142199250 stores its exact pointer into indexed/default context+808, retaining the lifetime obligation beyond return. Initial alias search resolves70 E8 candidates across46 roots without claiming all caller boundaries or a readiness gate. The275,968-byte fixture/SHA `0ccced9c886c6924591fb00b92ef0e766ea9000ed884550ed55904f10c86c6d3` and186,709-byte receipt/SHA `0b57e9f0c1728df76349b9545cea70c21dc78c45b872bf103744c4c55f883807` retain648 verified pins, including unchanged B69-B71/review inputs and the real first CRT build refusal/fix. No game/provider/install/input/close action occurred. Startup peer reports direct human resumption in its own chat and retains the game/install lane; local CDItem callers remain held without a fresh CDItem handover. Caller/engine readiness, complete publication/backing/resources/first saved ownership and all original feature/scenario/review/delivery/T20 parents stay open, native_admission=false. See `workspace/reports/cditem-execution/20261018-native-review/batch73-dispatcher-readiness-callers/findings.md`.

B74 implements a private recursive Windows coordination prototype for explicitly wrapped numeric/name/getter/materializer/reverse/bulk/maintenance entries. Eight owned C++ cases/65 checks pass on the first actual run, including real queued reader/writer exclusion, 7,000 threaded mutations, preparation cancellation, C++ commit failure/poison and LastError preservation. Review before execution added depth-one commit preconditions and ordinary scope release; first successful build inputs/EXE and reviewed build/run are retained. The 290,304-byte fixture/SHA `54bbdb4c87dc26f9ca8ca273d723d1edf2f87d8570044d4068648a9330575cc5` executes owned data and Windows primitives, not ItemInfo instructions. The user-supplied Downloads review/evidence are byte-identical to B72; no new document authority or model rerun is inferred. Complete consumer coverage, hook/readiness, cross-thread dependency/lock order, borrowed pointer last-use and whole-engine failure handling remain open, alongside backing/resources/first saved ownership/full feature/scenario/review/delivery/T20. No engine/game/provider/install/input/closure action or public build occurred; Startup retains the game lane and CDItem callers stay held. Native admission=false. See `workspace/reports/cditem-execution/20261018-native-review/batch74-native-access-coordination/findings.md`.

B75 source-qualifies ItemInfoManager slot+40 finalizer142417160 and name-list helper14241a020, plus the two direct phase callers1427c1650/149e0e690 through exact alias1425bb940->14fa45a60. Four roots total11,542 physical bytes/2,765 instructions including a source-qualified68-byte/17-RVA table; code is11,474 bytes. The finalizer has36 direct getter,19 name and19 numeric sites and one list-link helper, with no runtime invocation-count claim. The copied264-byte reload caller and unchanged596-byte dispatcher pass9 owned native cases/333 checks:149-family slot+8 teardown precedes clearing controller+19, then six setup passes; AL1/2 distinguishes tested success/returned failure. Prelude/prepare/groups/diagnostics/family methods are explicit spies. Returned prepare/group errors still reach the dispatcher under those spies; actual helper failure policy remains unqualified. Initial code/data capture refusal and first native wrong diagnostic-count assertion are retained with exact fixes. Final271,360-byte fixture/SHA `e73beba8f6d11f193a47a8b7c3f7993ee31c5361f7703ad52d4fa5ac764d1d5a` supplies no all-reader lease. Outer synchronization, rebuild/borrowed-name last-use, backing/resources/first saved ownership and all original feature/scenario/review/delivery/T20 parents stay open, native_admission=false. No game/provider/install/input/closure/public build; Startup retains lane. See `workspace/reports/cditem-execution/20261018-native-review/batch75-startup-reader-boundary/findings.md`.

B49 continuation qualifies eight complete resource roots,6,581 physical bytes/1,728 instructions. Its isolated fixture passes15 cases/15 calls of the unchanged native initializer using explicit PAPGT/availability/PAMT/diagnostic test helpers and owned empty names. Exact mode1 is required: modes2/255 can return success without checking/loading any group; mode1 with all255 optional groups absent can also succeed without a load call. A later mandatory or PAMT failure follows earlier successful helper calls. Selected fixture paths preserve source/input bytes/LastError and do not dereference guarded tuple/S pointers; actual engine parsing/allocation/context and resource loading are unexecuted. Constructor/global-byte and PAPGT TLS/context+808 writes rule out assuming off-list preparation is wholly private. Findings, exact executable/source pins and unresolved publication/context/coverage questions are in `workspace/reports/cditem-execution/20261018-native-review/batch49-resource-mode1-abi/`. B44/Manual52 live lookup is verified and original setup restored; user owns game input. No game/install/provider operation or public rebuild occurred. Canonical ledger remains B32, native admission=false and all original native feature/scenario/review/delivery parents remain open.

Passive native batches 25–29 resolve both constructed context+0x48 slots to the same constant-true leaf, qualify the complete PA named-pipe update and its actual S+0x138 callback dispatcher, and join S+0x1f0 to Enter/LeaveCriticalSection plus deleting cleanup. The registered zero-tag raw-I callback selects a direct call; no index lifetime lease or retirement participation in that critical section is established. The next questions are the concrete I+8 association and actual reader/retirement joins, not another decode of the solved virtual slots or141371a40 local drain. The literal-encoding helper failure and read-only lookup errors are retained. A fresh native census finds a different foreign provider lineage still owning the project; no new Root SDK or native query was started. All171 packaged source pins, the delivered ce0ab5f5 portable and the complete canonical ledger remain exact. RH-01/RH-02/RH-03/RH-05 and all original open feature/native parents remain open. Reports and the concrete restart packet are retained under `workspace/reports/cditem-execution/20261018-native-review/batch25-default-context-slot48/` through `batch29-pa-lock-operations/`.

Passive native batches 5–9 remain outside the unchanged canonical ledger. The after-all-successful-+0x60 point at `0x14fa45af1` remains conditional; actual completion callbacks, whole-startup failure/readiness and native admission remain open. The resource-only witness completed in the copied stock world: exact read-only menu/world replays confirm one mode 1 backend, with world count=capacity=1 and no observed spare slot. Branch 0 preparation exposes context/index/callback references before provider insertion, so off-list construction alone does not withhold publication. Deleting-destructor/lazy-group-load qualification now proves a local drain, while external callback participation and the index+8 concrete child remain unresolved. The observer invoked no engine function and wrote no game memory. The fifth disposable cycle ended normally; all 26 originals and metadata were restored before Cloud ON, all 4 setup files and foreign runtime/bootstrap remain original, and the game/session host are gone. Cloud is persisted ON/Up-to-date and Steam returned to minimized library; original payloads/inventory still match after 7 recorded normal timestamp changes. The cancelled focus refusal and 2 no-input exit-image pauses are retained; this witness does not replace the prior 2 clean acceptance cycles. Production source/native payload/delivered executable are unchanged. All 234 retained source fingerprints/151,455,090,976 bytes match after a fresh full rehash. The 05:18 UTC audit finds a newer foreign owner in the same REA project; no new provider was started or adopted. Evidence: `workspace/reports/cditem-execution/20261018-native-live-witness/` and `20261018-native-review/batch7-live-mode1-review/`. Full native feature/T20 remain open.

Completed native continuation: the fourth owned provider imported all 1,278 prior evidence records/95 unknown revisions and retained every canonical row in `workspace/reports/cditem-execution/20261018-native-review/batch4-registration-boundary/provider/rea-complete-final-ledger.json` (96,795,800 bytes; SHA-256 `1f9817603690170007cd5fbe690836d0d4ecef371f8826d27b18d93d43e3a3ad`; 1,289 records/97 revisions across 16 IDs). Supported target/session close and graceful shutdown passed at 03:32:32.075 UTC; 03:33:57.1009448 UTC verification found no owned processes/project locks, session open:false and unchanged project metadata. New source proves the ignored normal decoder failure, object-only unwind cleanup, copied/borrowed reverse-name consumers and concrete indexed resource provider. First-instance acquisition is separately unresolved at RH-05. No production source, delivered executable, game, installation, archive or save was changed by this continuation.

The paired CDRUN entries in [progress.md](progress.md) record completed baseline/research continuity and scoped offline substeps. The native feature tasks stay in their original CDISO owner. Detailed attempts and current blockers are in [the handoff](cditem-astra-pro-handoff.md).

- Baseline and recovery: `workspace/reports/cditem-execution/20261017T231206Z/baseline.json`, `baseline-context.json`, `source-guard-refresh.json`, `original-saves/`, `original-bookkeeping/`, `original-bin64-settings/` and `rollback/`. Source guard refresh passed all 234 files / 151,455,090,976 bytes; all four prepared files match. Existing save/profile/installed-loader bytes are preserved.
- Available development entry point: `scripts/run_cditem_device_tests.py`; default inspect/replay remain zero input/launch. Exact-manifest preflight/execute/resume/cancel bind an already supported-launched live context. Process-bound F/SPACE/fixed 1.25-second hold, exact exit confirmation and bounded recovery passed source/independent checks and two clean real stock cycles without user input.
- Selected readiness: retained earlier 106 distinct nonvisual cases plus focused final owners: runner 105, controller CLI 5, offline/live saves 30/66, setup 17 and execution 87. Independent source/recovery and both actual retained-cycle audits passed. Unchanged broad suites were not rerun; native-item and packaged-device proof remain separate.
- Save/Cloud evidence: all four contexts restored the original 26 files and whole-root metadata exactly before Cloud. Consecutive clean cycles3/4 finished seven actions each, no failures, and nine/eight released scopes. Exact four-file setup is restored; Cloud is ON/Up to date and Steam minimized. Final inventory/bytes remain exact; normal Cloud synchronization changed eleven retained file timestamps, with no post-sync repair. Final source/archive and installed-state checks pass.
- Profile preparation: current-compiler four-package candidate remains read-only and unpublished. The separate temporary stock setup was used only for controlled cycles and has now been recovered through its exact four-file contract. Original profile generation `bbf65bdaf90146ee835b1ff2093ab7c1` is restored; no source archive changed.
- Independent source review: `workspace/reports/cditem-execution/20261018-runner-review/review.md`. Seven findings were corrected. Approval review rejected deletion of the owned TEMP alias fixture, stating only `blocked by policy`; the exact retained path is in that report, with no workaround attempted.
- Native research history: four owned pinned batches preserve complete imported history. Latest final export is 96,795,800 bytes / SHA-256 `1f9817603690170007cd5fbe690836d0d4ecef371f8826d27b18d93d43e3a3ad`, 1,289 evidence/97 unknown revisions across 16 IDs. All four providers closed gracefully; final 03:33:57.1009448 UTC verification finds no owned/related PIDs/project locks and session open:false. New fourth-batch source and independent review establish normal false-decoder publication, object-only unwind cleanup, copied/borrowed reverse-name consumers and the concrete indexed resource provider. Formatter escape, coherent publication/failure, durable package backing/private index ingestion and retirement remain open. The reference Add tool uses a same-WORD owned exemplar for eligibility/stability; passive ordinary construction/UID/planner/apply is now source-joined, with lookup failure ambiguity and first-ownership success still open at RH-05. The linked handoff contains exact reports/hashes, corrected and failed attempts, and next discriminating contracts.
- External installation: the other chat installed sealed Loadouts v7.192 ASI-only during execution; its SHA-256 is `12b45299438009eda376cc8a77c17fa82bb8a1f55a53a834e3f354960c372b57`. That change is preserved and invalidates reuse of the initial foreign ASI pin for a later run.
- Delivery result: normal onefile release passed at source revision `98ae737c46cb8967cc42d15c7f5dc02680920e13`. Portable size 175,507,262 bytes; SHA-256 `051e0e8c2a3420c2d5e578ed0d1471c9858f770a5d13266124e368b339ff8e7f`. All 586 members, native probes/provenance and default/Mesh Builder startup pass. Six embedded service modules and fourteen catalogues match source; delivered ASI/session bytes equal the real stock-cycle payloads. Full native T20 remains blocked. Exact receipt, rollback, original failed verifier and corrected proof are retained in the baseline evidence directory.

Verified partial delivery: T01/T19 have actual stock launch/load/world/exit and two clean consecutive source-runner cycles. Source/embedded-code equivalence and identical delivered native payload hashes are verified; the actual packaged executable passes startup/native probes. Original saves/setup/Cloud and process cleanup pass with eleven honest post-sync timestamp deltas. Native positive/refusal, acquisition/equip/coexistence/cache/saved identity and full T20 remain blocked by RH-01/RH-02/RH-03 and the first-instance acquisition prerequisite RH-05. Their ten original feature parents, scenario, full review and full delivery gates stay open. Handoff and accurate partial-delivery reconciliation are complete; the full goal is not complete. WMDPI equal-scaling hardware proof remains separate.
