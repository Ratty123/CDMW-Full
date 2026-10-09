# Virtual loader (Experimental)

Mod Management opens a combined **Mods** list. New `.cditem` packages and supported
extracted or archive mod folders use **Apply changes**, then **Launch game**.
The list identifies their experimental CDMW launch route alongside physical installs
and external archive folders. Existing authoring and manager exports remain available;
physical install and identity tools are under **Advanced**. Existing installs never
move between physical and virtual ownership automatically.

**Current availability: reviewed experimental launches on the verified Windows
x64 executable and ASI bootstrap.** Each launch requires a fresh verified save
backup and an explicit **Launch game** click in CDMW. Item and effect compatibility remains experimental;
only the configurations documented below have controlled game evidence.
The general redirect mode remains disabled in Python and the native runtime;
the page uses the guarded controlled-launch mode.
The controlled startup probe resolved the verified ASI bootstrap's retained
forwarding hooks. Steam process binding now has a separate claim/readiness
handshake. Warm- and cold-Steam diagnostics reach the title screen, with
independent Windows traces showing readiness before the first game archive read.
The observed startup call site now has an exact-build activation guard. A separate
reviewed controlled-probe route permits real-game acceptance testing. CDMW's
experimental launch now enforces its save-backup requirement. Its first run redirects the prepared metadata and archive
pair while the physical game archive directory remains absent. The user confirms
both test items appear in the camp equipment shop, equip correctly and return in
the saved inventory after restarting with the same virtual profile. A subsequent
display-name update also reaches both saved items without repurchase and retains
their ability to equip. Removing one package also removes its shop entry while
the other saved item still equips. Restoring the original packages in reverse
order recovers both saved swords under their original names without repurchase.
Asset/behavior updates and the broader support matrix still require game
validation; changing a manifest cannot enable the general redirect mode.

## Use and ownership

The main list uses the full width, with Apply and Launch above it and contextual
actions below. Sort by name, type, loading method or status using the list headings; this
changes display order only, preserving the prepared selection and identity allocation
order. Hover over a filename for its complete path. Buttons have brief hover help.
Optional loader setup, diagnostics and recovery are under **Loader details** below the list.
The workspace's **Advanced** tab groups archive health and recovery, separate package
preparation, and item identity tools.

Preparation shows a percentage and the current stage. The percentage follows completed
stages and source files, not an estimate of elapsed or remaining time. It reaches 100%
only after the parent accepts the complete worker result. Apply then saves the
profile automatically. Saving has its own busy indicator; completion hides the bar
and shows **Profile applied. Ready to launch.** Cancelled, failed or outdated
preparation results cannot publish a profile or enable launch.

Launch reports runtime checks, save backup, file verification, Steam handoff and
runtime readiness. The host's verification percentage follows bytes actually read;
100% means the runtime acknowledged readiness, not that the title screen has loaded.
Session status uses a separate read-only lookup, so polling does not toggle the page's
busy state or repeatedly refresh Mod Management's inventory.

1. With the game closed, add packages or mod folders and choose **Apply changes**.
   CDMW checks the loader, prepares compatible inputs, then publishes the private
   snapshot and identity ledger together. Original game archives and their
   mount/texture metadata are unchanged. No separate Save step is needed.
2. The first loader installation asks for confirmation in this flow and explains
   automatic future updates. Later Apply or Launch clicks update only an unchanged,
   recorded CDMW-owned loader, retaining a verified backup and rollback. A current
   loader is left untouched. Modified or unowned loader files, an incompatible
   executable/bootstrap or a running game stop the operation with an explanation.
3. When the profile is ready, choose **Launch game**. CDMW verifies a fresh save
   backup, logs its location and rechecks the profile before starting through Steam.
   The click authorizes this launch; no second confirmation interrupts the flow.
   Missing or outdated loaders are handled here too, including after reopening CDMW.
   Changed saves, packages, game files or identities still block launch. A changed
   selection needs **Apply changes** again. **Cancel** stops preparation or launch
   preparation; saving and loader publication finish atomically. It does not
   terminate a game after the session host takes ownership.
4. Load and save with the intended profile active. **Open save backups** opens
   retained copies for recovery. Closing CDMW leaves a started game running.

Saves are copied from `%LOCALAPPDATA%/Pearl Abyss/CD/save` to
`<game>/.cdmw/virtual-loader/save-backups/<backup-id>/files`. Every file and the
complete inventory are verified; linked paths, missing saves and backups over
4 GiB or 4,096 files are refused. A completed backup is published in one rename;
cancellation or failure removes only the new temporary copy. Previous backups
remain available. The session host also checks the reviewed saves and backup
hashes before launch; save files are never redirected. CDMW never edits or
automatically restores live saves. To recover manually, close the game, retain
a copy of the current save folder and restore the selected backup's `files`
contents to that save folder, preserving its account and slot directories.

There is one saved virtual profile per installation. Changing the selection takes
effect after preparation and publication, never during a running session. Remove
an item from the selection and save a new profile to remove its virtual
contribution. Its identity remains reserved because saves may reference it.

