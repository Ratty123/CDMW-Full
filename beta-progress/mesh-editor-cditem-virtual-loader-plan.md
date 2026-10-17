# Mesh Editor, Create New Item, and Virtual Loader Improvement Plan

- Plan ID: MEL
- Status: Required implementation completed on 2026-10-17; conditional research remains deferred.
- Created: 2026-10-17, Europe/Stockholm.
- Project: D:\CLAUDETEST\CDMW Full
- Game reference: C:\games\Steam\steamapps\common\Crimson Desert
- Plan file: D:\CLAUDETEST\CDMW Full\beta-progress\mesh-editor-cditem-virtual-loader-plan.md
- Completion log: [progress.md](progress.md)
- Review baseline: branch RR/independent-item-packages, commit afa050237092d1aa38ad0642ceabdd889da907da.
- Current scope: All 17 required tasks are complete. The five conditional research tasks remain governed by their evidence and scope requirements.

## Goal

Make Mesh Editor interactions, Create New Item planning, .cditem preparation, and virtual-loader startup faster while preserving item identity, source integrity, correct output, cancellation, and recovery behavior.

Prioritize verified repeated work and the large source-verification workload. Use additional reverse engineering where an unknown format or game behavior blocks a justified improvement.

## Required progress tracking

These rules apply to anyone working from this plan.

1. Before the first implementation change, read this plan and progress.md in this folder. If progress.md is missing, create it before implementation starts.
2. Use the task IDs below in both files. Keep one authoritative checkbox for each task in this plan.
3. Keep progress.md as a simple chronological list of completed work. Each entry contains the completion date, task ID, and a short description of the result.
4. Mark a task [x] here only after its acceptance criteria and required focused checks are satisfied. Add a Completion note below that task with the date, result, relevant check or measurement, and commit or evidence reference when available.
5. Update progress.md and the matching plan checkbox in the same work session, before handing the work back. Neither file is a substitute for the other.
6. Keep partial, blocked, deferred, and next-step information in the Current handoff section of this plan. Do not list incomplete work as completed in progress.md.
7. If a task is too large to complete as one verified change, split it into stable, named subtasks in this plan first. Track those IDs separately; do not mark the parent complete until its remaining requirements are met.
8. If later evidence invalidates a completion, reopen the checkbox, correct the related progress entry, and record the reason in Current handoff.
9. Preserve unrelated plans and progress entries. Add to an existing progress.md rather than replacing its history.

Completion-entry format:

    - YYYY-MM-DD | MEL-ME-01 | Cached topology adjacency for Smooth; focused behavior checks passed.

That line is an example, not a completed implementation task.

A task is done when its result exists, its acceptance criteria pass, its evidence is recorded here, and its completion is also listed in progress.md. A code change, a successful build, or an investigation alone does not establish all of those conditions.

## Current handoff

- Completed: All 17 required tasks: MEL-DOC-01, MEL-BASE-01, MEL-ME-01 through MEL-ME-06, MEL-NI-01, MEL-PKG-01, MEL-PKG-02, and MEL-VL-01 through MEL-VL-05, plus MEL-DONE-01.
- Active task: None. Required implementation and closure completed on 2026-10-17.
- Ownership: MEL source claims are released. The isolated MEL change preserves the pending Morph & Refit, window/DPI and conflict-isolation work, including their shared-file hunks and progress entries.
- Validation: Binary transport, cache authority, source guards and task-owned diffs reviewed. The required overnight helper release outputs match their source/provenance records. Resume verification passed the production helper validator, binary codec checks (10 tests and 35 subtests), and localization freshness for both the shared tree and isolated staged source.
- Known limits: The actual four-package profile still requires 234 source files / 151,455,090,976 bytes, including all 192 PAZ carriers, because it includes nine external providers and incomplete recipe reference closures. Narrowed hashing is not enabled for that profile.
- Conditional follow-ups: MEL-RE-01 through MEL-RE-05 remain unchecked and do not block the required scope. Range guards need complete runtime/provider closure; compression needs cold-read and whole-preparation evidence; format, EyeCover and lifecycle work need their separate evidence gates.
- Next useful action: Choose another plan for implementation. If more loader performance work is selected, start by proving the unresolved runtime/provider closure before attempting MEL-RE-01.
- Evidence: [Implementation results](mesh-editor-cditem-virtual-loader-results.md) records matched measurements, focused checks, recovered release hashes and remaining limits. No visible UI, full startup, actual game launch or new save compatibility is claimed.

