# Virtual loader (Experimental)

Mod Management has a separate **Virtual loader (Experimental)** page beside
Independent items. It prepares a private startup profile from `.cditem` packages
and supported extracted or archive mod folders. Existing authoring, manager export
and physical installation remain the defaults.

**Current availability: profile preparation and reviewed startup diagnostics.**
Game file redirection is disabled in both Python and the compiled native runtime.
The controlled startup probe reached the runtime but refused an existing file
hook owned by the verified ASI bootstrap. No virtual items or saves have been
validated in game. Changing a manifest cannot enable the guarded launch mode.

## Use and ownership

1. Add packages or mod folders, then choose **Inspect and prepare**. Preparation
   reads the destination, its mounted providers and retained identity reservations.
2. Review the items, allocated identities and composed files. **Save virtual
   profile** publishes the private snapshot and identity ledger together. It does
   not modify the original game archives or their mount/texture metadata.
3. **Launch with virtual profile** is enabled only when the executable, runtime
   and game acceptance gates are satisfied. The current prototype reports its
   blocker and keeps this action disabled.

There is one saved virtual profile per installation. Changing the selection takes
effect after preparation and publication, never during a running session. Remove
an item from the selection and save a new profile to remove its virtual
contribution. Its identity remains reserved because saves may reference it.

The same UUID cannot be active through both installation routes. To move a
physically installed item, use Independent items' existing reviewed **Remove**
operation first; disabling it is insufficient. Then select the same package here.
Moving back requires removing it from the saved virtual profile before physical
installation. Nothing moves automatically, and CDMW does not edit saves.

Independent items' `.cdprofile` export/import transfers the same identity ledger
for both routes. Virtual ownership is separate from physical overlay ownership;
it does not create fake installed-overlay IDs. After transferring identities,
prepare the packages again against the destination's actual game data.

## Supported inputs

