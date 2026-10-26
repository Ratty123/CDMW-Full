# CDMW virtual runtime prototype

Windows x64, C++20, Windows SDK, CMake and MSVC. No downloaded injection framework
or third-party hooking library is used. The sources are `protocol.cpp/.hpp`,
`runtime.cpp`, `bootstrap.cpp/.hpp`, `compose_launch.cpp/.hpp`, `session.cpp` and the
synthetic `harness.cpp`. The runtime links the portable
[item composer](../cdmw_item_composer/README.md) library, whose sources are part of
the provenance.

Run `.\.venv\Scripts\python.exe scripts/build_virtual_loader.py` from the repository
root. It configures the x64 Release
build, compiles with `/W4 /WX /guard:cf`, runs CTest and writes `provenance.json`
containing source hashes, artifact hashes, repository revision and the closed
game-redirection gate. Build output is local and ignored by Git. Release packaging
includes only `Release/CDMWVirtualLoader.asi`, `Release/cdmw_virtual_session.exe`
and their provenance. Both production binaries reject synthetic test mode before
activation or session creation. Their Windows file properties identify CDMW,
the component, original filename and current application version. The resource
template, build script and shared application metadata are included in source
provenance. These resources are identification metadata, not a digital signature
or evidence that antivirus detection has been resolved.

