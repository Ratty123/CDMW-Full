# Tests

The `tests/` folder is regression coverage for implementation under `cdmw/`,
`native/`, and `tools/`, plus repository build, CI, and architecture contracts.
It is not application runtime code.

Most tests exercise behavior directly. Files named `*_source_guards.py` are
intentional wiring guards for large PySide UI surfaces where previous regressions
were caused by missing buttons, callbacks, or fallback paths. They are brittle by
nature, but they protect user-facing workflows until those surfaces have smaller
behavior-level harnesses.

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

GitHub's Windows Build defaults to the ten-module `smoke` gate on Python 3.14
for pushes, pull requests, tags and manual runs. It covers startup/tool
construction, archive confirmation/backup/rollback, output path safety,
helper cleanup, metadata and localization without building native helpers.
Manual `exhaustive_tests` opts into native builds and the full nonvisual suite
on Python 3.11 and 3.14. Packaging requires the selected QA to pass and runs
only for tags or manual dispatch; onefile is the default, with onedir and both
available explicitly. Packaged helper and startup checks remain mandatory.
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

Native-helper release builds are required when helper/native release output or
capability provenance changes. `build.bat onefile release` is reserved for
packaging changes or explicit release work. Packaged
visible GPU interaction, licensed real-PAC, and
ten-minute process/device/memory soak evidence are separate authorized gates;
synthetic ABI or source-helper success must never be reported as those proofs.
No automated gate may move the physical cursor, click through global input, or
use foreground focus as acceptance evidence while the workstation is in use.
