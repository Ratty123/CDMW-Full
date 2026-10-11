# CDMW virtual runtime prototype

Windows x64, C++20, Windows SDK, CMake and MSVC. No downloaded injection framework
or third-party hooking library is used. The sources are `protocol.cpp/.hpp`,
`runtime.cpp`, `bootstrap.cpp/.hpp`, `session.cpp` and the synthetic `harness.cpp`.

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

`CDVFS2` is a bounded, data-only local protocol: mode, intended game/host PIDs,
executable hash, canonical installation/generation/session/lease identities,
exact mapped files, source guards and the selected Steam client path/hash. Old
transient launch descriptors are refused; saved item/identity/profile formats
are unchanged. Trace mode observes original files;
production redirect mode is compiled off; harness mode requires the separate
test host, test ASI and fixture executable. Controlled probe mode additionally requires the host's
`--controlled-probe` opt-in and the verified early startup path. It is a reviewed
acceptance route. CDMW's experimental page now selects it only after creating
and verifying a save backup following the user's Launch click. The private named pipe rejects
remote clients and validates its user, server and client. No network listener or environment-only activation
is used. Session descriptors are not distributable mod packages.

The experimental UI checks its saved output, selected packages, inventories and
save backup before handing off. The host owns the full source-content verification
under the installation lease; the UI does not repeat the complete archive scan.
Two readers hash the guarded inputs and snapshot with sequential I/O, reporting
byte-based progress. Game inputs are pinned before hashing and retained for the
session. A mismatch prevents process creation. No cached digest or timestamp-only
check replaces the expected hashes. Status reports add an optional `progress`
percentage; older reports remain readable. Verification reaches 90%, Steam handoff
95%, runtime binding 98%, and acknowledged readiness 100%.

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
