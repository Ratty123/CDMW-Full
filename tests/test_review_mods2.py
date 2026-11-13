"""Review of refs/heads/rr/parity-mods-2: Remove What an Older CDMW Installed... (decision 42).

The real removal service and Restore Backup on owned game folders under tmp_path,
built with the removal tests' own helpers. They were strict xfails on the
reviewed code; the fixes removed the markers.
"""

from __future__ import annotations

import hashlib
import json

import pytest

removal = pytest.importorskip("cdmw.services.old_install_removal")

from cdmw.services.archive_mutation_service import ArchiveMutationService  # noqa: E402
from tests.test_old_install_removal import (  # noqa: E402,F401  (the autouse fixture owns the backups)
    OVERLAY_DDS, _fingerprint, _game, _group, _mount, _owned_backups, _remove,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_a_marked_folder_whose_archive_another_tool_replaced_is_left_alone(tmp_path):
    """CDMW's overlay index records the digest of every file it published. After Steam's
    verify (mount list back, 0036 left on disk) another tool wrote its own archive into
    0036 and mounted it; the owner mark is still there. The removal compares only the
    mark, so it deletes the other tool's 0.pamt and 0.paz and unmounts them."""

    root = _game(tmp_path, overlay=True)
    index_path = root / ".cdmw" / "overlays.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["published"] = {f"0036/{name}": _digest((root / "0036" / name).read_bytes())
                          for name in ("0.pamt", "0.paz", removal.OVERLAY_OWNER_MARKER)}
    index_path.write_text(json.dumps(index), encoding="utf-8")
    other = _group(root / "0036", ["character/texture/another_tool_wing_d.dds"])  # another tool's archive
    _mount(root, [("0036", other), ("0009", 0)])
    replaced = {name: (root / "0036" / name).read_bytes() for name in ("0.pamt", "0.paz")}

    plan = removal.find_old_install(root)
    if plan.can_remove:
        _remove(plan, root)
    for name, data in replaced.items():
        assert (root / "0036" / name).is_file() and (root / "0036" / name).read_bytes() == data, (
            f"0036/{name} was not what CDMW published, yet it was removed")


def test_restore_puts_back_two_files_that_share_a_folder_and_file_name(tmp_path):
    """backup_files names each copy '<parent folder>_<file name>'. An old virtual install
    keeps one packages/ folder per generation, so the removal backs up
    generations/g1/packages/a.cditem and generations/g2/packages/a.cditem to the same
    copy: Restore Backup then writes one file's bytes into both."""

    root = _game(tmp_path, virtual=True)
    generations = root / ".cdmw" / "virtual-loader" / "generations"
    for generation, data in (("g1", b"generation one's item"), ("g2", b"generation two's item")):
        (generations / generation / "packages").mkdir(parents=True, exist_ok=True)
        (generations / generation / "packages" / "a.cditem").write_bytes(data)
    before = _fingerprint(root)
    plan = removal.find_old_install(root)
    assert plan.can_remove
    result = _remove(plan, root)
    ArchiveMutationService().restore_backup(result.backup_dir, confirmed=True, game_root=root)
    assert _fingerprint(root) == before, "Restore Backup did not put back what the removal deleted"


def test_an_install_an_older_cdmw_left_mid_transaction_can_still_be_removed(tmp_path):
    """An Apply interrupted in an older CDMW left .cdmw/virtual-loader/transaction.json.
    installation_lane refuses every change while it exists unless recovery=True, and the
    only caller that passed it (recover_profile) went with the virtual loader. The removal
    takes the lane without it, so the one action meant to clear an old install refuses
    it, and so do Send to DMM and Restore Backup."""

    root = _game(tmp_path, virtual=True)
    (root / ".cdmw" / "virtual-loader" / "transaction.json").write_text(
        json.dumps({"format": "cdmw_virtual_transaction_v1"}), encoding="utf-8")
    plan = removal.find_old_install(root)
    assert plan.can_remove
    _remove(plan, root)
    assert not (root / "bin64" / "CDMWVirtualLoader.asi").exists()