## Scope and working rules

### Included

- Mesh Editor interaction and state-update costs.
- Create New Item stock discovery, planning, and related preparation.
- .cditem inspection, decoding, shared resources, and compatibility.
- Virtual profile composition, source verification, derived-output reuse, and progress reporting.
- Conditional format and runtime research described in Phase 5.

### Boundaries

- This document records proposed work. Reading it does not start implementation.
- Start from the current source and applicable AGENTS.md instructions. The source references below describe the review baseline and can move.
- Keep slow work out of the UI thread. Preserve the current worker ownership, stale-result checks, cancellation, and shutdown behavior.
- Keep logical package identities and retained numeric allocations stable.
- Preserve v1 compatibility and the implemented v2 module rules. Unknown required behavior must remain an explicit refusal.
- A cached result must be bound to verified inputs. File timestamps, a blob filename, or an unverified claimed hash are insufficient authority.
- Preserve bounds, path checks, exact index witnesses, provider conflict handling, final source verification, and recovery behavior.
- Keep native hooks focused on redirecting approved file operations to real files. Parsing and composition belong outside hooks.
- Use the smallest relevant behavior checks and measurements. Consult docs/test-matrix.md for current commands. Do not treat documentation work as a reason to build or run application suites.
- Reuse authorization already given when implementation begins. Follow applicable project rules for native release-contract changes, archive writes, visible UI, GPU captures, real-game runs, and publication.
- Keep extracted game assets, captures, and large machine-local evidence outside tracked source. Record concise findings and evidence references here.
- Separate window movement/DPI, Inspect File Formats, and Morph & Refit investigations are not added to this plan.

## Review evidence

The preceding read-only review inspected source and saved package/profile data. It made no implementation changes and performed no game launch, debugger attachment, build, or test-suite run.

The following are baseline observations, not promised end-to-end improvements. Reconfirm the relevant observations against the current checkout before changing their owners.

| Observation | Result | Evidence type |
| --- | --- | --- |
| Saved four-package virtual profile | 234 source files totaling 151,455,090,976 bytes | Saved profile plus current referenced file sizes |
| PAZ contribution to that source set | 192 files totaling 151,317,189,856 bytes | File-size inventory |
| Prepared virtual output | Four files totaling 136,194,852 bytes | File-size inventory |
| Saved compiler identity | Matched the source compiler stamp, revision 8 | Read-only comparison |
| test3 package full read | 26,020,289-byte ZIP; 138.66 ms warm median | Actual retained v1 package, three timed warm reads |
| test4 package full read | 25,960,171-byte ZIP; 137.97 ms warm median | Actual retained v1 package, three timed warm reads |
| Shared blobs in test3 and test4 | 44,739,680 decoded bytes; 25,708,500 compressed bytes | Actual package member inventories |
| Mesh document construction plus JSON encoding | 255.52 ms at 100,000 vertices; 776.02 ms at 300,000 vertices | Current functions, synthetic one-part, one-LOD geometry |
| Original/current skin-row checks plus selected-bone display | 448.13 ms at 100,000 vertices with six influences | Current functions, synthetic input |
| Rust helper contract validation | 12.60 ms median for the 18,064,384-byte helper | Existing validator; no helper launch |

Measurement limits:

- The 151.5 GB figure is a byte workload, not a measured launch duration. The review did not run another complete verification pass over that data.
- Package timings include the full reader and validation. Cold-storage conditions were not controlled.
- Synthetic mesh timings exclude disk writes, textures, process startup, Rust parsing, and GPU work.
- The two real packages were v1. Their timings do not establish performance for all v2 module combinations.
- Deflate reduced the three shared blobs by about 42.5 percent. Removing compression everywhere is not supported by these examples.
- Earlier source already includes progressive preview, worker-based preparation, resident catalogue caching, chunked package reads, post-decode blob sharing, GPU material reuse, and several JSON/clone reductions. Extend those mechanisms where useful.

## Phase 0: establish the work and its baseline

- [x] **MEL-DOC-01: Create the plan and synchronized completion log.**

  Acceptance: This plan exists in beta-progress, progress.md exists beside it, both contain the same documentation completion ID, and all implementation tasks remain unchecked.

  Completion: 2026-10-17. Created the two tracking documents and recorded the review baseline. Documentation inspection checks the task IDs, checkbox state, relative tracker link, and matching progress entry.