The same UUID cannot be active through both installation routes. To move a
physically installed item, use the mod list's existing reviewed **Remove**
operation first; disabling it is insufficient. Then select the same package here.
Moving back requires removing it from the saved virtual profile before physical
installation. Nothing moves automatically, and CDMW does not edit saves.

Advanced's Item identities `.cdprofile` export/import transfers the same identity ledger
for both routes. Virtual ownership is separate from physical overlay ownership;
it does not create fake installed-overlay IDs. After transferring identities,
prepare the packages again against the destination's actual game data.

## Save lineage and migration admission

Current launch checks prove that the reviewed save files and their backup have
not changed before the session starts. They do not determine which profile
created a save, which providers it needs, or whether a changed profile can read
it safely. In the backup manifest, `profile_sha256` and `generation` identify the
**proposed launch**, not the save's origin. The `.cdprofile` identity ledger also
contains no per-save origin or compatibility certificate.

| Situation | Current result |
| --- | --- |
| Save, backup or proposed profile changes after review | Launch refuses and requires a fresh review |
| Selected package requires a missing installation provider | Profile composition refuses through its declared package graph |
| A save requires a provider absent from the selected profile | Unknown: no save parser or verified origin record identifies that requirement |
| Profile changes an existing item's saved behavior or representation | Unknown: stable integer IDs do not establish a valid state migration |
| A provider returns after saving without it | Unknown: restoring its ID cannot recreate state the intervening save discarded |
| Another launch route or game installation writes the same save folder | Outside the virtual file map; no save isolation or lineage enforcement exists |

A future admission gate needs an evidence-backed association between the exact
save bytes, their producing context, executable/build contract, package content,
allocation bindings and persistence schema. Unknown origin must stay unknown.
A known mismatch must refuse unless a separately verified migration covers that
exact transition. Missing-provider policies must state whether launch refuses,
an isolated context is required, or a proven migration is available. Package
metadata alone cannot authorize a state conversion. No such migration is
currently implemented; CDMW never rewrites a save to remove missing objects.

The first persistence witness must distinguish three experiments on disposable
copies: load with a provider absent without saving; write a new save while it is
absent; then restore the provider and load **that newly written save**. Record
the exact profile/ID mappings, executable and save hashes plus the observed
objects and state at each step. Recovering the original pre-removal save only
tests restoration of that original save. It does not prove the latter two cases.
Use separate copies for each experiment and keep the original recovery copy.

## Supported inputs

