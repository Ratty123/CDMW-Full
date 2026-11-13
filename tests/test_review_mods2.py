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

_CONTENTS = "Review of rr/parity-mods-2 (REPORT-review.md): the owner mark proves the folder, not its files"
_BACKUP = "Review of rr/parity-mods-2 (REPORT-review.md): backup copies of same-named files overwrite each other"


_AI_TOOL = ("Review of rr/parity-mods-2 (REPORT-review.md): user_only sets nothing, so after MCP the "
            "removal and Restore Backup are AI tools")
_TRANSACTION = ("Review of rr/parity-mods-2 (REPORT-review.md): an interrupted old transaction blocks "
                "the removal, and the recovery it asks for was removed")


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