- [x] **MEL-BASE-01: Reconfirm owners and record focused before measurements.**

  Work: Check current branch, task-owned changes, owning contracts, and relevant existing tests. Select representative package, mesh, and profile inputs. Record stage durations and bytes for the work about to change, keeping cold and warm runs distinct.

  Acceptance: Record reproducible input identities, current commit, measurement method, relevant baseline results, and the smallest required validation scope. Do not remeasure unrelated phases or run a full archive scan merely to recreate the review.

  Suggested stages: stock discovery and table parsing; package inspection and decode; record composition and archive processing; source verification; mesh JSON preparation and Rust installation; inspector update; Smooth brush update.

  Sources: S1-S10 below, according to the task selected.

  Completion: 2026-10-17. Baseline b99e5c267f74e135410b9a627df8abc9a05d920d. Existing retained package/profile identities and synthetic mesh cases remain the matched inputs recorded above. Exact Python owners passed: 116 provenance/package/virtual tests in 25.19 s; 157 authoring tests and 32 subtests in 25.09 s. The initial temporary-path setup error ran no cases and was corrected before this baseline. Rust neighbor timing uses the old edge-scan algorithm beside the new cache on the same geometry, avoiding a second unrelated archive scan.

## Phase 1: highest-value bounded changes

These tasks can be separate changes. The source-verification implementation must follow its dependency-design task. The mesh and stock-cache work can proceed independently after their baseline checks.

- [x] **MEL-VL-01: Separate catalogue freshness from required content dependencies.**

  Work: Give catalogue structure, compilation inputs, and runtime resource references explicit meanings in provenance. Trace how broad file stamps currently become persistent whole-file hashes.

  Acceptance: Document which index, mount, provider, inventory, file-presence, and content witnesses each category needs. Establish a complete required resource set, including stock PAC, material, texture, and effect references the editor does not decode. Fixtures must cover a runtime-only dependency and competing providers. No source guard is removed merely because its archive has no recorded authoring payload read.

  Sources: S1, S2.

  Completion: 2026-10-17. Provenance now distinguishes catalogue-only PAZ presence from content reads and explicit pins. Per-recipe reference audits record closure only after a successful traversal; unparsed borrowed formats/HKX, v2 combinations, external providers and active mounted layers retain all carrier content checks. Parsed PAMT, mount, registry, inventory, provider order and actual/runtime-only payload witnesses remain authoritative. The owning Virtual Loader document records each role and its policy. Seven integration checks and five closure/fork checks passed, including a borrowed runtime DDS in a separate carrier, an unrelated carrier, unparsed references and competing providers. No v1-class-only exclusion remains.

- [x] **MEL-VL-02: Build source guards from the verified required dependency set.**

  Depends on: MEL-VL-01.

  Work: Keep the necessary catalogue and resolution evidence while excluding PAZ content proven unrelated to the profile. Preserve native pinning and final verification.

  Acceptance: Required content changes, same-size changes with restored timestamps, index remapping, mount/provider changes, runtime-only resource changes, truncation, and path replacement are rejected. Proven irrelevant changes behave according to the documented policy. Compare guarded files, bytes, and verification time on the same representative profile. Record the remaining required carrier size without inventing a target reduction.

  Sources: S1, S2, S9.

  Completion: 2026-10-17. Guard construction narrows only when every v1 recipe has a completed parsed/terminal runtime-reference traversal and there are no external providers or active mounted layers. Runtime-only DDS carriers remain content-guarded; verified-unused PAZ files retain native pinned presence/size/time checks, while indexes and metadata remain exact content witnesses. Seven source-role, five closure and nine added native catalogue cases pass, including restored-stamp required-content changes, directory junctions, absent/appeared files and session-long pinning. In a closed synthetic fixture with one 64 MiB unused carrier, content verification fell from 9 files / 67,257,532 bytes to 8 files / 148,668 bytes; five warm hash-stage trials measured 34.445 ms versus 2.461 ms. The installed saved profile has four incomplete recipe closures and nine external providers, so its 234 required files / 151,455,090,976 bytes remain fully guarded. This is not a measured game-launch improvement for that profile.

