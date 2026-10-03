# Tests

CDMW uses a focused regression suite for a modding tool. Test breadth is a choice,
not a requirement for every edit. Protect user files, authored output and complete
workflows first; accept less coverage of small UI and implementation details.

## What belongs here

Keep tests that catch a credible failure in:

- archive preflight, backup, rollback, output paths and cancellation;
- preservation of imported materials, binary fields, encoding and unedited data;
- saved settings, drafts, undo/redo, export history and atomic publication;
- opening a tool, completing its main workflow and closing its workers safely;
- current Python/native/helper protocols and exported package compatibility.

Use representative valid, boundary and refusal cases. Existing integration or
workflow tests should own related assertions. A test should explain the user
failure it catches, not just restate the implementation.

Do not routinely add tests for labels, tooltips, layout constants, getters,
pass-through methods, file sizes, private function ownership, exact source text,
or every experimental preview-math permutation. Small reversible UI and copy
changes normally need inspection. Developer capture/audit tools can be exercised
when they are used; they do not each need another permanent regression suite.

The October cleanup deliberately retired granular UI, source-shape, experimental
simulation and developer-harness coverage. These checks were not all duplicates
or dead code. The tradeoff is less precise detection of minor and experimental
regressions, with fewer tests to maintain. Some reduced modules retain shared
fixtures used by other tests or native reference-vector generators.

## Ordinary changes

Run the exact existing test that owns the affected behavior:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_archive_mutation_service.py --basetemp="$env:TEMP\cdmw-check"
```

Use the repository virtual environment and a short system-temp path. Do not run
an area gate, full suite, native build or package merely because nearby files
changed. Do not rerun a passing check on an unchanged implementation.

| Behavior | Representative owners |
| --- | --- |
| Archive writes and recovery | `test_archive_patch_preflight.py`, `test_archive_mutation_service.py`, `test_archive_operation_recovery.py`, `test_archive_output_path_safety.py` |
| Binary/container output | `test_pac_rebuild_byte_integrity.py`, `test_pac_interchange_roundtrip.py`, `test_prefab_binary_edit.py`, `test_paloc_container.py` |
| New Item creation and source fidelity | `test_new_item_service.py`, `test_new_item_golden.py`, `test_new_item_texture_fidelity.py`, `test_new_item_overlay_recovery.py` |
| Builder and Mesh Editor workflows | `test_mesh_builder_runtime_wiring.py`, `test_mesh_editor_replacement_sequences.py`, `test_mesh_mod_finish_export.py` |
| Mesh history and unsafe output | `test_mesh_history_atomic_restore.py`, `test_mesh_output_policy.py`, `test_transactional_mesh_outputs.py`, `test_mesh_service_editing.py` |
| Placement edits and package isolation | `test_placement_studio_phase3.py`, `test_placement_studio_phase4.py`, `test_placement_studio_move_apply.py`, `test_placement_studio_package_isolation.py` |
| Preview handoffs and shutdown | `test_dotnet_preview_shared_host.py`, `test_mesh_rust_finish_lifecycle.py`, `test_mesh_editor_nonblocking_close.py` |
| Settings and workspaces | `test_profile_controller.py`, `test_settings_tab_flush_persistence.py`, `test_workspace_ownership.py` |
| Test runner and CI routing | `test_qa_runner.py`, `test_release_packaging.py` |

Historical `dotnet_*` filenames can cover the current Rust bridge. Check the
actual caller before removing coverage because of a filename. A missing local
helper or a failed assertion alone is not a reason to delete a test.

## CI and optional broader checks

Routine Windows CI uses Python 3.14 and the small `smoke` selection in
`scripts/codex_check.ps1`: startup, archive refusal/mutation/path safety, process
cleanup and build metadata. It also checks CI routing and the Finder entry point.
Localization, Mesh Editor state matrices and format-specific regressions remain
available for focused work, outside the default smoke selection.

CodeQL runs weekly or by manual dispatch, retaining all five language analyses.
It does not run on each push or pull request. Workflow changes take effect on
GitHub only after they are pushed; repository protection settings are separate.

Manual `exhaustive_tests` opts into native preparation and the retained nonvisual
suite on Python 3.11 and 3.14. `-Area full` discovers all remaining `test_*.py`
modules and runs them in separate processes so Qt lifetimes do not leak between
modules. Discovery does not prove that each test is useful or regularly run.

Area selections remain available for an explicitly requested broader check.
`mesh-contract` includes the Rust contract/build script; `mesh-native` builds the
native interaction ABI; `mesh-unit` is a broad nonvisual aggregate. Inspect the
owning script before requesting those heavier checks.

Packaging runs for tags or manual dispatch after selected QA, with packaged
helper/startup validation. Visible UI, GPU soak, licensed assets and real-game
checks are separate, explicit activities. Headless or synthetic success does not
prove visible appearance or game compatibility. No automated check may move the
physical cursor or rely on foreground focus while the workstation is in use.

## Fixtures

Keep bounded synthetic and documented golden inputs under `tests/fixtures/`.
Do not commit game archives, extracted corpora, screenshots, build output, crash
reports, restore points or machine-local evidence. When deleting a suite, check
its helper imports and remove scaffolding only when it has no remaining user.