Synthetic tests use a separate protocol library compiled with
`CDMW_VIRTUAL_TESTING`, `tests/Release/cdmw_virtual_session_test.exe`,
`tests/Release/CDMWVirtualLoaderTest.asi` and the harness in that same test folder.
The test loader is copied to the normal ASI name inside each disposable fixture.
Suspended fixture launches and synthetic Steam arguments are compiled only into
the test session host. Test outputs are not listed in release provenance or the
packaging allowlist. Run the native behavior and version-resource checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader_native.py -q --basetemp "$env:TEMP\cdmw-virtual-native"
```

Local Defender file scans should record the exact artifact hash and intelligence
version. A clean scan does not establish packaged or game-launch acceptance;
neither rebuilding nor adding metadata proves a prior detection was incorrect.

The ASI exports `InitializeASI` and `CdmwVirtualState`. Its `DllMain` performs no
file I/O, hook installation, thread creation or blocking waits. Initialization
outside CDMW's own DllMain is necessary but does not establish freedom from a
calling bootstrap's loader lock or readiness before game-data reads.

`CDVFS3` is the current bounded, data-only local protocol: mode, intended game/host
PIDs, executable hash, canonical installation/generation/session/lease identities,
exact mapped files, required content guards, catalogue metadata guards and the
selected Steam client path/hash. The native reader also understands `CDVFS2`
descriptors without catalogue guards; unknown versions refuse. Current compiler
identity requires older saved profiles to be applied again. Portable item formats
and retained numeric identities are unchanged. Trace mode observes original files;
production redirect mode is compiled off; harness mode requires the separate
test host, test ASI and fixture executable. Controlled probe mode additionally requires the host's
`--controlled-probe` opt-in and the verified early startup path. It is a reviewed
acceptance route. CDMW's experimental page now selects it only after creating
and verifying a save backup following the user's Launch click. The private named pipe rejects
remote clients and validates its user, server and client. No network listener or environment-only activation
is used. Session descriptors are not distributable mod packages.

The experimental UI checks the saved profile, output presence, selected packages,
inventories and save backup before handing off. The host hashes the prepared
outputs and all required source content under the installation lease; the UI does
not repeat those output hashes or the complete archive scan.
Two readers hash the guarded inputs and snapshot with sequential I/O, reporting
byte-based progress. Game inputs are pinned before hashing and retained for the
session. A mismatch prevents process creation. No cached digest or timestamp-only
check replaces the expected hashes. Status reports add an optional `progress`
percentage, checked/total bytes, elapsed time and current filenames. Refusals
identify the affected source or snapshot. Older reports remain readable.
Verification reaches 90%, Steam handoff
95%, runtime binding 98%, and acknowledged readiness 100%.

Catalogue metadata guards apply only to otherwise unused PAZ carriers after every
v1 recipe completes a verified reference traversal. Borrowed formats without a
proven traversal, borrowed HKX, other module combinations and external or active
mounted providers retain the full carrier content checks. Parsed PAMT hashes,
mount and registry content, actual compilation payloads and runtime-only resource
dependencies remain required content. Catalogue-only guards retain presence,
size and last-write time, reject reparse paths and pin real file handles for the
session. Unrelated byte changes with unchanged metadata are permitted by that
policy; they are not cached content hashes. Python additionally checks its captured
file stamps during preparation/publication and preflight. The ASI's independent
snapshot-content checks remain in place.

The UI's Apply action prepares and publishes the profile in one flow. Apply and
Launch also handle loader setup: the first installation requires confirmation;
later updates require matching recorded ownership, preserve recovery copies and
roll back on failure. Unowned or modified files are refused. The current loader
is not rewritten. A routine launch verifies its backup and proceeds without a
second dialog; the launch service still requires explicit confirmation from its caller.

The host validates inputs, refuses an existing game, publishes a pending request,
then asks Steam to launch app 3321460. The runtime claims that request through the
private pipe. The host binds only a newly created process with the exact game
path/hash and a live, older parent matching the selected Steam path/hash. It
publishes the bound descriptor and acknowledges the claim before the runtime
installs hooks and reports readiness. The short-lived Steam command process is
not the game. Claims and readiness have bounded waits. The direct suspended-child
path exists only in the test host. The host holds the first lease byte;
the runtime retains the second for process lifetime. Python installation actions
lock both. The runtime pins snapshots and its module even if the host dies. The
host does not kill a successful game on UI shutdown and cannot silently accept a
Steam-created replacement process.

Hooks replace only verified main-image import slots for the supported open/query/
enumeration functions. Exact paths resolve to real snapshot files; Windows owns
the returned handles. No package parser, ID allocator or record composer runs
inside a hook. Unknown existing hooks refuse with their function and module.
The fixed trace has at most 4096 records; a worker flushes them without allocation
or output-file writes in the hooks. A zero-length trace after refusal establishes
no intercepted game-data read.

The synthetic harness checks file opens, attributes, enumeration, mapping,
asynchronous/concurrent reads, path aliases, write refusal and original errors.
Python tests additionally exercise the host handshake, corrupt snapshots, the
closed production gate, controlled-probe opt-in, ordinary inert loading and
process-lifetime leases. Startup tests reject a worker thread, truncated or
reordered return frames, a different game caller, late initialization and changed
bootstrap instruction/forwarding witnesses.

The exact Ultimate ASI Loader 9.7.1 bootstrap can leave temporary forwarding
imports in read-only IAT pages after its restoration phase. CDMW chains through
only its verified wrappers: whole-file hash, module location, code/instruction
witnesses, completed handoff flags, and original system forwarding destinations
must all match. Other hooks remain a refusal. The existing bootstrap is neither
modified nor replaced. The controlled diagnostic passed these guards and reported
initialization outside an ntdll loader callout; this alone is not proof of
readiness before every affected game read. The fixture also checks mutated
instructions, handoff flags, forwarding destinations and bootstrap hashes.

Controlled warm- and cold-Steam diagnostics stay bound to the real game and
reach the title screen. Independent Windows file-mode recordings retain process
creation and show the game's first mount-table read after the host receives
runtime readiness. The early archive queries come from CDMW's own manifest path
validation; the cold-start call stacks identify that boundary through UAL's
`GetCommandLineW` wrapper. Game redirection now requires that ordered return chain:
UAL RVAs `0x21785`, `0x308e8`, `0x32e13`, `0x1f848`, followed by game RVA
`0x10958a48`. The runtime verifies UAL's complete `GetCommandLineW` wrapper and
system forwarding destination, completed bootstrap phases, the earliest live
process thread, and an outside-loader-callout result. It refuses before hooking
if any witness is missing. This is an executable-specific startup boundary, not
an item-registration ABI. The guard runs after Steam process binding, allowing
the host to terminate its verified new game on refusal. Trace records distinguish
the startup guard result from completion of all import hooks.

Controlled game acceptance additionally requires a verified save backup and
reviewed launch plan. The experimental UI enforces these through
`prepare_experimental_launch` and `launch_experimental`; `start_controlled_probe`
remains the low-level acceptance entry point. Save and backup hashes use the
existing source-guard protocol; they never become redirection targets. The
general redirect-mode gate stays closed pending broader compatibility validation. The
source lead for the retained wrappers is the exact
[UAL 9.7.1 implementation](https://github.com/ThirteenAG/Ultimate-ASI-Loader/blob/v9.7.1/source/dllmain.cpp);
the reviewed local binary witnesses, not a project version label, govern support.

The first controlled profile run passes the startup guard and records redirected
opens for its PAPGT, PATHC and private PAMT/PAZ pair. The virtual archive directory
is absent from the physical game root. Hook installation completes before the
first redirected mount-table open. Separately, the user reports that both test
items appear in the camp equipment shop and equip correctly. A second guarded
launch reuses the same profile and identities; the user confirms both swords
return from the manual save and equip without repurchase. This is save/reload
evidence for that two-item profile. A further guarded launch uses name-only
updates to copies of both packages with the same identities and assets. The user
confirms both saved swords receive the updated names and still equip without
repurchase. A subsequent guarded profile removes test3 while retaining test4;
the user confirms test3 is absent from the camp shop and saved test4 still
equips. Both identities remain reserved. Restoring the original packages in
reverse selection order reproduces the original identity ledger. The next
guarded launch redirects that restored snapshot; the user confirms both swords
return from the original manual save under their original names and equip
without repurchase. This completes the tested two-item lifecycle. Saving with
an absent item, asset/behavior updates and broader item/save coverage remain
unverified; the public release gate stays closed.

Do not poll until an unknown hook disappears or promote game loading based on
the harness. The
[feature loading map and acceptance gates](../../cdmw/ui/new_item/VIRTUAL_LOADER.md)
are the authoritative scope and limitations.

## Launcher-independent profiles

Standalone mode 4 lets the runtime load an applied profile when CDMW did not start
the game, for example from Steam or a mod manager such as DMM. CDMW publishes
`.cdmw/virtual-loader/standalone.bin` (same `CDVFS3` format, no PIDs, host or
launcher) only after the runtime setup is current and every source and prepared
file has been hashed. When no session descriptor exists, the runtime reads that
profile and, before hooking any import, checks the exact game executable, the
verified early startup path, every content guard (indexes, sources up to 1 MiB, the
installed runtime, the bootstrap and CDMW's own state files), size and write time
for larger carriers, and the prepared snapshot hashes. It then takes the
installation lease, so CDMW cannot change the installation while the game runs.
Any mismatch leaves the game unmodded. Each launch writes
`standalone-status.json` (`ready` or `refused` with the reason) and a bounded
`trace-standalone.bin`. Other programs in `bin64` that load the bootstrap, such as the
crash handler that starts with every launch, leave both files alone and stay inert.
A mod manager that rebuilds PAPGT or PATHC after CDMW applied the profile with
different content makes it stale; apply and publish again.

Recorded 2026-10-25 on game 2.03.02 with UAL 9.7.4: the headless Steam smoke passed,
and a launch from DMM loaded a five-sword profile published against DMM's mount. The
runtime reported ready in the game's process with the expected redirects, and the
user confirmed all five items in game. Save/reload and removal under a standalone
profile are untested. The feature map's evidence gates hold the details.

```powershell
.\.venv\Scripts\python.exe scripts/cditem_standalone.py --game-root "<game>" update-runtime
.\.venv\Scripts\python.exe scripts/cditem_standalone.py --game-root "<game>" publish
.\.venv\Scripts\python.exe scripts/cditem_standalone.py --game-root "<game>" status
.\.venv\Scripts\python.exe scripts/cditem_standalone.py --game-root "<game>" smoke
.\.venv\Scripts\python.exe scripts/cditem_standalone.py --game-root "<game>" withdraw
```

`smoke` launches through Steam, waits for the runtime's report and for redirected
opens of `meta/0.papgt` and the profile's private group index, closes only the
process the report names (`WM_CLOSE`, then termination), and confirms PAPGT,
PATHC, every group PAMT, the runtime and the bootstrap are unchanged. It sends no
input and captures no screen. Reports go to `workspace/reports/cditem-smoke/`.
A pass shows the files were served at startup; it does not show the items in a
shop or inventory.

## Launch-time composition (milestone 2, provisional input)

When `.cdmw/virtual-loader/compose/` holds change sets (`*.cdchanges`), a launch
CDMW did not start composes them instead of loading a standalone profile; without
change sets the standalone profile applies as before. A change set holds one
package's owned changes (each path's file before and after the package, its archive
flags and whether it is mount metadata) in the provisional `CDMWCHG1` format that
`cdmw_item_composer` parses. Packages compose in file-name order. The format is a
stand-in until `.cditem` packages carry their own `runtime/` members; CDMW does not
write change sets yet, so a test writes them from its own resolve.

The runtime checks the exact game executable and the verified early startup path,
takes the installation lease, and then merges the change sets onto what the game
reads today: the groups `meta/0.papgt` lists, DMM's included, and `meta/0.pathc`.
The changed files become a private group under the first free name from `0036`,
mounted first, as CDMW's Apply builds it. The result is cached in
`.cdmw/virtual-loader/compose-cache/<key>/`. The key covers the runtime, the game
build, the mount list, the group name and each change set's name, size and write
time. A launch reuses the cache only after it re-verifies every source the
composition read (hashed up to 1 MiB, size and write time beyond, as a standalone
profile keeps its carriers) and hashes each output. A changed source composes again
from the current files, so a DMM remount no longer invalidates the items. All
sources and outputs are pinned read-only for the session. Conflicting packages,
unreadable change sets and input outside the composer's exact subset refuse and
leave the game unmodded. Each launch writes `compose-status.json` (`ready` or
`refused`, cache `composed` or `reused`, the group, counts, stage times and the
reason) and `trace-compose.bin`, whose code-14 row names the composition.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_virtual_loader_compose.py -q --basetemp "$env:TEMP\cdmw-virtual-compose"
```