- [x] **MEL-ME-01: Cache mesh adjacency for Smooth.**

  Work: Build stable vertex-neighbor lists when topology changes. Reuse them during brush movement instead of scanning all edges for each affected vertex. Preserve deterministic neighbor handling and scoped normal updates.

  Acceptance: Neighbor results, Smooth output, undo/redo, and topology-change invalidation match the existing behavior. Include disconnected and boundary cases. Measure affected-vertex work and brush-update time on the same representative mesh.

  Source: S3.

  Completion: 2026-10-17. WorkingMesh stores immutable sorted adjacency rebuilt with topology; Smooth borrows it without per-vertex edge scans, sets or sorting. Cargo filters cached_adjacency, document_refresh and cached_smooth passed five behavior checks covering isolated/disconnected geometry, boundaries, stale handles, topology changes and undo/redo. The focused release benchmark on 10,000 vertices and 29,601 edges measured 124.321 ms edge scanning versus 0.145 ms cached lookup. This is algorithm timing, not visible frame timing. Evidence: tools/rust_mesh_lab/crates/cdmw_mesh/src/lib.rs and cdmw_interaction/src/lib.rs.

- [x] **MEL-ME-02: Cache inspector calculations by relevant data revisions.**

  Work: Cache immutable source eligibility by PAC/skeleton identity; current skin validation by weight, topology, palette, and rig state; selected-bone display by the selected bone and relevant weight state. Cache or request expensive inspector sections only when needed.

  Acceptance: Selection or label changes do not trigger unrelated full-mesh checks. Relevant edits invalidate results correctly. Island caching accounts for position-dependent seam behavior as well as topology. Cache hits and misses return equivalent state, including unavailable/unsupported cases. Record before/after update timings.

  Source: S4.

  Completion: 2026-10-17. Immutable PAC eligibility, weight/rig summaries, selected-bone influence and position-aware islands use relevant revisions. Selection and label changes reuse eligible results; successful commits adopt only their exact prepared candidate and close clears state. Eight new performance/authority checks pass; the 157 existing authoring cases and 32 subtests passed with the first cache implementation. The matched 100,000-vertex inspector stage measured 482.9999 ms before and 3.4201 ms on verified warm reuse. Evidence: tests/test_mesh_rust_authoring_performance.py and the production-function benchmark recorded in the results document.

- [x] **MEL-NI-01: Reuse the verified clean stock baseline for independent Build Plan.**

  Work: Reuse immutable stock catalogue and parsed lookup data on repeated independent plans. Give each plan fresh mutable caches, dependency tracking, and cancellation state. Preserve stock-baseline selection rather than reusing the mounted workspace view.

  Acceptance: Repeated unchanged plans avoid repeated discovery/parsing while producing equivalent results. Index/content changes and changes to baseline selection invalidate correctly. Concurrent or cancelled plans cannot contaminate each other's provenance. Measure discovery, parsing, and total planning separately.

  Source: S5.

  Completion: 2026-10-17. Repeated independent planning reuses one verified clean catalogue/table generation with immutable mappings, lazy per-request entry copies and separate trackers/caches. Exact source, index, metadata and authority checks invalidate reuse; mounted pathc rebasing remains per request. Focused stock-cache cases passed, including same-stamp index changes, table changes, custom reader/service identity, cancellation/concurrency isolation and mutable mapping separation. On the installed baseline with 2,052,523 catalogue entries, 6,816 items, 436 stores and 15 languages, three warm trials measured 17,946.925 ms median for the captured original catalogue/table preparation versus 250.371 ms for verified reuse. Exact table and all 34 baseline index hashes matched. This stage excludes overlay-journal rebasing and subsequent item-specific planning; it is not an entire Build Plan or UI duration.

## Phase 2: package and mesh data reuse

- [x] **MEL-PKG-01: Remove repeated full package work across inspection and preparation.**

  Work: Trace ordinary-package versus semantic-export admission, parent-side texture requirement collection, child resolution, and retained-package checks. Add a bounded verified inspection result or consolidate decoding under one preparation owner.

  Acceptance: The optimized path makes the same capability and texture-registry decisions and consumes the same verified artifact. Preserve changed-during-read detection, semantic witnesses, member limits, and v1/v2 rejection behavior. Measure read/decode counts and bytes across the complete preparation route.

  Source: S6.

  Completion: 2026-10-17. Ordinary semantic dispatch no longer reads/decompresses the whole artifact. One bounded preparation cache spans admission, resolution, retained-package recovery and final semantic recomposition; the parent conservatively guards the small texture registry without decoding ordinary packages. The new semantic contributor check confirms one admission rather than two, with unchanged recomposition and metadata isolation. Focused cache/stock/child tests passed, including capability and limit refusal. Inspecting the same two retained real packages twice measured 537.287 ms without shared reuse versus 295.471 ms with reuse, with decoded asset bytes reduced from 181,678,002 to 46,099,321. Warm process/filesystem measurement; no launch timing claim.