| Input or operation | Current preparation support | Refusal boundary |
| --- | --- | --- |
| `.cditem` version 1 | Existing identity, dependency, relocation and record composition services | The [independent-item format matrix](INDEPENDENT_ITEMS.md#supported-format-matrix) applies without expansion |
| Mounted external mods | Current archive inspection and record conflict checks | Ambiguous providers, required-record edits or unsupported formats |
| Selected extracted mod folders and PAMT/PAZ mods | Supported loose files and known table pairs, privately composed with installed contributions | Executables, runtime plugins, malformed paths or unknown content |
| Shared tables | Existing additive and record merge rules | Different changes to an owned/required record never choose a silent winner |
| Texture registration | Existing PATHC encoder and collision checks | Missing or unverified registry, duplicate hashes or conflicting paths |
| Private output | One complete PAMT/PAZ pair, PAPGT and applicable PATHC from one generation | Game loading is gated separately from successful composition |
| Native additional definition files | Research only | No evidence that arbitrary filenames register items |
| Direct native item registration | Research only | No verified callable constructor/insertion/finalization chain |

Virtual loading still requires shared-table composition. It does not create an
independent game namespace or make arbitrary mods conflict-free.

## Publication and lifecycle

The feature owners are `virtual_loader_composition`, `virtual_loader_state`,
`virtual_loader_runtime`, and `VirtualLoaderPage`. The shared resolver in
`independent_item_install` and the existing archive writer/compositor remain the
only implementations of item binding and game-format composition.

The private directory is `.cdmw/virtual-loader/`. Each immutable generation has
`files/`, retained recovery packages and its profile manifest. The active profile
and `.cdmw/independent-items.json` are published with a durable before/after
journal and verified recovery copy. Cancellation before commitment preserves the
previous profile. A surviving journal blocks use until **Recover interrupted
profile** completes or reports incompatible external changes. Unreferenced
generations remain recovery evidence; this prototype does not prune them.

Preparation captures package hashes, source revisions, mounted provider
inventories and ownership state. Publication and launch reject changed inputs.
The transaction's writable targets are CDMW-owned bookkeeping and private files,
never original PAMT, PAZ, PAPGT or PATHC files. Physical archive mutation, overlay
installation/removal, recovery and virtual publication share a cross-process
installation lock. A session host and the in-game DLL each retain a lease so a
host failure cannot release a running game's snapshot prematurely.

The Qt controller supplies cancellable workers and generation checks. The Rust
Mod Management renderer projects the same controls through its existing generic
document/input bridge. Closing the page cancels preparation and discards pending
reviews; it does not terminate a launched game. The verified host executable is
copied into persistent CDMW storage before launch, outside the onefile app's
temporary extraction directory and helper lifetime job.

## Diagnostic setup and loading map

**Review runtime setup** shows the exact `bin64/CDMWVirtualLoader.asi` target and
SHA-256 before installation. It backs up an existing owned runtime, verifies the
exact executable and existing compatible `winmm.dll`, and refuses another file
owner. It never replaces that bootstrap, its configuration or another plugin.
**Remove CDMW runtime** removes only the verified owned DLL and receipt, retaining
profiles, reservations and recovery material.

**Review startup trace** prepares and reviews an original-file diagnostic launch.
Keep it at the title screen without loading a save. Trace mode does not redirect
any game file. Status and a bounded binary trace are retained under the private
directory, along with launch diagnostics. Ordinary launches without the correct
PID-bound live host session are inert.

Initial executable scope: Windows x64, version `1.0.0.2976`, exact SHA-256
`57da440d72f4db974f25fef047cf84c4dadd999a88cb2a3c5af4c9bd67fde1e7`.
The reviewed bootstrap SHA-256 is
`810111a7f6a6cef892877c9f7c4582ccde2d621d119891f700c5309c370508bf`.
Version text alone is never authorization to activate.

| Boundary | Observation and limitation |
| --- | --- |
| ASI bootstrap | Calls `InitializeASI`; CDMW's `DllMain` only disables thread notifications. The controlled probe found `GetFileAttributesExW` already redirected into `WINMM.dll` at initialization. Loader-lock context and readiness before the first affected read are not established. |
| File opens | Exact main-image imports of `CreateFileW`, `CreateFileA` and `CreateFile2`; the verified executable's CreateFile2 IAT RVA is `0x51eb158`. Import presence is only a candidate boundary. |
| Queries/enumeration | `GetFileAttributesW/A/ExW` and `FindFirstFileW/ExW` are exercised by synthetic native tests. The game-required subset and complete startup ordering still need observation. |
| Reads and mapping | Approved logical paths map to real immutable files. Windows retains read, seek, mapping and asynchronous-I/O semantics through its handles; no archive parsing occurs in hooks. |
| Unmapped paths | Original destinations; saves, configuration and executables are outside the redirect map. Mapped write access is refused. |
| Session | Private local pipe with owner ACL, PID and host checks, random token and exact executable/snapshot hashes. The host creates its own suspended game child and requires readiness before accepting the session. |
| Steam handoff | A process handoff that cannot be verified is refused. Cold/warm Steam startup has not passed acceptance; no environment-only activation or automatic rebinding is supported. |

The native runtime refuses foreign import hooks and reports the function and
owning module. It neither chains through an unverified hook nor overwrites it.
If readiness fails, the host terminates only the child it created, before accepting
the session. After readiness it waits for game exit. Unsupported hook combinations
are outside the compatibility guarantee.

## Native discovery and registration research

The read-only `scripts/probe_virtual_loader.py --executable <path>` records exact
fingerprints, relevant imports, strings and bounded candidate references.
`--trace <path>` decodes the native trace. These probes never attach, patch, launch
or register an item.

The verified image contains the `iteminfo` family name, the static-info directory
and ordinary/qualified `%s%s.staticinfobody` / `%s%s.%s.staticinfobody` patterns,
with matching header formats. Candidate formatting references occur near RVAs
`0x25c53ed`, `0x25c539f`, `0x25c575e` and `0x25c5710`. This suggests selection by
named families and optional qualifiers; it does not prove an enumeration-based
extension point. Raw string/reference matches are leads requiring caller and
instruction-boundary verification, not function signatures.

A candidate near `0x25bc118` references `iteminfo` after a call to `0x2412520`.
Neither that call nor the surrounding catalogue path establishes a safe item
insertion API. Calling convention, allocators, ownership, startup phase, threads,
auxiliary registries, finalization and save lookup remain unverified. No candidate
function is invoked and no raw registry writes are implemented.

Reference projects: [Crimson Desert VFS](https://github.com/liuhVIP/CD_Mods_Loader_VFS)
and [Ultimate ASI Loader](https://github.com/ThirteenAG/Ultimate-ASI-Loader).
The latter's source exposes deferred startup through imported APIs and its
`InitializeASI` callback. Its documented behavior is not evidence of CDMW's
timing. Crimson Loadouts' resource-loading and CreateFile2 observer are read-only
research references; mesh/texture resource access does not establish item
registration or save identity.

The next isolated discovery experiment must expose two uniquely named definition
pairs without changing the original item tables and inspect both actual registries
and auxiliary references. A file-open trace alone is insufficient. If an extra
shared manifest is needed, that remains a composition requirement. This probe is
not yet enabled because the verified startup/redirection boundary is unresolved.

## Evidence gates and validation

1. **Loading map:** static executable leads and a controlled refusal witness;
   deterministic bootstrap timing remains blocked.
2. **Synthetic prototype:** profile composition, colliding authors, imported assets
   and auxiliary references, update/transfer, recovery, stale state, Qt/Rust input
   projection, native handles and session isolation have focused fixture coverage.
3. **Controlled game prototype:** the reviewed original-file diagnostic reached
   CDMW initialization and refused the bootstrap's existing hook. No redirected
   game read or new-item acceptance is claimed.
4. **Selectable experimental item loading:** blocked pending the earlier timing
   gate, verified Steam behavior, coexistence, acquisition/equipment/crafting and
   save/reload/update/removal acceptance with a disposable backed-up save.

Source tests, built native binaries, packaged application, visible game behavior
and save compatibility are separate evidence classes. The diagnostic observations
do not certify item registration. Machine-specific traces, save backups and game
payloads stay outside version control.

Focused commands from the project root (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader.py tests/test_virtual_loader_runtime.py tests/test_virtual_loader_ui.py -q --basetemp "$env:TEMP\cdmw-virtual-loader"
.\.venv\Scripts\python.exe scripts/build_virtual_loader.py
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader_native.py -q --basetemp "$env:TEMP\cdmw-virtual-native"
```

The native sources, build instructions and provenance contract are described in
[`native/cdmw_virtual_loader/README.md`](../../../native/cdmw_virtual_loader/README.md).
