# CDMW virtual runtime prototype

Windows x64, C++20, Windows SDK, CMake and MSVC. No downloaded injection framework
or third-party hooking library is used. The sources are `protocol.cpp/.hpp`,
`runtime.cpp`, `bootstrap.cpp/.hpp`, `session.cpp` and the synthetic `harness.cpp`.

Run `.\.venv\Scripts\python.exe scripts/build_virtual_loader.py` from the repository
root. It configures the x64 Release
build, compiles with `/W4 /WX /guard:cf`, runs CTest and writes `provenance.json`
containing source hashes, artifact hashes, repository revision and the closed
game-redirection gate. Build output is local and ignored by Git. Release packaging
includes the ASI, session host and provenance, not the test harness.

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
fixture executable. The private named pipe rejects remote clients and validates
its user, server and client. No network listener or environment-only activation
is used. Session descriptors are not distributable mod packages.

The host validates inputs, refuses an existing game, publishes a pending request,
then asks Steam to launch app 3321460. The runtime claims that request through the
private pipe. The host binds only a newly created process with the exact game
path/hash and a live, older parent matching the selected Steam path/hash. It
publishes the bound descriptor and acknowledges the claim before the runtime
installs hooks and reports readiness. The short-lived Steam command process is
not the game. Claims and readiness have bounded waits. The direct suspended-child
path is reserved for synthetic fixtures. It holds the first lease byte;
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
closed production gate, ordinary inert loading and process-lifetime leases.

The exact Ultimate ASI Loader 9.7.1 bootstrap can leave temporary forwarding
imports in read-only IAT pages after its restoration phase. CDMW chains through
only its verified wrappers: whole-file hash, module location, code/instruction
witnesses, completed handoff flags, and original system forwarding destinations
must all match. Other hooks remain a refusal. The existing bootstrap is neither
modified nor replaced. The controlled diagnostic passed these guards and reported
initialization outside an ntdll loader callout; this alone is not proof of
readiness before every affected game read. The fixture also checks mutated
instructions, handoff flags, forwarding destinations and bootstrap hashes.

The controlled warm-Steam diagnostic now stays bound to the real game, reaches
the title screen and observes its archive/metadata opens. A circular Windows
file trace did not retain the process start, so zero dropped events is not
sufficient first-read evidence. Game redirection remains gated. The source lead
for the retained wrappers is the exact
[UAL 9.7.1 implementation](https://github.com/ThirteenAG/Ultimate-ASI-Loader/blob/v9.7.1/source/dllmain.cpp);
the reviewed local binary witnesses, not a project version label, govern support.

Do not poll until an unknown hook disappears or promote game loading based on
the harness. The
[feature loading map and acceptance gates](../../cdmw/ui/new_item/VIRTUAL_LOADER.md)
are the authoritative scope and limitations.