- [x] **MEL-PKG-02: Extend verified blob reuse before repeated decompression where valid.**

  Depends on: MEL-PKG-01.

  Work: Evaluate preparation-scoped reuse of previously validated artifacts or compressed-member representations. Extend the current post-decode sharing without weakening incoming-archive validation.

  Acceptance: A new malformed archive cannot become accepted because its blob name or claimed content hash matches cached data. Corrupt compressed bytes, CRC failures, size mismatches, missing members, and conflicting metadata remain rejected. Cache lifetime and memory budget are bounded. Compare duplicate decompression work using shared-resource packages such as the reviewed pair.

  Source: S6.

  Completion: 2026-10-17. Matching verified compressed representations now share immutable decoded assets before repeated inflation. Bounded byte/member/artifact budgets and admission-limit keys preserve local-header, CRC, length, path, capability, mutable-source and complete-package checks. The package/provenance/virtual owner run passed 148 cases; added admission-limit/authority and semantic checks also passed. The retained pair measured 272.947 ms without shared reuse versus 235.515 ms with it, decoding 90,839,001 versus 46,099,321 asset bytes and 10 versus 7 members. The avoided 44,739,680 bytes are the three shared DDS resources. Evidence: tests/test_independent_item_read_cache.py and the matched retained-package benchmark.

- [x] **MEL-ME-03: Avoid duplicate mesh document construction and JSON encoding.**

  Work: Reuse an exact prepared encoding between capacity checking and publication where they concern the same candidate document. Use revision-aware size information where valid. Preserve existing state-only command handling.

  Acceptance: Payload and aggregate limits remain enforced before publication; revision races, cancellation, and stale candidates cannot publish. Document content and fingerprints remain equivalent. Measure construction, encoding, and allocation work separately.

  Source: S7.

  Completion: 2026-10-17. Capacity checking and publication reuse the same exact immutable prepared JSON payload. Only a successful matching commit adopts a candidate; stale/cancelled candidates are cleared, source/session/root/revision checks and aggregate limits remain. Eight new authority/performance tests pass, including exact byte comparisons, stale candidates, oversized payloads and cancellation. Three-trial production-function medians were 354.462 to 184.897 ms at 100,000 vertices and 1,109.187 to 554.314 ms at 300,000; same-document lookup was about 0.0039 ms. At 300,000 vertices, the remaining build cost was 302.596 ms including 135.841 ms fingerprint JSON, followed by 252.558 ms final JSON encoding. Those remaining costs activate MEL-ME-04. Synthetic stages exclude disk, helper startup and rendering.

- [x] **MEL-ME-04: Add a versioned binary authoring transport when measurement supports it.**

  Depends on: MEL-ME-03 and its remaining-cost measurement.

  Work: Use typed arrays and a small descriptor for authoring data, taking the existing preview binary route as a design reference. Define producer/consumer compatibility before changing the bridge.

  Acceptance: Preserve numeric precision, channel identity, source mappings, resource hashes, bounds, revision authority, and unsupported-version handling. Verify all affected producer/consumer contracts and the required helper provenance. Compare startup and document-update costs with equivalent inputs.

  Sources: S7, S8.

  Completion: 2026-10-17. Versioned float64 binary geometry preserves channel identity and source mappings until the existing native float32 boundary, with checked descriptors, structural fingerprints, owned file/hash/count bounds, capability negotiation and revision-authorized publication. The shared Python/Rust precision fixture and focused producer/consumer, legacy, stale/cancel and prepared-commit checks passed. Final review reproduced and fixed deeply nested metadata escaping the controlled document-error contract; tests/test_mesh_rust_document.py now passes 10 tests and 35 subtests. At 300,000 vertices, matched Python preparation measured 545.118 ms JSON versus 106.588 ms binary; native decode/validation measured 30.422 ms versus 6.098 ms. These are component timings, not full startup or visible UI measurements. The required helper-only release build completed overnight; current source fingerprints, artifact hashes and production binary-capability validation pass. Exact commands, hashes and measurement limits are in the results document.

- [x] **MEL-ME-05: Share immutable CPU texture bytes.**

  Work: Separate texture ownership/material mappings from immutable DDS data so remapping and document installation do not deep-copy unchanged byte buffers.

  Acceptance: Material ownership and role-specific interpretation remain correct, lifetimes are safe across refresh and close, and existing GPU reuse still works. Measure copied bytes or peak memory and installation time with a texture-heavy asset.

  Source: S8.

  Completion: 2026-10-17. LoadedTexture retains immutable DDS data through shared Arc ownership while each material keeps its own mappings and interpretation. Refresh, remapping and queued documents share bytes without extending ownership past their live users. Focused headless texture/LOD/history and source-hydration checks pass. The release texture fixture used a 32 MiB payload and 20 remaps: 63.321 ms with deep copies versus 0.046 ms with shared data, with zero subsequent payload bytes copied. The measure covers CPU remapping, not GPU upload or visible frame latency.

