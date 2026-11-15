"""Guard: CDMW writes into a game folder through exactly two routes (decisions 35, 39, 42).

CDMW never writes into the game's archives; it only creates mods. Two confirmed
actions in Browse Archives may change files inside a game installation, and
nothing else in ``cdmw/`` may:

- **Restore Backup...** puts back what an older CDMW patched into the game,
  through ``ArchiveMutationService.restore_backup``;
- **Remove What an Older CDMW Installed...** removes what it can prove an older
  CDMW's overlay or virtual-loader install put there, through
  ``cdmw.services.old_install_removal``. It backs up first, Restore-style, and
  restores that backup itself if it fails halfway.

Neither has an MCP tool or an automation route: both are user-only commands.

Since decision 46 this also holds by construction: the configured game folder is a
protected root (``cdmw.core.protected_roots``), every shared writer in
``cdmw.core.atomic_file`` refuses a path inside it, and only those two routes hold
the permit. CDMW keeps nothing of its own in the game folder: the item identity
registry lives in the CDMW folder (``cdmw.services.game_records``). The tests at the
end send to DMM from both routes against an owned game folder and fail if one byte
in it changes.

These tests fail when that fence moves:

- the low-level archive writers are not in cdmw/ at all: they live in
  tests/support/ (tests use them on owned copies), and nothing under cdmw/
  imports that package;
- ``restore_archive_patch_backup`` is reached only through
  ``ArchiveMutationService.restore_backup``;
- ``restore_backup`` and ``backup_files`` are called only by the two routes;
- the read halves of the removed installs, which live features still use to
  read an older CDMW's records, write nothing;
- the removed installs and the removed direct patch route stay removed.

The scan covers every module under ``cdmw/`` (the interface, workers, the
automation bridge and, once merged, the assistant's MCP tools) and
``cdmw_app.py``. A new route that writes into the game has to be added here on
purpose, with its reason.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import hashlib
import json

import pytest

from cdmw import constants
from cdmw.core import protected_roots
from cdmw.core.atomic_file import (
    atomic_binary_writer, atomic_copy_file, atomic_publish_directory, atomic_publish_files,
    atomic_publish_paths, atomic_text_writer, atomic_write_bytes, atomic_write_text,
)
from cdmw.core.protected_roots import ProtectedGameFolderWrite, game_folder_write_permit
from cdmw.services import game_records

ROOT = Path(__file__).resolve().parents[1]
#: Generated data, not code that runs.
SKIPPED = {"cdmw/ui/shell/error_reference_data.py"}
#: Lazy re-export tables of the old ``cdmw.core.archive_modding`` names; they hold strings only.
COMPAT_TABLES = ("cdmw/core/archive_modding_compat_exports_",)

#: The two routes that may write into a game folder, by the text the user sees.
GAME_WRITE_ROUTES = {
    "Restore Backup...": "cdmw/ui/archive_browser/patch_actions.py",
    "Remove What an Older CDMW Installed...": "cdmw/ui/archive_browser/old_install_removal.py",
}

#: The in-place PAMT/PAZ writers, moved to tests/support/archive_patch_writer.py
#: and tests/support/archive_entry_addition.py.
CORE_WRITERS = frozenset({
    "patch_archive_entries", "apply_archive_mutations", "add_archive_entries",
    "_run_archive_mutation", "_apply_in_place_patches", "_write_paz_payload", "_append_paz_payload",
    "_write_bytes_preserve_timestamps", "_write_paz_record", "_verify_crc_chain", "_parse_mutable_pamt",
})
#: Restore's own copy-back; only its module and the Restore path use it.
RESTORE_COPY = "_restore_backup"

RESTORE_WRITER = "restore_archive_patch_backup"
RESTORE_WRITER_CALLERS = {
    "cdmw/core/archive_patching.py": "defines it",
    "cdmw/services/archive_mutation_service.py": "restore_backup, after explicit confirmation",
}

SERVICE_WRITES = frozenset({"restore_backup", "backup_files"})
SERVICE_WRITE_CALLERS = {
    "cdmw/services/archive_mutation_service.py": "defines them",
    "cdmw/ui/archive_browser/patch_actions.py": "Restore Backup...: confirmed",
    "cdmw/services/old_install_removal.py": "Remove What an Older CDMW Installed...: backs up first, restores on failure",
    "cdmw/ui/archive_browser/old_install_removal.py": "Remove What an Older CDMW Installed...: confirmed, through the service",
}
#: The removal service's entry points; only its own module and its Browse action use them.
REMOVAL_ENTRY = frozenset({"remove_old_install", "find_old_install"})

#: Read halves of the removed installs. Live features (Send to DMM, combining item
#: packages, mod updates) still read an older CDMW's overlay index and item
#: registry through them; they must not write anything.
READ_HALVES = (
    "cdmw/services/archive_overlay_install.py", "cdmw/services/archive_overlay_manager.py",
    "cdmw/services/independent_item_install.py", "cdmw/services/virtual_loader_state.py",
    "cdmw/services/virtual_loader_composition.py",
    "cdmw/domain/virtual_loader.py",
)
#: Calls that write, move or delete files.
WRITE_CALLS = frozenset({
    "write_bytes", "write_text", "atomic_write_bytes", "atomic_write_text", "atomic_write_json",
    "unlink", "rename", "rmdir", "rmtree", "mkdir", "makedirs", "copy", "copy2", "copyfile",
    "copytree", "move", "remove", "truncate", "atomic_binary_writer", "atomic_text_writer", "atomic_write",
    "atomic_copy_file", "atomic_publish_directory", "atomic_publish_files", "atomic_publish_paths",
    "atomic_preview_publication",
})

#: Modules of the removed installs; none may come back.
REMOVED_MODULES = (
    "cdmw/services/archive_overlay_migration.py", "cdmw/services/archive_overlay_rebuild.py",
    "cdmw/services/archive_reference_cleanup.py", "cdmw/services/new_item_mounted_base.py",
    "cdmw/services/new_item_overlay_preview.py", "cdmw/services/overlay_inventory_details.py",
    "cdmw/services/virtual_loader_cache.py", "cdmw/services/virtual_loader_process.py",
    "cdmw/services/virtual_loader_receipts.py", "cdmw/services/virtual_loader_runtime.py",
    "cdmw/services/virtual_loader_saves.py", "cdmw/services/virtual_loader_smoke.py",
    "cdmw/services/virtual_loader_sources.py", "cdmw/services/virtual_loader_standalone.py",
    "cdmw/domain/virtual_save_evidence.py", "cdmw/domain/virtual_save_lineage.py",
    "cdmw/domain/virtual_session_receipt.py", "cdmw/ui/new_item/independent_items_page.py",
    "cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw/ui/new_item/virtual_loader_page.py",
    "cdmw/ui/tools/mod_management_list.py", "cdmw/ui/tools/mod_management_overview.py",
    "cdmw/core/archive_entry_addition.py", "cdmw/services/overlay_target_recovery.py",
)
#: Entry points of the removed installs; none may come back.
REMOVED_INSTALLS = frozenset({
    "install_overlay", "prepare_install", "apply_overlay_change", "apply_overlay_retirement",
    "prepare_overlay_removal", "prepare_overlay_enabled", "prepare_overlay_retirement", "prepare_overlay_rebuild",
    "migrate_into_overlay", "remove_overlay", "plan_migration", "restore_last_overlay_install",
    "publish_profile", "prepare_profile", "apply_identity_deletion", "prepare_identity_deletion",
    "prepare_remove", "prepare_rebuild", "prepare_profile_import",
    "prepare_missing_reference_cleanup", "apply_missing_reference_cleanup",
    "ARCHIVE_OVERLAYS_ENABLED", "VIRTUAL_LOADING_ENABLED",
})

#: Entry points of the removed direct patch route; none may come back.
REMOVED = frozenset({
    "prepare_patch", "validate_patch", "apply_patch", "_apply_confirmed_patch", "ArchiveMutationPlan",
    "require_explicit_archive_mutation", "ArchiveMutationSafety",
    "_choose_archive_write_target", "_confirm_mesh_direct_archive_patch", "_build_mesh_direct_patch_requests",
    "_mesh_direct_patch_target_paths", "_mesh_direct_patch_spec_payload", "_mesh_direct_patch_spec_is_generated",
    "_apply_archive_patch_result",
})


@lru_cache(maxsize=1)
def _modules() -> dict[str, ast.Module]:
    paths = [*sorted((ROOT / "cdmw").rglob("*.py")), ROOT / "cdmw_app.py"]
    modules = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in SKIPPED or relative.startswith(COMPAT_TABLES):
            continue
        modules[relative] = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    return modules


def _referenced(tree: ast.Module, names: frozenset[str] | set[str]) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in names:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in names:
            found.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            found.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names if alias.name in names)
    return found


def _modules_referencing(names) -> set[str]:
    return {path for path, tree in _modules().items() if _referenced(tree, frozenset(names))}


def test_exactly_two_routes_write_into_a_game_folder():
    assert len(GAME_WRITE_ROUTES) == 2
    assert set(GAME_WRITE_ROUTES.values()) == {path for path in SERVICE_WRITE_CALLERS if path.startswith("cdmw/ui/")}
    source = {name: (ROOT / path).read_text(encoding="utf-8") for name, path in GAME_WRITE_ROUTES.items()}
    assert "Restore Backup" in source["Restore Backup..."]
    assert '"Remove What an Older CDMW Installed..."' in source["Remove What an Older CDMW Installed..."]


def test_the_removed_installs_are_gone():
    assert not hasattr(constants, "ARCHIVE_OVERLAYS_ENABLED")
    assert not hasattr(constants, "VIRTUAL_LOADING_ENABLED")
    assert [path for path in REMOVED_MODULES if (ROOT / path).exists()] == []
    assert _modules_referencing(REMOVED_INSTALLS) == set()


def test_nothing_imports_a_removed_module():
    removed = {path[:-3].replace("/", ".") for path in REMOVED_MODULES}
    found = set()
    for path, tree in _modules().items():
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            found.update((path, name) for name in names if name in removed)
    assert found == set()


def test_the_low_level_archive_writers_are_not_in_the_app():
    assert _modules_referencing(CORE_WRITERS) == set()
    assert _modules_referencing({RESTORE_COPY}) == {"cdmw/core/archive_patching.py"}
    importing_tests = set()
    for path, tree in _modules().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tests":
                importing_tests.add(path)
            elif isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "tests" for alias in node.names):
                importing_tests.add(path)
    assert importing_tests == set()


def test_the_backup_restore_writer_is_reached_only_through_its_listed_callers():
    assert _modules_referencing({RESTORE_WRITER}) == set(RESTORE_WRITER_CALLERS)


def test_restore_and_backup_are_called_only_by_the_two_routes():
    assert _modules_referencing(SERVICE_WRITES) == set(SERVICE_WRITE_CALLERS)


def test_the_removal_is_reached_only_from_its_browse_action():
    assert _modules_referencing(REMOVAL_ENTRY) == {
        "cdmw/services/old_install_removal.py", "cdmw/ui/archive_browser/old_install_removal.py"}


def _write_calls(tree: ast.Module) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
        if name == "replace" and isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name) \
                and function.value.id == "os":
            found.append(f"os.replace (line {node.lineno})")
        elif name in WRITE_CALLS:
            found.append(f"{name} (line {node.lineno})")
        elif name == "open":
            modes = [*node.args[1:2], *(k.value for k in node.keywords if k.arg == "mode")]
            if any(isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+")
                   for mode in modes):
                found.append(f"open for writing (line {node.lineno})")
    return found


def test_the_read_halves_of_the_removed_installs_write_nothing():
    writes = {path: _write_calls(_modules()[path]) for path in READ_HALVES}
    assert {path: calls for path, calls in writes.items() if calls} == {}


def test_the_removed_direct_patch_route_stays_removed():
    assert _modules_referencing(REMOVED) == set()


def test_both_routes_need_confirmation(tmp_path):
    import pytest

    from cdmw.services.archive_mutation_service import ArchiveMutationService
    from types import SimpleNamespace

    from cdmw.services.old_install_removal import remove_old_install

    with pytest.raises(PermissionError, match="explicit confirmation"):
        ArchiveMutationService().restore_backup(tmp_path / "backup")
    source = (ROOT / "cdmw/ui/archive_browser/patch_actions.py").read_text(encoding="utf-8")
    # The page asks first and passes confirmed=True only after a Yes.
    assert "QMessageBox.question(" in source and "confirmation != QMessageBox.Yes" in source
    # The removal refuses an unconfirmed call before it looks at the plan or the folder.
    with pytest.raises(PermissionError, match="confirmation"):
        remove_old_install(SimpleNamespace(root=tmp_path), confirmed=False, configured_root=tmp_path,
                           backup=lambda *a, **k: pytest.fail("backed up"),
                           restore_backup=lambda *a, **k: pytest.fail("restored"))


# Decision 46: nothing CDMW keeps lives in the game folder, and its writers refuse it.


@pytest.fixture
def protected(tmp_path):
    game = tmp_path / "game"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"papgt")
    assert protected_roots.set_configured_game_root(game) is not None
    yield game


def _bytes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_every_shared_writer_refuses_the_game_folder_without_the_permit(protected, tmp_path):
    staged = tmp_path / "staged.bin"
    staged.write_bytes(b"x")
    folder = tmp_path / "staged-folder"
    folder.mkdir()
    target = protected / ".cdmw" / "independent-items.json"
    attempts = (
        lambda: atomic_write_bytes(target, b"x"),
        lambda: atomic_write_text(target, "x"),
        lambda: atomic_copy_file(staged, target),
        lambda: atomic_publish_files({staged: target}),
        lambda: atomic_publish_directory(folder, protected / "0036"),
        lambda: atomic_publish_paths(((staged, target),)),
    )
    for attempt in attempts:
        with pytest.raises(ProtectedGameFolderWrite, match="does not write into the game folder"):
            attempt()
    for writer in (atomic_binary_writer, atomic_text_writer):
        with pytest.raises(ProtectedGameFolderWrite):
            with writer(target):
                pass
    assert sorted(p.name for p in protected.rglob("*")) == ["0.papgt", "meta"] and staged.read_bytes() == b"x"


def test_the_permit_is_only_for_the_two_routes_and_only_while_held(protected):
    target = protected / "meta" / "0.papgt"
    with game_folder_write_permit("Restore Backup"):
        atomic_write_bytes(target, b"restored")
    assert target.read_bytes() == b"restored"
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_write_bytes(target, b"after the permit")
    with pytest.raises(ProtectedGameFolderWrite, match="may not write"):
        with game_folder_write_permit("Send to DMM"):
            pass


def test_a_path_that_resolves_into_the_game_folder_is_refused(protected, tmp_path):
    with pytest.raises(ProtectedGameFolderWrite):
        atomic_write_bytes(tmp_path / "elsewhere" / ".." / "game" / "x.bin", b"x")
    atomic_write_bytes(tmp_path / "game-copy" / "x.bin", b"x")  # a sibling with a longer name is fine


def test_the_registry_lives_in_the_cdmw_folder_keyed_by_game(tmp_path):
    first, second = tmp_path / "one" / "game", tmp_path / "two" / "game"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    a = game_records.write_registry(first, b'{"a": 1}\n')
    b = game_records.write_registry(second, b'{"b": 2}\n')
    assert a != b and a.parent.parent == b.parent.parent == game_records.records_root()
    assert not (first / ".cdmw").exists() and not (second / ".cdmw").exists()
    about = json.loads((a.parent / "game.json").read_text(encoding="utf-8"))
    assert about["game_folder"] == str(first.resolve())


def test_an_older_registry_in_the_game_is_read_and_never_changed(tmp_path):
    game = tmp_path / "game"
    (game / ".cdmw").mkdir(parents=True)
    legacy = game / ".cdmw" / "independent-items.json"
    legacy.write_bytes(b'{"older": true}\n')
    before = _bytes(game)
    assert game_records.registry_source(game) == legacy
    game_records.write_registry(game, legacy.read_bytes())
    assert game_records.registry_source(game) == game_records.registry_path(game)
    assert _bytes(game) == before


def test_send_to_dmm_from_the_mods_page_changes_no_byte_in_the_game(tmp_path):
    from cdmw.services.dmm_send import send_item_packages
    from tests.support.game_fixtures import packages
    from tests.test_dmm_send import _dmm

    root, files = packages(tmp_path)
    _install, mods = _dmm(tmp_path)
    before = _bytes(root)
    protected_roots.set_configured_game_root(root)
    try:
        result = send_item_packages(files, root, mods, "Two items")
        again = send_item_packages(files, root, mods, "Two items")
    finally:
        protected_roots.set_configured_game_root(None)
    assert _bytes(root) == before
    assert result.folder.is_dir() and again.replaced
    registry = json.loads(game_records.registry_path(root).read_text(encoding="utf-8"))
    assert len(registry["items"]) == 2


def test_send_to_dmm_from_create_new_item_changes_no_byte_in_the_game(tmp_path):
    from cdmw.services.dmm_send import send_plan
    from tests.test_dmm_send import _dmm
    from tests.test_new_item_compact_dlc import setup, spec

    service, snapshot = setup(tmp_path)
    root = tmp_path / "game"
    plan = service.plan(spec("CompactOwned"), snapshot, capture_independent=True)
    _install, mods = _dmm(tmp_path)
    before = _bytes(root)
    protected_roots.set_configured_game_root(root)
    try:
        send_plan(plan, mods, "Frost blade", service=service)
    finally:
        protected_roots.set_configured_game_root(None)
    assert _bytes(root) == before


def test_a_dmm_mods_folder_inside_the_game_is_refused(protected, tmp_path):
    from cdmw.services.dmm_send import destination

    with pytest.raises(ProtectedGameFolderWrite):
        destination(protected / "mods", "Frost")
