# Mesh Editor, Create New Item and Virtual Loader implementation results

Date: 2026-10-17 (Europe/Stockholm)  
Plan: [mesh-editor-cditem-virtual-loader-plan.md](mesh-editor-cditem-virtual-loader-plan.md)  
Completion log: [progress.md](progress.md)  
Status: Completed on 2026-10-17. All 17 required tasks are closed; five conditional research follow-ups remain deferred.

## Delivered scope

The bounded implementation improves repeated mesh work, independent item planning,
package admission and decompression, virtual-output preparation and launch verification.
Each reuse path retains its owning source, revision, identity and cancellation checks.

The work includes selected-LOD initialization and deferred editing graphs, topology
adjacency for Smooth, immutable texture sharing, revision-aware inspector caches,
one exact prepared geometry encoding, and the versioned binary authoring bridge.
Create New Item reuses a verified clean stock catalogue/table generation with
independent request state. Package preparation shares complete admissions and
verified compressed-member resources. The Virtual Loader distinguishes required
content from catalogue-only files when dependency closure is proved, reuses
appropriate private output work, and reports byte-weighted verification progress.

The source and focused executable evidence are described below. They do not establish
visible UI frame pacing, full application startup, a live Steam launch or new game/save
compatibility.

## Measurement method and input identity

Results are matched component measurements on the same Windows development machine.
Package and stock measurements use a warm process/filesystem; OS-cold storage was
not controlled. Python document measurements invoke the production preparation and
encoding functions over synthetic geometry. Rust measurements use optimized release
fixtures and state their included stages.

The real retained package pair is identified by exact artifact SHA-256:

- `7858f1f1b0a26de4df4c56a6666ce96a1cd97200fb16d28e4c1605b6133018e3`
- `875ea762163938cda47bcac8fdc020e6d55fca13fbcfa0f08ac0a0201c641464`

Their ZIP sizes are 26,020,289 and 25,960,171 bytes. The shared three DDS resources
contain 44,739,680 decoded bytes and 25,708,500 compressed bytes. These real-package
timings cover v1 inputs; focused fixtures separately cover the supported semantic
and v2 admission paths.

Baseline implementation work started at `b99e5c267f74e135410b9a627df8abc9a05d920d`.
The earlier read-only review used `afa050237092d1aa38ad0642ceabdd889da907da`.
Concurrent window, format and Morph & Refit changes are outside this implementation's
staging boundary.

## Mesh results

### Derived calculations and working data

| Stage and fixture | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Inspector calculations, 100,000 vertices | 483.000 ms | 3.420 ms | Verified warm reuse of static/relevant-revision results |
| Neighbor lookup, 10,000 vertices / 29,601 edges | 124.321 ms | 0.145 ms | Edge scanning versus cached ordered adjacency; not a full brush frame |
| DDS remapping, 32 MiB payload / 20 remaps | 63.321 ms | 0.046 ms | Zero repeated payload-byte copies after sharing |
| Initial graph construction, four 99,999-vertex LODs | 58.296 ms | 13.529 ms | Four graphs versus the selected graph |
| Compatible resident graph refresh | — | 0.779 ms | Reuses compatible topology/provenance |
| First uncached LOD request | — | 0.012 ms | Request submission through the real loader |
| First uncached LOD completion | — | 33.615 ms | Worker plus headless acceptance; 1 ms polling |

The deferred-LOD fixture checks accepted request/document generations, retained
history for the previous LOD and the final geometry fingerprint. Its timing excludes
initial application creation, GPU upload and a visible frame. Deferral moves the
unused graph work to the first request; it does not remove that work.

Inspector caches distinguish geometry, topology, weight, palette, rig, provenance,
policy and position-dependent island changes. Selection and presentation changes
refresh their smaller state without repeating unrelated full-mesh checks.
The source remains authoritative when a revision cannot be safely reused.

### Prepared encoding and binary transport

The first optimization shares the exact prepared encoding between capacity checks
and successful publication. In its matched JSON trial, 100,000 vertices improved
from 354.462 to 184.897 ms and 300,000 vertices from 1,109.187 to 554.314 ms.

The remaining JSON construction/fingerprint/encoding cost justified the binary
transport. The subsequent matched single-encoding trial produced:

| Python document fixture | Prepared JSON | Prepared binary |
| --- | ---: | ---: |
| 10,000 vertices | 15.950 ms | 3.548 ms |
| 100,000 vertices | 185.144 ms | 35.007 ms |
| 300,000 vertices | 545.118 ms | 106.588 ms |
| 300,000 vertices with fractional shader masks | 673.840 ms | 224.417 ms |

Exact unchanged-document cache lookup was approximately 0.004 ms. Binary fingerprint
work was 3.277 ms at 300,000 vertices, compared with 135.841 ms of JSON fingerprint
work in the preceding measured JSON stage. Separate trial medians are reported as
stages; they are not added together into a claimed window-startup duration.