- [x] **MEL-ME-06: Reuse working meshes and defer inactive LOD graph construction.**

  Work: Reuse topology and resident graph data for compatible document updates. Build inactive LOD editing graphs when required while retaining complete authoritative mesh data.

  Acceptance: LOD switching, undo/redo, topology edits, channel edits, and final output retain correct behavior. Define and verify the fallback that rebuilds a graph when required. Measure startup, refresh, and first-use LOD costs.

  Sources: S3, S8.

  Completion: 2026-10-17. Compatible authoritative updates refresh resident attributes while retaining exact topology/provenance graphs; incompatible changes rebuild. Initial authoring builds the selected LOD graph, and uncached LODs use the existing bounded loader with shared immutable source data, generation checks and cancellation. Current geometry remains visible until a matching result is accepted; parked LOD histories remain owned and stale source results cannot install. Focused lazy-LOD, refresh, undo/redo, topology, channel, hair-hydration and immutable-queue checks pass. The final release fixture for four 99,999-vertex LODs measured 58.296 ms for all four graphs versus 13.529 ms for the selected graph, with compatible resident refresh at 0.779 ms. The first uncached LOD request took 0.012 ms; actual bounded-worker completion and headless installation took 33.615 ms with 1 ms polling. Accepted generations, parked previous history and final geometry matched. GPU upload and visible frame latency remain outside this measurement.

## Phase 3: virtual preparation and launch

- [x] **MEL-VL-03: Reuse unchanged compiled virtual outputs.**

  Work: Define a cache lookup from verified inputs available before rebuilding output: compiler/adapter identity, package content, source witnesses, bindings, provider order, processing parameters, runtime ABI, and links. Validate cached output hashes separately.

  Acceptance: Unchanged Apply can reuse valid work. Changed records can reuse unaffected resource processing. Identity allocations, conflict handling, cancellation, generation publication, and recovery remain correct. Compiler or source changes cause the required misses. Compare composition/repacking time separately from final verification.

  Sources: S2, S10.

  Completion: 2026-10-17. The optional bounded build_cache records verified compilation inputs before processing. Whole hits capture and hash exact prior-generation outputs against the existing owned file ledger, check inventory/processed-span bindings and retain fresh source/final guards. Partial reuse requires unchanged transformed resources and skips capture dominated by plain DDS data. Preparation-local receipts reuse only digests of the exact immutable fully admitted package bytes; other data hashes normally. The final cache/receipt/reader/semantic/lifecycle run passed 72 cases, following the earlier 84-case virtual integration run. Three warm matched trials with the retained three DDS resources plus one synthetic compressed record measured unchanged processing/packing/cache verification at 99.210 ms without reuse versus 83.257 ms with it. Record changes measured 101.401 versus 100.113 ms and selection changes 98.886 versus 99.902 ms, with no prior-output capture on those misses. All output bytes matched and source packages remained unchanged. This stage excludes package admission, semantic lowering and fresh source hashing; it is not a full Apply time. Earlier raw-only partial reuse was rejected after measuring a regression.

- [x] **MEL-VL-04: Consolidate avoidable eager snapshot hashing.**

  Work: First assess moving prepared-output content checking from Python preflight to the existing pinned native verification before Steam starts. Keep necessary manifest, selection, ownership, and inventory checks.

  Acceptance: Changed or missing snapshots block startup through the native stage and produce an accurate UI result. Failed verification and cancellation do not start Steam. Preserve the final content check. Removing ASI-side hashing is outside this initial task unless an explicit follow-up proves retained file identity and every relevant handshake/death branch.

  Source: S9.

  Completion: 2026-10-17. UI preflight checks output presence and selection while deferring prepared-output hashes to the pinned native stage before Steam creation. Full standalone verification and ASI-side content checks remain. The focused preflight test proves output files are not eagerly hashed while every expected output digest remains in the session manifest; missing output still refuses early. Thirteen selected semantic/native cases passed, including corrupt output refusal before launch, required same-size/restored-time content changes, catalogue policy/pins and unknown wire versions. The saved profile has 136,194,852 output bytes whose redundant Python hashing is removed; no end-to-end launch timing is claimed.