def test_no_ai_tool_lists_the_removal_or_restore_backup():
    """Both commands write into the game, and the plan says no AI tool covers such a writer
    under any setting. user_only_command passes user_only only when Command has the field;
    neither branch adds it, and MCP's table leaves out only USER_ONLY_COMMANDS. So once
    both branches land, command_tools() lists both with the default class (edit)."""

    tools = pytest.importorskip("cdmw.mcp.tools")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from cdmw.mcp.catalogue import typed_tools
    from cdmw.ui.archive_browser import old_install_removal as ui

    QApplication.instance() or QApplication([])
    browser = SimpleNamespace(_restore_archive_patch_backup_from_ui=lambda: None)
    registry = ui.install_old_install_removal(browser)
    assert registry is not None
    try:
        assert ui.REMOVE_COMMAND_ID in registry and ui.RESTORE_COMMAND_ID in registry
        listed = {tool.name: tool.effect
                  for tool in tools.ToolTable(typed_tools(), registry=lambda: registry).command_tools()}
        exposed = {name: listed[name] for name in (ui.REMOVE_COMMAND_ID, ui.RESTORE_COMMAND_ID) if name in listed}
        assert not exposed, f"AI tools that write into the game: {exposed}"
    finally:
        for name in (ui.REMOVE_COMMAND_ID, ui.RESTORE_COMMAND_ID):
            registry._commands.pop(name, None)


def _send_twice_fixture(tmp_path):
    from tests.support.game_fixtures import packages
    from tests.test_dmm_send import _dmm

    root, files = packages(tmp_path)
    _install, mods = _dmm(tmp_path)
    return root, files, mods


def _identities(root):
    from cdmw.services import game_records

    registry = json.loads(game_records.registry_source(root).read_text(encoding="utf-8"))
    return {identity: row.get("values") for identity, row in registry["items"].items()}


def test_send_to_dmm_reads_an_older_registry_in_the_game_and_changes_no_byte(tmp_path):
    """Decision 46's carry-over through the real Mods page route: an older CDMW's registry
    in <game>/.cdmw is read, the same identities come out, and the game folder (that
    file included) keeps every byte."""

    from cdmw.core import protected_roots
    from cdmw.services import game_records
    from cdmw.services.dmm_send import send_item_packages

    root, files, mods = _send_twice_fixture(tmp_path)
    protected_roots.set_configured_game_root(root)
    try:
        send_item_packages(files, root, mods, "Two items")
        kept = game_records.registry_path(root)
        first = _identities(root)
        legacy = root / game_records.LEGACY_REGISTRY_PATH  # as an older CDMW left it
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(kept.read_bytes())
        kept.unlink()
        before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        send_item_packages(files, root, mods, "Two items")
        after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    finally:
        protected_roots.set_configured_game_root(None)
    assert after == before, "Send to DMM changed the game folder"
    assert kept.is_file(), "the carried-over registry was not kept in the CDMW folder"
    assert _identities(root) == first, "the carried-over identities changed"


def test_a_game_folder_moved_to_another_library_keeps_its_item_identities(tmp_path):
    """Before decision 46 the registry travelled with the game folder. Now its key is the
    folder's resolved path, so after Steam moves the game the next send finds no registry.
    It holds: the same packages against the same game come out with the same identities."""

    import os

    from cdmw.core import protected_roots
    from cdmw.services.dmm_send import send_item_packages

    root, files, mods = _send_twice_fixture(tmp_path)
    protected_roots.set_configured_game_root(root)
    try:
        send_item_packages(files, root, mods, "Two items")
        first = _identities(root)
        moved = tmp_path / "Other Library" / "game"
        moved.parent.mkdir()
        os.rename(root, moved)
        protected_roots.set_configured_game_root(moved)
        send_item_packages(files, moved, mods, "Two items")
        after = _identities(moved)
    finally:
        protected_roots.set_configured_game_root(None)
    assert after == first, "the moved game's items were given new identities"


