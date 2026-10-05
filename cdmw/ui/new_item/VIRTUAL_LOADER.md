# Virtual loader (Experimental)

Mod Management has a separate **Virtual loader (Experimental)** page beside
Independent items. It prepares a private startup profile from `.cditem` packages
and supported extracted or archive mod folders. Existing authoring, manager export
and physical installation remain the defaults.

**Current availability: profile preparation and reviewed startup diagnostics.**
The public game-loading gate remains disabled in Python and the native runtime.
The controlled startup probe resolved the verified ASI bootstrap's retained
forwarding hooks. Steam process binding now has a separate claim/readiness
handshake. Warm- and cold-Steam diagnostics reach the title screen, with
independent Windows traces showing readiness before the first game archive read.
The observed startup call site now has an exact-build activation guard. A separate
reviewed controlled-probe route permits real-game acceptance testing with a
verified save backup. Its first run redirects the prepared metadata and archive
pair while the physical game archive directory remains absent. The user confirms
both test items appear in the camp equipment shop, equip correctly and return in
the saved inventory after restarting with the same virtual profile. Updates,
removal/reinstallation and the broader support matrix still require game
validation; changing a manifest cannot enable the public launch mode.

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

For controlled acceptance, `start_controlled_probe` requires an explicit reviewed
launch plan and confirmation that the caller retained a verified save backup.
It revalidates the complete prepared profile and starts the native host with the
separate `--controlled-probe` opt-in. This route is not exposed by the normal UI.
The host checks the exact game/Steam identities and the runtime refuses a changed,
late or unrecognized startup path before installing file hooks. A trace marker
records hook installation completion separately from entry into initialization.

| Boundary | Observation and limitation |
| --- | --- |
| ASI bootstrap | Calls `InitializeASI`; CDMW's `DllMain` only disables thread notifications. The exact UAL 9.7.1 build can retain forwarding imports after restoration. CDMW verifies the binary, instructions, phase flags and original forwarding targets before chaining. Independent cold-start stacks locate initialization through UAL's `GetCommandLineW` wrapper on the initial game thread, outside the ntdll loader callout. Redirection requires that exact ordered return chain and game caller, verified wrapper instructions and forwarding, the earliest live thread, and no loader callout. |
| File opens | Exact main-image imports of `CreateFileW`, `CreateFileA` and `CreateFile2`; the verified executable's CreateFile2 IAT RVA is `0x51eb158`. Independent Windows events and native traces match the observed original archive opens. A cold-start mount-table stack passes through CDMW's hook from game RVA `0x13274b6`; this is a file-loading observation, not an item-registration API. |
| Queries/enumeration | Synthetic tests cover `GetFileAttributesW/A/ExW` and `FindFirstFileW/ExW`. The controlled Steam trace sees `CreateFile2` opening PAPGT/PAMT/PAZ/PATHC and W/ExW attribute queries on archive tables. Early original-file attribute queries match the manifest guard sequence and, in the cold trace, CDMW's validation call stacks. The first redirected profile run queries and opens its private archive pair despite that directory being absent from the physical game root. |
| Reads and mapping | Approved logical paths map to real immutable files. Windows retains read, seek, mapping and asynchronous-I/O semantics through its handles; no archive parsing occurs in hooks. |
| Unmapped paths | Original destinations; saves, configuration and executables are outside the redirect map. Mapped write access is refused. |
| Session | Private local pipe with owner ACL, PID and host checks, random token and exact executable/snapshot hashes. A new Steam game claims the pending launch; the host verifies its exact executable, parent and creation time before binding and granting initialization. Runtime readiness is a separate acknowledgement. |
| Steam handoff | Steam is asked to launch app 3321460; its command process may exit independently. Ambiguous clients, existing games, changed launcher binaries and a different parent are refused. Synthetic handoff/lifetime tests and controlled warm- and cold-Steam diagnostics pass. Virtual item acceptance remains separate. No environment-only activation is used. |