- [x] **MEL-VL-05: Make progress and verification failures useful.**

  Work: Report preparation stages, checked bytes, total bytes, elapsed time, and the current large file. Identify the first relevant changed source or package in verification errors, with concise recovery guidance.

  Acceptance: Progress stays responsive and bounded through success, cancellation, and failure. Large files contribute by byte volume. Error details distinguish package, source, snapshot, and ownership failures without claiming success early. Reuse existing byte-progress support in the native host.

  Sources: S2, S9.

  Completion: 2026-10-17. Python and native verification report checked bytes, total bytes, elapsed time and current files with bounded update frequency. Concurrent readers share cancellation/failure state; error messages name the source or snapshot and recovery action. Focused progress/cancellation checks passed, including byte-weighted totals, monotonic updates, cancellation without success, same-stamp source refusal and native readiness gating. The native test host retained source/catalogue handles throughout its isolated fixture session. Evidence: tests/test_virtual_loader_sources.py, test_virtual_loader_catalogue_native.py and the baseline_guard_progress native cases.

## Phase 4: validate the implemented work

- [x] **MEL-DONE-01: Record focused before/after results and close the implemented scope.**

  Work: Compare equivalent inputs for the tasks implemented above. Inspect task-owned diffs and update the nearest owning documentation where behavior or contracts changed. Follow current project rules for any required changelog entry.

  Acceptance: Each completed task has its own proof, a checked checkbox, and a matching progress.md entry. Record remaining costs and limitations without turning synthetic or nonvisual checks into visible or in-game proof. Keep deferred tasks unchecked and list the next useful action in Current handoff. Do not widen tests merely because several source files changed.

  Useful user actions to measure when in the authorized scope: open a mesh, select a bone, update Smooth, build an unchanged independent plan, apply an unchanged virtual profile, and reach loader readiness.

  Completion: 2026-10-17. Reviewed the task-owned source and contracts, reconciled the recovered release evidence, fixed the final binary rejection finding, and completed the matched results document, owning feature documentation and grouped Unreleased notes. All 17 required checkboxes have matching shared completion entries. The isolated MEL source and generated metadata preserve other plans' work; staged Python syntax and the production localization generator passed (15,981 staged keys, versus 15,996 in the shared working tree). Existing unchanged focused checks were reused, and the changed codec's focused checks passed. Conditional research remains unchecked with its missing evidence and next actions above. Six inherited extra EOF blank lines are the only whitespace-check findings; they do not change behavior. The local commit contains only the verified MEL scope.

## Phase 5: conditional format and reverse-engineering work

These are separate follow-ups. Record the reason before starting one. They do not block the bounded changes above. Deferred work remains unchecked.

- [ ] **MEL-RE-01: Add bounded stored-byte archive-range guards if required PAZ carriers remain the main cost.**

  Depends on: MEL-VL-01, MEL-VL-02, and evidence of the remaining carrier-read cost.

  Work: Design a versioned protocol binding the resource to a verified PAMT, PAZ identity, offset, compressed length, decoding-relevant flags, and stored-byte digest. Bind those bytes to the payload used during preparation. Group reads by archive and offset where safe.

  Acceptance: Native bounds, truncation, alias/path replacement, index changes, overlapping/coalesced intervals, and pinning behavior are covered. Verify only proven required ranges; timestamp reuse is not a substitute. Parsing and decompression remain outside hooks. Record protocol compatibility and before/after bytes.

  Sources: S1, S9.

- [ ] **MEL-RE-02: Evaluate adaptive package compression only if it remains a meaningful cost.**

  Work: Compare representative PAC, DDS, and other blob families using stored members and suitable Deflate settings. Account for artifact determinism and reader compatibility.

  Acceptance: Record archive size, write time, cold/warm read time, and total preparation impact. Preserve package identity semantics and existing reader support. A decision to retain current compression is a valid completed investigation when supported by the measurements.

  Source: S6.

- [ ] **MEL-RE-03: Investigate additional PAC skinning layouts and LOD correspondence.**

  Work: Establish exact palette locations, extra-influence rules, supported vertex layouts, and LOD mapping before extending writes.

  Acceptance: Document proven layouts and remaining unknowns. Require byte-identical no-edit round trips and changes confined to intended fields. Treat game deformation/equipment checks as separate evidence when authorized. Do not broaden support from parser success alone.

  Sources: S4, S11.