def test_the_removals_backup_is_kept_in_the_cdmw_folder():
    """The removal deletes the game's whole .cdmw folder (retained item packages and an
    older registry among it) after backing it up with backup_files. Those backups go to
    ARCHIVE_PATCH_BACKUP_ROOT, <system temp>/<app>/archive_patch_backups: outside the CDMW
    folder, where Windows' temp cleanup can empty them and Restore Backup then has nothing."""

    import importlib.util

    from cdmw.app.app_folder import cdmw_folder
    from cdmw.core import archive_patching

    # The removal tests' autouse fixture points the live module at tmp_path; read the
    # module's own default from a fresh copy of it.
    spec = importlib.util.spec_from_file_location("archive_patching_default", archive_patching.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    root = fresh.ARCHIVE_PATCH_BACKUP_ROOT.resolve()
    assert root.is_relative_to(cdmw_folder().resolve()), f"backups go to {root}"


def test_the_mods_pages_send_refuses_a_dmm_mods_folder_inside_the_game(tmp_path, monkeypatch):
    """The Mods page sends through send_item_packages_in_subprocess. The protected root is
    a module global of the GUI process; the --dmm-send-worker child starts with none, and
    the parent never checks the destination. With DMM's modsPath inside the game, the
    child stages and publishes the mod there."""

    from cdmw.core import protected_roots
    from cdmw.services import dmm_send_process
    from tests.support.game_fixtures import packages
    from tests.test_dmm_send import _dmm

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    root, files = packages(tmp_path)
    _install, mods = _dmm(tmp_path, mods_path=root / "mods")
    before = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    protected_roots.set_configured_game_root(root)  # as Browse's game folder field does
    try:
        try:
            dmm_send_process.send_item_packages_in_subprocess(files, root, mods, "Two items")
        except Exception:
            pass  # a refusal is the right outcome; what counts is the game folder
    finally:
        protected_roots.set_configured_game_root(None)
    added = sorted({path.relative_to(root).as_posix() for path in root.rglob("*")} - before - {"mods"})
    assert not added, f"Send to DMM wrote into the game folder: {added[:5]}"


@pytest.mark.parametrize("pick", ["the game folder", "a folder that holds the game"])
def test_clearing_an_output_folder_never_empties_the_game(tmp_path, pick):
    """Browse's Clear Root (extraction.py) and Clear Workflow Roots call
    clear_directory_contents on the folder the user picked. It refuses only a drive root,
    and never asks the protected root, so picking the game folder, or the library that
    holds it, deletes the game."""

    from cdmw.core import protected_roots
    from cdmw.core.archive_extraction import clear_directory_contents

    game = tmp_path / "library" / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"papgt")
    picked = game if pick == "the game folder" else game.parent
    protected_roots.set_configured_game_root(game)
    try:
        try:
            clear_directory_contents(picked)
        except Exception:
            pass  # a refusal is the right outcome
    finally:
        protected_roots.set_configured_game_root(None)
    assert (game / "meta" / "0.papgt").is_file(), f"clearing {pick} deleted the game"


@pytest.mark.parametrize("older_registry", [False, True], ids=["no-older-registry", "older-registry"])
def test_the_mods_pages_send_in_its_child_process_changes_no_byte_in_the_game(tmp_path, monkeypatch, older_registry):
    """The live Mods page route (a --dmm-send-worker child) with DMM's mods folder outside
    the game, with and without an older CDMW's registry in <game>/.cdmw."""

    from cdmw.core import protected_roots
    from cdmw.services import dmm_send_process, game_records
    from tests.support.game_fixtures import packages
    from tests.test_dmm_send import _dmm

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    root, files = packages(tmp_path)
    _install, mods = _dmm(tmp_path)
    if older_registry:
        from cdmw.services.dmm_send import send_item_packages

        send_item_packages(files, root, mods, "Two items")  # makes a real registry
        kept = game_records.registry_path(root)
        legacy = root / game_records.LEGACY_REGISTRY_PATH
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(kept.read_bytes())
        kept.unlink()
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    protected_roots.set_configured_game_root(root)
    try:
        result = dmm_send_process.send_item_packages_in_subprocess(files, root, mods, "Two items")
    finally:
        protected_roots.set_configured_game_root(None)
    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert result.folder.is_dir()
    assert after == before, "Send to DMM changed the game folder"


def test_an_overlay_recorded_only_by_the_older_install_receipt_is_removed(tmp_path):
    """Before the overlay index (0f521e245, 2026-09-09), and in its single-overlay route,
    CDMW recorded an install only in .cdmw/last-overlay-install.json, which names the
    folder and the mount lists but no file digests. fc120763d proves each 0.pamt/0.paz by
    the index's published digests only, so such an install is listed as not CDMW's and
    stays mounted: the action can no longer take out what it was made for."""

    from tests.test_old_install_removal import _group as group, _mount as mount

    root = _game(tmp_path)
    checksum = group(root / "0036", [OVERLAY_DDS])
    (root / "0036" / removal.OVERLAY_OWNER_MARKER).write_bytes(removal.OVERLAY_OWNER_BYTES)
    shipped = (root / "meta" / "0.papgt").read_bytes()
    mount(root, [("0036", checksum), ("0009", 0)])
    (root / ".cdmw").mkdir(exist_ok=True)
    (root / ".cdmw" / "last-overlay-install.json").write_text(json.dumps({
        "format": "cdmw_overlay_install_receipt_v1", "package_root": str(root), "overlay_directory": "0036",
        "mesh_paths": [OVERLAY_DDS], "mount_list_before": ["0009"], "mount_list_after": ["0036", "0009"],
        "carried_forward": [], "backup_dir": "", "backup_targets": [], "created_files": []}), encoding="utf-8")
    del shipped
    plan = removal.find_old_install(root)
    assert plan.can_remove and "0036/0.pamt" in plan.delete_files, plan.review_lines()
    _remove(plan, root)
    assert not (root / "0036" / "0.pamt").exists() and not (root / "0036" / "0.paz").exists()