| Input or operation | Current preparation support | Refusal boundary |
| --- | --- | --- |
| `.cditem` v1 or v2 `item.legacy` | Existing identity, dependency, relocation and record composition services | The [independent-item format matrix](INDEPENDENT_ITEMS.md#supported-format-matrix) applies without expansion |
| `.cditem` v2 `item.fields` | Typed existing stack-count and stat-value assignments, composed in both deployment paths | Exact sources and recognized row layouts only; v1 requirements remain protected; gameplay/save effects are unverified |
| `.cditem` v2 `package.links` | Exact package release/content pins and typed references to exported legacy item identities | Providers must belong to the same selected virtual profile; game-reference relocation and save/runtime lifetimes remain unsupported |
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
Each new profile also records its compiler and adapter revisions and a compilation
identity linking packages, features, allocation bindings, sources, composition
order, runtime protocol and output hashes. A profile with
an older, different or unrecorded compiler remains readable for recovery but cannot
launch: use **Apply changes** to regenerate it while retaining item identities.
Older CDMW versions that cannot read this profile record refuse it rather than
assuming compatibility. V1 item packages retain their wire format. Field-only v2
packages use the v2 identity ledger described in [Independent items](INDEPENDENT_ITEMS.md#existing-iteminfo-field-operations).

**Apply changes** runs its CPU-heavy preparation in an owned background process
so table parsing and composition do not contend with the GUI's Python execution.
The existing controller owns progress, cancellation and stale-result rejection;
closing the page cancels the helper without waiting on the UI thread. Its private
temporary files are removed only after it exits. A bounded data-only result carries
the same source, provider and ownership guards back to automatic profile publication.
The asset collision index is built once per preparation, only when new assets need
it, using the existing native PA hash implementation for large path batches. An older
or unavailable helper retains the exact scalar checks. Ambiguous hashes, retained
reservations and earlier items remain part of the index. Source archives are hashed
afresh with at most two concurrent readers; no content digest is reused across runs.
The existing revision checks still bracket preparation and protect publication. Large
installations can still take time because all relevant source files are verified.

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

If Windows refuses a runtime file with error 225 or 226, CDMW reports the file and
build hash and blocks further attempts with those same bytes for the rest of the
app session. No quarantine restoration, exclusion, security setting change or
fallback launch is performed. Resolve the detection before restarting CDMW to
retry. A matching build hash establishes provenance, not that an antivirus result
is a false positive; use [Microsoft's developer submission portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
for detection review. Launch still verifies every recorded game and mod file.
The UI worker checks the selected packages, prepared output, inventories and save
backup. The native host performs the full source-content check once under its
installation lease, using two bounded readers with sequential I/O and byte progress.
It pins game inputs before hashing and keeps those handles through the session;
Steam cannot start until all checks pass. No timestamp-only shortcut or cached
content digest substitutes for the recorded hashes. Standalone snapshot verification
and diagnostic entry points retain their complete checks.

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

For low-level controlled acceptance, `start_controlled_probe` requires an explicit reviewed
launch plan and confirmation that the caller retained a verified save backup.
It revalidates the complete prepared profile and starts the native host with the
separate `--controlled-probe` opt-in. The experimental page uses
`prepare_experimental_launch` and `launch_experimental` to enforce verified save
backups before selecting that same native mode after the user's Launch click. Existing low-level
entry points retain their defaults; ordinary launches remain inactive.
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
   The virtual route also covers updating one item, removing the other and
   reinstalling in reverse order while retaining a disjoint external ItemInfo
   edit, for both loose-file and archive mods. It checks saved identities, shop
   stock, displayed names, immutable earlier snapshots and unchanged source
   files. A conflicting template-record edit refuses without replacing the
   usable profile. These are synthetic composition checks, not game/save proof.
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
   A later controlled launch updates copies of both packages with visible name
   suffixes while preserving their UUIDs and all item, perk, recipe and asset
   bindings. The composed payload changes only localization records; the user
   confirms both already-owned swords show the updated names and still equip
   without repurchase. The native trace separately confirms the guarded startup
   and all four mapped file opens. Original packages and the earlier snapshot
   remain unchanged. Another controlled profile removes test3 and retains the
   updated test4. Parsed output has no test3 definition, shop stock, group
   membership, owned auxiliary records, localization or assets; test4's owned
   contribution is intact and both identities remain reserved. The user confirms
   test3 is absent from the camp shop and saved test4 still equips. The native
   trace separately confirms redirection to that one-item snapshot. Restoring
   the original package files in reverse selection order reproduces the original
   identity ledger exactly, including auxiliary identities and asset paths.
   Parsed records match the original two-item view; differences are table order
   and the owned shop entries' positions. The guarded launch redirects the
   restored snapshot, and the user confirms both swords return from the original
   manual save under their original names and equip without repurchase. This
   completes acquisition, same-profile save/reload, name update, partial removal
   and reinstallation for these two imported-model swords. Saving with an absent
   item, asset/behavior updates and other configurations remain unverified.
   Verified save backups are retained from before the controlled launches.
   The final full comparison matches all 228 original archive and metadata
   files to their pre-test hashes. The physical overlay directory is still
   absent; original packages, restored identities and active snapshot hashes
   also match their expected values.
   A further real-data preparation uses separate clean authoring snapshots for
   a stock Hwando model and an imported model. Both deliberately receive the
   same temporary item, perk, recipe, reward and icon identities. The published
   four-item view gives the new packages disjoint bindings while preserving
   test3/test4's reservations, records and assets. Its audit resolves two custom
   icons through StringInfo, the icon list and PATHC; three owned perks and
   fourteen owned recipe/output pairs per item; names in all fifteen language
   tables; and the imported item's owned effect, emitter and render preset.
   Each new item has a first-refinement ingredient override for the game check.
   An attempted effect on the stock model correctly refuses export because it
   would copy an unverified physics file; this template test instead retains
   the original model and physics as game dependencies. Save backups precede
   publication. The guarded launch redirects the reviewed four-file snapshot;
   the checked physical mount/texture metadata and game-data archive pair still
   match their initial hashes, and the virtual archive directory remains absent
   from the game root. User screenshots show the expected stock/imported models,
   the supplied green/blue test icons and perk labels. The user confirms that
   the imported item equips and that refinement works. The intended blue effect
   is absent. Inspection found an embedded emitter file type still naming the
   original emitter after its ordinary reference was rebound; a focused fix now
   rebinds and validates both references. A controlled retry changes only that
   reference, preserves the identities and all other composed payloads, and
   passes guarded redirection; the user still reports no visible blue effect.
   The structural fix is therefore insufficient to establish effect activation.
   A subsequent candle-effect comparison keeps the imported item's identity and
   uses the stock `fx_fire_bg_a__candle1.level.effect`, alongside a separately
   bound blue clone with no emitter filtering. Its composed output preserves
   existing item records and identities and passes guarded redirection. The user
   reports success; screenshots show both flame colours in the shop and the blue
   effect on the equipped weapon outside the shop. This establishes appearance
   for that candle effect and its clone. Following a fresh verified save backup,
   a guarded relaunch uses the same snapshot and identity ledger. The user
   confirms that both swords remain in inventory and both flames appear when
   equipped after loading the saved game. This passes the same-profile
   save/reload check for the two candle-effect items. The earlier fire-attach
   failure remains unresolved.
4. **Selectable experimental item loading:** available for user-led compatibility
   tests through the guarded launch and verified backup workflow. Focused tests
   cover backup integrity, cancellation, changed saves/sources, native save
   guards, stale selection/review rejection and the Qt/Rust launch controls.
   This does not certify broader runtime coexistence, other item configurations,
   saving with removed items or all asset/behavior updates. Those game checks
   remain separate from the delivered application workflow.

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