The native runtime refuses foreign import hooks and reports the function and
owning module. It neither chains through an unverified hook nor overwrites it.
If readiness fails after binding, the host terminates only the verified new game,
before accepting the session. An unverified claimant is never terminated. After
readiness it waits for game exit. Unsupported hook combinations
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
not yet enabled; controlled item and save acceptance takes priority over this
separate discovery experiment.

## Evidence gates and validation

1. **Loading map:** static executable leads, verified bootstrap forwarding,
   an outside-loader-callout witness and independent warm/cold first-read
   observations. An activation guard now enforces the observed startup call site,
   bootstrap phases, thread and loader-callout boundaries for controlled loading.
2. **Synthetic prototype:** profile composition, colliding authors, imported assets
   and auxiliary references, update/transfer, recovery, stale state, Qt/Rust input
   projection, native handles and session isolation have focused fixture coverage.
3. **Controlled game prototype:** the reviewed original-file diagnostic passed
   bootstrap forwarding checks and binds the actual Steam-created game. The
   user confirmed the title screen, including a cold Steam launch. Independent
   Windows file-mode traces retain process creation with no dropped events; the
   first game mount-table read occurs 0.72-0.75 seconds after CDMW's trace
   initialization and after the host's readiness acknowledgement. Each of the
   three complete captures has 228 earlier original-file attribute queries
   from CDMW's manifest validation and 173 subsequent archive opens/queries
   matched to native hooks. Cold-start stacks independently attribute all 228
   early queries to CDMW. The final capture's filename rundown resolves the
   earlier cached reads to the game executable, Windows disk metadata and the
   paging file. After all launches, the 286 checked original files and saved-game
   fingerprints are unchanged. Those captures are original-file diagnostics.
   A subsequent controlled virtual run passes the exact startup guard and records
   redirected PAPGT, PATHC, PAMT and PAZ opens for the prepared two-item profile.
   Its first redirected mount-table open follows completed hook installation by
   about 0.64 seconds; the mapped archive directory is absent from the physical
   game root. The user reports that both imported-model test items appear in the
   camp equipment shop and equip correctly. After saving, the user reports the
   item absent on an ordinary restart. A second controlled launch reuses the
   exact profile and identities and again passes the startup guard; the user
   confirms both items return in the manual save's inventory and equip without
   buying them again. This establishes user-observed save/reload for these two
   items with an unchanged profile, separately from the native file trace.
   Updates, removal/reinstallation and other configurations remain unverified.
   Verified save backups are retained from before both controlled launches.
4. **Selectable experimental item loading:** blocked pending broader controlled
   coexistence, acquisition/equipment/crafting, full supported item/save coverage
   and update/removal acceptance with a disposable backed-up save.

Source tests, built native binaries, packaged application, visible game behavior
and save compatibility are separate evidence classes. The diagnostic observations
do not certify item registration. Machine-specific traces, save backups and game
payloads stay outside version control.

Independent timing analysis must retain process creation and bind PID reuse to
that process lifetime. Use file-mode recording with `ProcessThread`, `Loader`,
`FileIO`, `FileIOInit` and `Filename`; include file-name rundown and
`FileCreate`/`FileQueryInformation` stacks when attributing early access. Compare
raw QPC timestamps with the native trace and distinguish CDMW's validation from
engine loading. Resolve cached/image reads through file keys within the same
recording; a later filename lookup can misidentify a reused key. A circular
recording that has overwritten startup, even with zero dropped events, is not
first-read evidence.

Focused commands from the project root (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader.py tests/test_virtual_loader_runtime.py tests/test_virtual_loader_ui.py -q --basetemp "$env:TEMP\cdmw-virtual-loader"
.\.venv\Scripts\python.exe scripts/build_virtual_loader.py
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader_native.py -q --basetemp "$env:TEMP\cdmw-virtual-native"
```

The native sources, build instructions and provenance contract are described in
[`native/cdmw_virtual_loader/README.md`](../../../native/cdmw_virtual_loader/README.md).
