"""Guard: no route in the interface can write inside the game folder (decision 35).

CDMW only creates mods. The direct "Patch Game Files" route is gone. What can
still write into a game installation is fenced in, and these tests fail when
that fence moves:

- the low-level archive writers are not in cdmw/ at all: they live in
  tests/support/ (tests use them on owned copies), and nothing under cdmw/
  imports that package;
- ``restore_archive_patch_backup`` is reached only through
  ``ArchiveMutationService.restore_backup`` and the overlay installs' own
  rollback;
- ``restore_backup`` and ``backup_files`` are called from exactly the modules
  listed below: Browse Archives' **Restore Backup...**, which puts back what an
  older CDMW patched into the game, and the archive-group overlay installs,
  which stay implemented but switched off;
- the interface imports exactly the listed names from the overlay installers,
  and both switches that hide those installs are off;
- the removed patch entry points stay removed.

The scan covers every module under ``cdmw/`` (the interface, workers, the
automation bridge and, once merged, the assistant's MCP tools) and
``cdmw_app.py``. A new route that writes into the game has to be added here on
purpose, with its reason.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

from cdmw import constants

ROOT = Path(__file__).resolve().parents[1]
#: Generated data, not code that runs.
SKIPPED = {"cdmw/ui/shell/error_reference_data.py"}
#: Lazy re-export tables of the old ``cdmw.core.archive_modding`` names; they hold strings only.
COMPAT_TABLES = ("cdmw/core/archive_modding_compat_exports_",)

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
    "cdmw/services/overlay_target_recovery.py": "rollback of an overlay install (switched off)",
}

SERVICE_WRITES = frozenset({"restore_backup", "backup_files"})
SERVICE_WRITE_CALLERS = {
    "cdmw/services/archive_mutation_service.py": "defines them",
    "cdmw/ui/archive_browser/patch_actions.py": "Restore Backup...: puts back what an older CDMW patched, confirmed",
    "cdmw/services/archive_overlay_install.py": "overlay install rollback (switched off)",
    "cdmw/services/archive_overlay_manager.py": "overlay change rollback (switched off)",
    "cdmw/services/archive_overlay_migration.py": "overlay migration rollback (switched off)",
    "cdmw/services/archive_reference_cleanup.py": "Clean missing mod references (switched off)",
    "cdmw/services/independent_item_install.py": "item package install into the game (switched off)",
    "cdmw/services/new_item_service.py": "Create New Item's overlay install (switched off)",
    "cdmw/services/overlay_target_recovery.py": "overlay rollback (switched off)",
    "cdmw/ui/new_item/independent_items_page.py": "overlay install page (switched off)",
    "cdmw/ui/new_item/overlay_manager_dialog.py": "overlay manager (switched off)",
    "cdmw/workers/mesh_editor_workers.py": "Mesh Editor Restore Last Overlay Install worker (switched off)",
    "cdmw/workers/new_item_workers.py": "Create New Item overlay install worker (switched off)",
}

INSTALLER_MODULES = frozenset({
    "cdmw.services.archive_overlay_install", "cdmw.services.archive_overlay_manager",
    "cdmw.services.archive_overlay_migration", "cdmw.services.archive_overlay_rebuild",
    "cdmw.services.archive_reference_cleanup", "cdmw.services.independent_item_install",
    "cdmw.services.overlay_target_recovery",
})
#: (module, installer, imported name) for every import of an installer outside cdmw/services.
INSTALLER_IMPORTS = frozenset({
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.archive_overlay_manager", "apply_overlay_change"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.archive_overlay_rebuild", "prepare_overlay_rebuild"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "apply_identity_deletion"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "export_profile"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "inventory"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "prepare_identity_deletion"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "prepare_install"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "prepare_profile_import"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "prepare_rebuild"),
    ("cdmw/ui/new_item/independent_items_page.py", "cdmw.services.independent_item_install", "prepare_remove"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "apply_overlay_change"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "apply_overlay_retirement"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "list_installed_overlays"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "prepare_overlay_enabled"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "prepare_overlay_removal"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_manager", "prepare_overlay_retirement"),
    ("cdmw/ui/new_item/overlay_manager_dialog.py", "cdmw.services.archive_overlay_rebuild", "prepare_overlay_rebuild"),
    ("cdmw/ui/new_item/panels_output.py", "cdmw.services.archive_overlay_install", "OverlayInstallResult"),
    ("cdmw/ui/new_item/panels_output.py", "cdmw.services.independent_item_install", "IdentityDeletionResult"),
    ("cdmw/ui/tools/mod_management.py", "cdmw.services.archive_overlay_install", "OverlayInstallResult"),
    ("cdmw/ui/tools/mod_management.py", "cdmw.services.archive_overlay_migration", "plan_migration"),
    ("cdmw/ui/tools/mod_management.py", "cdmw.services.independent_item_install", "IdentityDeletionResult"),
    ("cdmw/ui/tools/mod_management_list.py", "cdmw.services.archive_overlay_manager", "prepare_overlay_enabled"),
    ("cdmw/ui/tools/mod_management_list.py", "cdmw.services.archive_overlay_manager", "prepare_overlay_removal"),
    ("cdmw/ui/tools/mod_management_list.py", "cdmw.services.independent_item_install", "prepare_remove"),
    ("cdmw/ui/tools/mod_management_overview.py", "cdmw.services.archive_reference_cleanup", "prepare_missing_reference_cleanup"),
    ("cdmw/ui/tools/mod_management_overview.py", "cdmw.services.archive_reference_cleanup", "apply_missing_reference_cleanup"),
    # The overlay install workers (switched off).
    ("cdmw/workers/mesh_editor_workers.py", "cdmw.services.archive_overlay_install", "restore_last_overlay_install"),
    ("cdmw/workers/new_item_workers.py", "cdmw.services.archive_overlay_migration", "migrate_into_overlay"),
    ("cdmw/workers/new_item_workers.py", "cdmw.services.archive_overlay_migration", "plan_migration"),
    ("cdmw/workers/new_item_workers.py", "cdmw.services.archive_overlay_migration", "remove_overlay"),
    # A read-only check of a package's identity registry.
    ("cdmw/core/mod_compatibility.py", "cdmw.services.independent_item_install", "_validate_registry"),
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


def test_the_switches_that_hide_the_game_installs_are_off():
    assert constants.ARCHIVE_OVERLAYS_ENABLED is False
    assert constants.VIRTUAL_LOADING_ENABLED is False


def test_the_low_level_archive_writers_are_not_in_the_app():
    assert _modules_referencing(CORE_WRITERS) == set()
    assert _modules_referencing({RESTORE_COPY}) == {"cdmw/core/archive_patching.py"}
    assert not (ROOT / "cdmw/core/archive_entry_addition.py").exists()
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


def test_restore_and_backup_are_called_from_exactly_the_listed_modules():
    assert _modules_referencing(SERVICE_WRITES) == set(SERVICE_WRITE_CALLERS)


def test_the_interface_imports_exactly_the_listed_names_from_the_installers():
    found = set()
    for path, tree in _modules().items():
        if path.startswith("cdmw/services/"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in INSTALLER_MODULES:
                found.update((path, node.module, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module == "cdmw.services":
                found.update((path, f"cdmw.services.{alias.name}", "*") for alias in node.names
                             if f"cdmw.services.{alias.name}" in INSTALLER_MODULES)
            elif isinstance(node, ast.Import):
                found.update((path, alias.name, "*") for alias in node.names if alias.name in INSTALLER_MODULES)
    assert found == INSTALLER_IMPORTS


def test_the_removed_direct_patch_route_stays_removed():
    assert _modules_referencing(REMOVED) == set()


def test_the_only_live_game_write_is_restore_and_it_needs_confirmation(tmp_path):
    import pytest

    from cdmw.services.archive_mutation_service import ArchiveMutationService

    with pytest.raises(PermissionError, match="explicit confirmation"):
        ArchiveMutationService().restore_backup(tmp_path / "backup")
    source = (ROOT / "cdmw/ui/archive_browser/patch_actions.py").read_text(encoding="utf-8")
    # The page asks first and passes confirmed=True only after a Yes.
    assert "QMessageBox.question(" in source and "confirmation != QMessageBox.Yes" in source