The matching Rust release decode/validation fixture measured:

| Vertices | JSON | Binary |
| --- | ---: | ---: |
| 99,999 | 9.906 ms | 2.062 ms |
| 300,000 | 30.422 ms | 6.098 ms |

Those native figures exclude file I/O and the outer file SHA check.

Fixed-width float64 transport preserves Python values until the existing Rust
float32 rendering boundary. It can use more bytes than JSON for simple numbers:

| Python fixture | JSON bytes | Binary bytes |
| --- | ---: | ---: |
| 100,000 vertices | 5,655,582 | 7,201,061 |
| 300,000 vertices | 17,587,943 | 21,601,072 |
| 300,000 vertices with masks | 21,787,942 | 28,801,083 |

New authoring writes `document.bin` and revisioned binary state files using
`mesh_document_binary_v1`. The helper must advertise that exact capability.
The existing JSON reader and Preview paths remain available. The typed metadata
and structural fingerprint are checked before conversion; the outer owned reference
checks path, root identity, size, count and complete SHA-256. Payload and aggregate
session bounds remain 512 MiB and 768 MiB.

Capacity preflight and publication reuse immutable bytes only for the exact prepared
candidate after its successful revision-checked commit. Stale, cancelled, malformed
and oversized candidates cannot replace the last usable state. Vertex Parameters'
separate commit boundary follows the same rule.

Owning documentation: [Mesh Editor](../cdmw/ui/mesh_editor/README.md), including the
binary layout and cache rules. Focused test routing is in
[the test matrix](../docs/test-matrix.md).

## Create New Item and .cditem results

### Verified clean stock reuse

The installed clean baseline contains 2,052,523 catalogue entries, 6,816 items,
436 stores and 15 language tables. Three warm trials of the captured original
catalogue/table preparation versus verified reuse measured:

| Stage | Before | After |
| --- | ---: | ---: |
| Clean catalogue/table preparation | 17,946.925 ms | 250.371 ms |

The table contents and all 34 baseline PAMT hashes matched. This isolates the
catalogue/table stage: overlay-journal rebasing and later item-specific planning
were excluded. It is not a full Build Plan or UI-open duration.

The cache retains one immutable clean generation. Root/discovery metadata,
original index/content witnesses and reader/service identity govern reuse.
Each plan retains independent dependency tracking, mutable entry views and working
caches. A mounted workspace view cannot replace the clean authoring baseline.

### Package admission and repeated decompression

Five warm trials of the retained pair measured:

| Workload | Without shared reuse | With reuse | Decoded asset bytes before / after |
| --- | ---: | ---: | ---: |
| Read the pair once | 272.947 ms | 235.515 ms | 90,839,001 / 46,099,321 |
| Inspect the pair twice in one preparation | 537.287 ms | 295.471 ms | 181,678,002 / 46,099,321 |

One pair requires ten decoded members without sharing and seven with verified
representation reuse. The three shared DDS resources account for the avoided
44,739,680 decoded bytes.

Cache identity includes the exact artifact and current admission limits. Reuse of
compressed members remains bound to the verified compressed bytes and ZIP metadata.
Malformed paths, missing members, changed sources, CRC/length errors, unsupported
capabilities and contradictory metadata remain refused. Each package keeps independent
mutable metadata and ownership while immutable resources can be shared.

One preparation cache spans admission, resolution, retained-package recovery and final
semantic recomposition. Ordinary ZIP classification no longer decodes the full artifact
merely to choose its reader.

### Compression decision

Three warm trials rebuilt and read both retained packages under three storage policies:

| Policy | Combined ZIP bytes | Write median | Read median |
| --- | ---: | ---: | ---: |
| Stored | 90,882,864 | 66.833 ms | 105.229 ms |
| Deflate level 1 | 60,531,973 | 440.000 ms | 227.754 ms |
| Current Deflate level 6 | 51,980,442 | 1,249.640 ms | 232.194 ms |

Content/identity comparisons passed. Level 1 increased storage by about 16.5% for
about 1.9% faster warm reads; stored members increased storage by about 74.8%.
The current compression policy is retained. OS-cold reads and complete preparation
impact were not measured, so MEL-RE-02 remains an unfinished conditional investigation.

Owning documentation: [Independent item packages](../cdmw/ui/new_item/INDEPENDENT_ITEMS.md).

## Virtual Loader results

### Source roles and the current saved profile

A source can become catalogue-only only after every relevant v1 recipe records a
completed traversal through parsed reference formats and explicit terminal resources.
Unparsed borrowed formats, borrowed HKX, unsupported module combinations, external
providers and active mounted layers retain the full carrier content guards.

The closed synthetic fixture placed a required runtime DDS in one carrier and
64 MiB of unrelated data in another:

| Hash-stage policy | Content files | Content bytes | Five-trial warm median |
| --- | ---: | ---: | ---: |
| Previous whole-carrier set | 9 | 67,257,532 | 34.445 ms |
| Proven required content plus catalogue metadata | 8 | 148,668 | 2.461 ms |

The unused carrier still receives pinned presence/size/time checks. Index bytes,
required content and metadata retain their exact witnesses. Native fixtures cover
same-size/restored-time required-content changes, file appearance/disappearance,
directory-junction rejection and session-long handle pinning.

**The current real saved profile does not qualify for narrowed carrier hashing.**
It has four incomplete recipe closures and nine external providers. Its required
set remains:

| Source class | Files | Bytes |
| --- | ---: | ---: |
| PAZ carriers | 192 | 151,317,189,856 |
| PAMT indexes | 35 | 68,152,176 |
| PAPGT, PATHC and version metadata | 3 | 7,095,205 |
| Package artifacts | 4 | 62,653,739 |
| Total | 234 | 151,455,090,976 |

The installed profile was probed only through dependency resolution and guard
inventory. The probe stopped before the complete source-hashing stage and published
nothing. No new 151 GB scan or live-launch duration is claimed.

### Compiled-output reuse

Fresh source verification precedes cache lookup. A whole hit captures the active
private generation's exact bytes and verifies its existing owned output SHA ledger,
resource inventory and decoded raw bindings. The ledger supplies prior-builder
provenance, as during launch; exact output SHA preserves the already built checksum
chain without recomputing the PAZ checksum.

Partial reuse is limited to unchanged processed resources where a conservative size
check justifies capture. Plain DDS data uses its current bytes directly. A tiny
unchanged compressed record cannot trigger capture dominated by large plain assets.

Preparation-owned digest receipts originate only from exact immutable byte objects
retained after complete package admission. Changed, generated, copied and uncached
objects hash normally. No receipt crosses the subprocess or persistent-profile boundary.
Source-file hashing, captured-output hashing, decoded span checks and final guards
remain fresh.

Three matched warm trials used the real three DDS resources and one synthetic
212,992-byte encrypted LZ4 record:

| Processing/packing/cache stage | Without reuse | Final policy |
| --- | ---: | ---: |
| Unchanged output | 99.210 ms | 83.257 ms |
| Record changed | 101.401 ms | 100.113 ms |
| Selection order changed | 98.886 ms | 99.902 ms |

Every output byte matched the uncached builder and source package hashes were unchanged.
The two misses captured no previous output; their small timing differences do not
establish a general speed improvement. Package admission, semantic lowering and fresh
source-file hashing are excluded.

An earlier raw-only partial implementation regressed to 215.864 ms versus 105.443 ms.
It was replaced with the capture admission rule and exact-byte digest handoff before
completion. Cache use remains bounded to the active generation, 256 MiB of captured
output and 4,096 resources; unsupported or unavailable cache data uses the normal
builder, while malformed ownership metadata is refused.

### Launch preflight and progress

Python preflight keeps ownership, selection, inventory and presence checks while
the pinned native stage performs prepared-output content verification before
starting Steam. Full standalone verification and ASI-side checks remain.

For the saved profile this removes one redundant Python pass over 136,194,852 output
bytes. It does not remove the required source scan. Verification reports checked
bytes, total bytes, elapsed time and the current file, with bounded updates and
source-specific failure messages.

Compiler revision 9 and worker/native protocol version 3 describe the new preparation
contract. The native reader retains CDVFS2 compatibility. Existing saved profiles
from the old compiler require **Apply changes** under the updated application.

Owning documentation: [Virtual Loader](../cdmw/ui/new_item/VIRTUAL_LOADER.md) and
[native protocol/runtime](../native/cdmw_virtual_loader/README.md).

## Validation evidence

Focused behavior checks were selected for the changed boundaries:

- Package, stock, provenance and virtual integration: 148 cases passed after the
  initial cache/source work. Semantic admission and exact reader-authority follow-ups
  also passed.
- Source roles and reference closure: seven integration cases and five traversal/fork
  cases passed. Added native catalogue coverage passed nine cases, including junctions.
- Final output cache, digest receipt, reader, semantic and lifecycle run: 72 passed.
  Earlier virtual/process integration and additional lifecycle runs passed.
- Mesh authoring owner run: 175 passed plus 74 subtests, with two legacy error-message
  assertions exposed by the new bridge. Those contracts were restored; the focused
  rerun passed 22 cases and 42 subtests, including the binary/cache owner checks.
- Vertex Parameters, helper selection, legacy Preview cutover and resource packaging:
  132 passed, including the direct prepared-commit reuse case and missing-only-binary
  capability refusal.