These harness checks compose two packages over a synthetic install with DMM's group
mounted and read the mapped files back through the hooks. The files must equal CDMW's
own composition, and the reuse, reorder, remount, conflict, malformed-input, lease and
precedence cases are covered. They are synthetic; the in-game record follows below.

The runtime composes on the startup thread alone. On UAL's startup path a new thread
does not run until `InitializeASI` returns, so a composition that waits for worker
threads never finishes. Before composing, the report records whether a new thread ran
within a second (`worker_thread`) and whether the startup thread holds the loader lock
(`loader_lock`); a `composing` report is written first, so a launch that stops there
shows where.

Recorded 2026-10-26 on game 2.03.02 with UAL 9.7.4 and DMM's group mounted, using
headless Steam launches that closed at the title screen:

- The first build composed with worker threads; it wrote no report within 300 s and the
  game never opened a window, so the check ended it. Protected files were unchanged.
- Runtime `74336eda`, composing on the startup thread, read five change sets taken from
  CDMW's resolve of the five applied Wolf Trial packages. It recorded `worker_thread` 0
  with the loader lock free, composed 170 files in 6.2 s and reported ready 7.75 s into
  startup. The game opened the composed `meta/0.papgt`, `meta/0.pathc` and the private
  `0042/0.pamt` and `0.paz` through the hooks, closed on request, and all 40 protected
  files were unchanged. The cached view is byte-identical to the one CDMW's Apply had
  published for those packages, which the user had confirmed in game.
- The next launch reused the cache and was ready in 312 ms, with the same redirects.

Those headless launches did not look at items. Later that morning, with compose mode
enabled on the user's install, a launch the user started reused the cache (ready in
328 ms) and opened the composed files through the hooks, and the user found all five
swords in the inventory of their loaded save. Saving under compose mode and a real DMM
remount remain untested.

## Independent item publication research

The separate [paired-publication experiment](research/README.md) prepares both
item identity maps and their owned fixture backing before publication. Its
standalone C++20 checks cover refusal, visibility, reentry and lifetime. Both
lookup paths, decoded rows and resource completion are modeled. The research
subdirectory is outside the production CMake targets and source provenance;
its focused isolated build does not rebuild or enable this runtime.