- [ ] **MEL-RE-04: Investigate EyeCover overlap with decisive render evidence.**

  Work: When capture work is in scope, identify the failing draw, bound shader variant, input/output resources, aliasing, and ordering. Use the existing overlap investigation to choose the capture.

  Acceptance: Separate observed mechanism from hypotheses. Compare a proposed change with the one-overlap-component control and check its effect on the character behind the surface. XML flags or preview similarity alone do not establish a rendering fix.

  Source: S12.

- [ ] **MEL-RE-05: Investigate startup, resource resolution, and item/save lifecycle gaps.**

  Work: Define a narrow research question about a more stable startup boundary, runtime-only dependencies, archive lookup behavior, or missing lifecycle evidence. Direct item registration needs a separate proven chain covering construction, insertion, references, finalization, lifetime, and saves.

  Acceptance: Record exact game/build identity, observations, limits, and the next supported decision. Preserve executable-specific support boundaries until replacement evidence exists. A loader function or filename alone does not establish a usable registration API or broad save compatibility.

  Source: S13.

## Source map from the review

All locations below are under D:\CLAUDETEST\CDMW Full unless the full game path is given. Line ranges locate the reviewed code at the baseline commit; use current symbols if lines have moved.

| Ref | Owning files and reviewed locations |
| --- | --- |
| S1 | cdmw/services/new_item_provenance.py:69-92,135-189; cdmw/services/new_item_snapshot.py:644-650 |
| S2 | cdmw/services/virtual_loader_composition.py:34-49,69-184 |
| S3 | tools/rust_mesh_lab/crates/cdmw_mesh/src/lib.rs:123-136,249-265; tools/rust_mesh_lab/crates/cdmw_interaction/src/lib.rs:981-1047; tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs:6045-6090 |
| S4 | cdmw/services/mesh_rust_authoring.py:6313-6394,6446-6472,8155-8298; cdmw/services/mesh_rust_rig.py:10-57; cdmw/services/mesh_island_authoring.py:16-61 |
| S5 | cdmw/workers/new_item_workers.py:182-202; cdmw/services/independent_item_package.py:44-69; cdmw/services/new_item_service.py:89-134; cdmw/ui/new_item/controller_model_mixin.py:295-397,430-488 |
| S6 | cdmw/services/independent_item_package.py:281-413; cdmw/services/independent_item_install.py:326-354,396-419,569-578; cdmw/services/virtual_loader_process.py:254-307; cdmw/core/mod_compatibility.py:444-460,587-608; cdmw/services/independent_mod_package.py:34-133 |
| S7 | cdmw/services/mesh_rust_authoring.py:1858-1918,2140-2191,7539-7575,8845-8934; tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_session.rs:480-565 |
| S8 | tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/loader.rs:45-60; tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/main.rs:1801-1857,2395-2470,3128-3235; cdmw/services/mesh_rust_contract.py |
| S9 | cdmw/services/virtual_loader_runtime.py:79-123,195-213,378-415; native/cdmw_virtual_loader/session.cpp:15-77; native/cdmw_virtual_loader/runtime.cpp:55-144,299-325; native/cdmw_virtual_loader/protocol.hpp:19-33; cdmw/services/virtual_loader_process.py:80-149 |
| S10 | cdmw/domain/new_item/compilation.py:45-56; cdmw/services/virtual_loader_composition.py:165-184 |
| S11 | cdmw/modding/mesh_parser.py:2819-2848; exact-write eligibility in S4 |
| S12 | cdmw/ui/mesh_editor/EYECOVER_OVERLAP.md:1-59; tools/rust_mesh_lab/crates/cdmw_render_wgpu/src/lib.rs:569-608 |
| S13 | native/cdmw_virtual_loader/README.md; cdmw/ui/new_item/VIRTUAL_LOADER.md:392-424 |
| Game evidence | C:\games\Steam\steamapps\common\Crimson Desert\.cdmw\virtual-loader\profile.json; retained test3/test4 packages in C:\games\Steam\steamapps\common\Crimson Desert\.cdmw\independent-items |

Relevant existing test owners identified during the review include tests/test_new_item_provenance.py, tests/test_cditem_index_consumers.py, tests/test_independent_item_performance.py, tests/test_independent_item_streaming.py, tests/test_new_item_responsiveness.py, tests/test_new_item_model_apply.py, tests/test_virtual_loader_process.py, and tests/test_virtual_loader_launch_progress.py. Reconfirm exact cases in the current tree; these references are not a claim that the tests have been run.