- Rust checks passed for adjacency/Smooth, compatible refresh and fallback, texture
  sharing, deferred LOD success/failure/staleness, parked history, immutable queue
  ownership, hair source hydration and binary framing/integrity/legacy compatibility.
- The shared Python/Rust precision fixture passed through the production native
  deserializer and binary reader, including rounding boundaries, subnormals, negative
  zero, partial optional arrays, multiple LODs and signed source-map extrema.
- Release component benchmarks, including the real deferred-LOD worker and headless
  acceptance path, passed their parity assertions.
- Native protocol/I/O and selected launch-harness refusal/readiness cases passed
  using an isolated fake game/Steam fixture.

These are separate runs with overlapping owners, not one summed test-count claim.
The actual test commands and per-task proof notes remain in the plan and owning docs.

### Final release-helper gate

The overnight implementation session completed the required helper-only release command. Resume verification on 2026-10-17 recovered its outputs and confirmed that they still match the current implementation:

```powershell
.\build_pyside6_app.ps1 -Mode onefile -BuildProfile release -NativeHelpersOnly
```

| Verified input or output | Recovered evidence |
| --- | --- |
| Rust production helper | `native/rust_mesh_editor/build/Release/cdmw_mesh_lab.exe`, 18,234,880 bytes; SHA-256 `b9772dfc50a4a4d59ef9e0bdac96bdff95e07351260ce132e81993112007db04` |
| Rust source identity | All 120 fingerprint inputs match `41af008f3eaabe4e9588407f8a3ec4cfc6be7126e912f3b542dcfb0e45aac1d6`; the current Cargo.lock also matches the manifest |
| Rust contract | The production package validator passes, including executable/control-contract hashes, locked dependencies, Preview requirements and `mesh_document_binary_v1` |
| Virtual Loader ASI | SHA-256 `ebd7524402794428d363e2d182e57f3c9a966b4716a86eac1d20856ad74d4b68` |
| Virtual session host | SHA-256 `b59eb8e8bda23b10e3b56156151412f406d19ced14c6f6b0f3164ee817b4e743` |
| Virtual source identity | Every source and artifact hash in `native/cdmw_virtual_loader/build/Release/provenance.json` matches |
| Native self-test | The saved `protocol_and_io` test passed at 02:10 Europe/Stockholm, recorded in `native/cdmw_virtual_loader/build/Testing/Temporary/LastTest.log` |

Both provenance records identify checkout HEAD `10735072ee094e9dd7193b25eb289315df6fd1d0` plus its recorded source changes. The helper was built from the shared working tree, which also contains the other plans' pending work; its fingerprint identifies that exact tree. The final MEL commit retains only this plan's source changes. Build outputs remain machine-local.

The unchanged build and focused behavior evidence are reused. Resume checks independently verified the current hashes and production helper compatibility rather than rebuilding the same inputs. The current localization freshness check also passed with 15,996 source keys.

Full application packaging, visible UI/GPU captures, actual Steam/game launches,
archive installation and game/save compatibility tests are separate proof scopes.
The implementation does not claim those results.

### Final closure review

The final source review checked Python/Rust binary framing and precision, descriptor
validation, prepared-document adoption, verified output reuse and its source-check
ordering. One malformed-input gap was reproduced: deeply nested metadata raised
`RecursionError` outside the normal protocol-error boundary. The decoder now converts
it to `BinaryMeshDocumentError`, which the owning payload reader already handles.

The final focused command passed 10 tests and 35 subtests, including the new rejection
case and the shared Python/Rust fixture:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mesh_rust_document.py -q -p no:cacheprovider --basetemp="$env:TEMP\cdmw-pytest-mel-binary-final-20261017"
```

The source split passed syntax checks for 39 staged Python files. The production
localization generator also passed against the isolated staged source: 15,981 keys,
with all 14 catalogues and native-key metadata synchronized. The shared working tree
retains the other plans' changes and its 15,996-key catalogue. Only MEL source hunks,
generated-key changes, documentation and completion entries enter the local commit.

## Conditional research left open

| Plan task | Remaining requirement |
| --- | --- |
| MEL-RE-01: range guards | Prove the actual runtime/provider closure before selecting stored-byte PAZ ranges; then validate a new bounded native range protocol |
| MEL-RE-02: adaptive compression | Add controlled cold-read and whole-preparation evidence if further format work is justified |
| MEL-RE-03: skinning/LOD formats | Establish exact additional layouts, no-edit byte round trips and changes confined to intended fields before expanding writes |
| MEL-RE-04: EyeCover overlap | Obtain a decisive scoped render capture with draw/resource/order evidence and the documented control |
| MEL-RE-05: startup/lifecycle | Establish executable-specific runtime and save-lifecycle evidence for a narrowly defined replacement boundary |

Those tasks remain unchecked under the plan's conditional research phase. They do
not block the verified bounded implementation. The largest remaining measured
workload is the real profile's required 151.46 GB source set.
