# Tests

The `tests/` folder is regression coverage for implementation under `cdmw/`,
`native/`, and `tools/`, plus repository build, CI, and architecture contracts.
It is not application runtime code.

Prefer observable behavior: construct the owning surface, invoke its action,
and check the resulting state, payload or output. Literal source snippets do not
prove that a callback runs, and comments can accidentally satisfy them. Keep
static checks for genuine architecture, packaging and compatibility contracts;
do not freeze local variable names, statement order or old UI layouts.

The full runner discovers `test_*.py` automatically. A file omitted from the
short CI list is still selected by full QA; discovery does not establish when
it last ran or whether it remains valuable. Remove a test only when its requirement
is obsolete or another executable test covers it; a failure or an old filename
alone is not evidence for removal. Preserve cancellation, rollback, unsafe-output
refusal and compatibility coverage. Consolidate small related checks with their
existing owner instead of adding one module per implementation detail.

### Behavior owners

| Contract | Owning tests |
| --- | --- |
| Research display, notes and layout state | `test_research_state.py` |
| Research tree population and shared widgets | `test_research_tree_population.py`, `test_research_widgets.py` |
| Static preview status, modes, routing, batching and limits | `test_static_replacement_preview_status_state.py` |
| Archive HKX and binary preview ownership, imports and golden outputs | `test_archive_hkx_decomposition.py`, `test_archive_binary_preview_decomposition.py` |
| Prefab field meanings and path classification | `test_prefab_glossary.py` |
| Builder construction, parenting and current controls | `test_mesh_builder_construction_invariants.py`, `test_mesh_builder_construction_lifecycle.py`, `test_mesh_builder_runtime_wiring.py` |
| Preview presentation and acknowledged editor updates | `test_dotnet_preview_shared_host.py`, `test_dotnet_update_queue.py`, `test_mesh_dotnet_stroke_protocol_flow.py` |
| Preview startup, modes and appearance settings | `test_dotnet_preview_shared_host_lifecycle.py`, `test_static_replacement_dotnet_presentation.py`, `test_model_preview_settings_dialog.py` |
| Camera and material handoffs | `test_mesh_editor_camera_is_not_reset.py`, `test_mesh_editor_textured_view_import.py`, `test_mesh_dotnet_material_state.py` |
| Editor finish, cancellation and close | `test_mesh_rust_finish_lifecycle.py`, `test_mesh_editor_nonblocking_close.py`, `test_mesh_edit_session_state.py` |
| Texture panels, saved values and OpenImageIO completion | `test_lazy_texture_workflow_panels.py`, `test_asset_authoring_workers.py` |
| Current native helper manifest and release routing | `test_native_build_configuration.py`, `test_release_packaging.py` |
| QA selection and opt-in proof boundaries | `test_qa_runner.py` |

The `dotnet_*` filenames in the preview owners include current Rust bridge
coverage. Check the actual runtime owner before classifying them as retired.
When retiring a suite, also remove its unreferenced helpers and build stubs.
Keep environment-gated integration tests while their supported tool or input
still exists; an unavailable local prerequisite does not make them obsolete.

## Fixtures and private evidence

`tests/fixtures/` contains the bounded, documented inputs that are part of the
regression contract, including trimmed golden byte fixtures. Full game archives,
extracted corpora, screenshots, captures, benchmark output, restore points, and
machine-local paths remain ignored and must never be added as test evidence.

## Running tests and CI

Use the repository virtual environment and a system-temp directory:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_documentation_consistency.py --basetemp="$env:TEMP\cdmw-docs-tests"
```

Choose the exact test file for an ordinary change. On a fresh source checkout,
prepare the native helpers and archive worker using the root README's source
setup first. Full-suite and native tests require those real helpers.

### CI triggers and default checks

GitHub's Windows Build defaults to the `smoke` gate on Python 3.14 for code pushes, pull
requests, tags and manual runs. Documentation and GitHub issue/pull-request
template-only pushes and pull requests skip both Windows Build and CodeQL; mixed
code/documentation changes still run. The CodeQL workflow owns its triggers instead of
GitHub's automatic default setup and retains the existing five-language coverage and
weekly security refresh. CodeQL uploads all security results but disables optional
database-archive publication, whose bundling can stall after analysis has completed. All
five language scans and their security-result uploads remain required.

The default Windows QA path runs focused CodeQL workflow-contract and Archive Browser
Finder wiring tests after smoke, without requesting the full suite. The smoke gate
covers startup/tool construction, archive confirmation/backup/rollback, output path
safety, helper cleanup, metadata and localization without building native helpers. The
real-window localization regression also runs with frequent garbage collection to catch
native widget lifetime faults during startup.

### Exhaustive tests and packaging

Manual `exhaustive_tests` opts into native builds and the full nonvisual suite
on Python 3.11 and 3.14. Packaging requires the selected QA to pass and runs
only for tags or manual dispatch; onefile is the default, with onedir and both
available explicitly. Packaged helper and startup checks remain mandatory.
Before publishing a release, wait for Windows Build and every CodeQL language
check on its commit to finish successfully. Pending, cancelled, timed-out, or
failed checks must be resolved before publication. Jobs skipped by the documented
conditions above are expected; they do not replace any required check.

### Scope, exit codes and shutdown

Feature-specific and native regressions should use their owning tests when
those surfaces change. There is no nightly schedule. CI excludes
`visual`, `real_game` and machine-sensitive `timing` tests.
Each gate's exit code is checked before continuing, so a later successful gate
cannot hide an earlier failure. Async shutdown tests verify worker ownership and
nonblocking calls directly instead of imposing wall-clock limits on shared runners.
The shared pytest teardown drains requested Qt deletions and shuts down
QApplication before Python exits. A subprocess regression checks both the
session cleanup and the final process status, since a passing pytest summary
does not rule out a later crash in the offscreen platform plugin.

### Module isolation and fault reports

Smoke, Mesh unit, and full gates run each complete test module in a fresh
interpreter to contain accumulated Qt state. Full discovers its modules through
pytest collection with the active markers; collection errors also fail the gate.
Every module's process exit must succeed
before the next module starts; no tests are skipped or failures retried.
These gates capture Python streams while leaving native stderr visible. If a
test process fails, the runner also prints a bounded excerpt of the app's
native fault log, where shell construction redirects faulthandler output.

## Mesh Editor gates

Dedicated Rust Mesh Editor changes start with the exact owning shadow, embedding,
control-contract, or output tests. `mesh-contract` covers the Python/Rust helper protocols and runs
`scripts/test_rust_mesh_lab.ps1`; inspect that script for its current Rust scope.
The compiled control-contract check budgets cold Rust compilation separately
from the contract query, so a slow build cannot consume the query's deadline.
`mesh-native` builds and checks the C++ native interaction ABI and bridge
contracts. Historical filenames do not identify the production renderer. `-Area mesh-unit` remains
the explicit broad nonvisual aggregate for CI, release confidence, or a
requested complete Mesh regression. `-Area responsiveness` checks pointer
handler and host-heartbeat contracts without substituting for native or
packaged behavior.

### Release and visible proof

Native-helper release builds are required when helper/native release output or
capability provenance changes. `build.bat onefile release` is reserved for
packaging changes or explicit release work. Packaged
visible GPU interaction, licensed real-PAC, and
ten-minute process/device/memory soak evidence are separate authorized gates;
synthetic ABI or source-helper success must never be reported as those proofs.
No automated gate may move the physical cursor, click through global input, or
use foreground focus as acceptance evidence while the workstation is in use.
