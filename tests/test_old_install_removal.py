"""Remove what an older CDMW installed (decision 42), on game folders made in the test.

Every game here is built from scratch in the test's own folder: a shipped
archive group, a legacy mount list and a texture registry, plus what an old
CDMW left (an overlay folder with its owner mark, the virtual loader's ASI and
owner file, CDMW's records). The real game is never read.
"""

from __future__ import annotations

import hashlib
import json
import struct
import threading
from pathlib import Path

import pytest

from cdmw.core import archive_patching
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, parse_papgt, serialize_papgt
from cdmw.core.pathc_format import PathcTable, encode_pathc, parse_pathc, pathc_checksum, register_dds
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import old_install_removal as removal
from cdmw.services.archive_mutation_service import ArchiveMutationService
from tests.test_new_item_service import _fake_dds

SHIPPED_DDS = "character/texture/shipped_d.dds"
OVERLAY_DDS = "character/texture/cdmw_new_item_d.dds"
SHARED_DDS = "character/texture/shared_d.dds"


@pytest.fixture(autouse=True)
def _owned_backups(tmp_path, monkeypatch):
    from cdmw.app.app_folder import SYSTEM_TEMP_ENV

    monkeypatch.setattr(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", tmp_path / "backups")
    (tmp_path / "system-temp").mkdir()
    monkeypatch.setenv(SYSTEM_TEMP_ENV, str(tmp_path / "system-temp"))


def _group(folder: Path, paths) -> int:
    dds = _fake_dds(64, 64)
    archive = build_overlay_archive([OverlayFile(path=p, payload=dds, orig_size=len(dds), flags=0) for p in paths])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "0.pamt").write_bytes(archive.pamt_bytes)
    (folder / "0.paz").write_bytes(archive.paz_bytes)
    return archive.pamt_checksum


def _registry(root: Path, paths) -> None:
    dds = _fake_dds(64, 64)
    table = PathcTable(0, 148, (), (), (), b"")
    for path in paths:
        table = register_dds(table, path, dds)
    (root / "meta" / "0.pathc").write_bytes(encode_pathc(table))


def _mount(root: Path, entries) -> None:
    directories = [PapgtDirectory(name, PAPGT_DEFAULT_FLAGS, checksum) for name, checksum in entries]
    (root / "meta" / "0.papgt").write_bytes(serialize_papgt(directories))


def _game(tmp_path: Path, *, overlay=False, virtual=False, half_removed=False) -> Path:
    root = tmp_path / "game"
    (root / "bin64").mkdir(parents=True)
    (root / "meta").mkdir()
    (root / "bin64" / "CrimsonDesert.exe").write_bytes(b"owned stand-in executable")
    shipped = _group(root / "0009", [SHIPPED_DDS, SHARED_DDS])
    mounted, textures = [("0009", shipped)], [SHIPPED_DDS, SHARED_DDS]
    if overlay:
        checksum = _group(root / "0036", [OVERLAY_DDS, SHARED_DDS])
        (root / "0036" / removal.OVERLAY_OWNER_MARKER).write_bytes(removal.OVERLAY_OWNER_BYTES)
        mounted.insert(0, ("0036", checksum))
        textures.append(OVERLAY_DDS)
        (root / ".cdmw" / "overlays").mkdir(parents=True)
        (root / ".cdmw" / "overlays.json").write_text(json.dumps({
            "format": "cdmw_overlay_inventory_v1", "directory": "0036",
            "layers": [{"id": "a" * 32, "label": "Wolf's Fang", "active": True}]}), encoding="utf-8")
        (root / ".cdmw" / "overlays" / ("a" * 32 + ".zip")).write_bytes(b"journal")
        if half_removed:
            import shutil

            shutil.rmtree(root / "0036")
    if virtual:
        asi = b"owned stand-in ASI"
        (root / "bin64" / "CDMWVirtualLoader.asi").write_bytes(asi)
        (root / "bin64" / "winmm.dll").write_bytes(b"the user's ASI loader")
        folder = root / ".cdmw" / "virtual-loader"
        (folder / "save-backups" / "1").mkdir(parents=True)
        (folder / "save-backups" / "1" / "save.sav").write_bytes(b"a save")
        (folder / "generations" / "g1").mkdir(parents=True)
        (folder / "generations" / "g1" / "view.bin").write_bytes(b"private view")
        (folder / "runtime-owner.json").write_text(json.dumps(
            {"format": removal.RUNTIME_OWNER_FORMAT, "sha256": hashlib.sha256(asi).hexdigest()}), encoding="utf-8")
        (folder / "profile.json").write_text(json.dumps({"format": "cdmw_virtual_profile_v1"}), encoding="utf-8")
    (root / ".cdmw").mkdir(exist_ok=True)
    (root / ".cdmw" / "independent-items.json").write_text('{"format": "kept", "items": {}}', encoding="utf-8")
    _mount(root, mounted)
    _registry(root, textures)
    return root


def _fingerprint(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _remove(plan, root, **overrides):
    service = ArchiveMutationService()
    options = dict(
        confirmed=True, configured_root=root, running_check=lambda: "",
        backup=lambda paths, label: service.backup_files(paths, description=label),
        restore_backup=lambda path: service.restore_backup(path, confirmed=True, game_root=root),
    )
    options.update(overrides)
    return removal.remove_old_install(plan, **options)


def test_nothing_found_in_a_clean_game_offers_nothing(tmp_path):
    root = _game(tmp_path)
    plan = removal.find_old_install(root)
    assert plan.nothing_found and not plan.can_remove and plan.review_lines() == ()
    with pytest.raises(removal.OldInstallRemovalRefused, match="Nothing an older CDMW installed"):
        _remove(plan, root)


def test_an_overlay_install_is_removed_with_its_mount_and_registry_entries_and_can_be_restored(tmp_path):
    root = _game(tmp_path, overlay=True)
    before = _fingerprint(root)
    plan = removal.find_old_install(root)
    assert plan.can_remove and plan.overlay_folders == ("0036",) and plan.mount_entries == ("0036",)
    # The shared texture is also shipped, so only the overlay's own texture leaves the registry.
    assert plan.registry_paths == (OVERLAY_DDS,)
    assert plan.overlay_items == ("Wolf's Fang",)
    lines = "\n".join(plan.review_lines())
    assert "Folder 0036" in lines and "Mount list entry 0036" in lines and OVERLAY_DDS in lines
    assert "File .cdmw/overlays.json" in lines
    result = _remove(plan, root)
    assert not (root / "0036").exists() and not (root / ".cdmw" / "overlays.json").exists()
    assert not (root / ".cdmw" / "overlays").exists()
    assert [item.name for item in parse_papgt((root / "meta/0.papgt").read_bytes())] == ["0009"]
    table = parse_pathc((root / "meta/0.pathc").read_bytes())
    assert table.index_of(pathc_checksum(OVERLAY_DDS)) is None
    assert table.index_of(pathc_checksum(SHIPPED_DDS)) is not None and table.index_of(pathc_checksum(SHARED_DDS)) is not None
    assert (root / ".cdmw/independent-items.json").is_file()  # Send to DMM still uses it
    # The removal is itself undone by Restore Backup.
    ArchiveMutationService().restore_backup(result.backup_dir, confirmed=True, game_root=root)
    assert _fingerprint(root) == before


def test_a_virtual_loader_install_keeps_the_users_loader_and_save_backups(tmp_path):
    root = _game(tmp_path, virtual=True)
    plan = removal.find_old_install(root)
    assert removal.RUNTIME_PATH in plan.delete_files and plan.mount_entries == () and plan.registry_paths == ()
    assert not any("save-backups" in path for path in plan.delete_files)
    assert any("winmm.dll" in line for line in plan.kept) and any("save backups" in line for line in plan.kept)
    _remove(plan, root)
    assert not (root / "bin64/CDMWVirtualLoader.asi").exists()
    assert (root / "bin64/winmm.dll").read_bytes() == b"the user's ASI loader"
    assert (root / ".cdmw/virtual-loader/save-backups/1/save.sav").read_bytes() == b"a save"
    assert not (root / ".cdmw/virtual-loader/generations").exists()
    assert not (root / ".cdmw/virtual-loader/profile.json").exists()


def test_both_installs_go_in_one_removal(tmp_path):
    root = _game(tmp_path, overlay=True, virtual=True)
    plan = removal.find_old_install(root)
    assert plan.overlay_folders == ("0036",) and removal.RUNTIME_PATH in plan.delete_files
    _remove(plan, root)
    assert not (root / "0036").exists() and not (root / "bin64/CDMWVirtualLoader.asi").exists()


def test_a_foreign_folder_that_looks_similar_and_an_unproven_asi_are_left_and_named(tmp_path):
    root = _game(tmp_path, overlay=True, virtual=True)
    # Another manager's mounted group, no CDMW mark, holding the overlay's texture too.
    foreign = _group(root / "0037", [OVERLAY_DDS])
    mounted = [(item.name, item.pamt_checksum) for item in parse_papgt((root / "meta/0.papgt").read_bytes())]
    _mount(root, [mounted[0], ("0037", foreign), *mounted[1:]])
    (root / "0038").mkdir()
    (root / "0038" / removal.OVERLAY_OWNER_MARKER).write_bytes(b"a different mark\n")
    (root / "0036" / "notes.txt").write_text("the user's file", encoding="utf-8")
    (root / ".cdmw/virtual-loader/runtime-owner.json").write_text(json.dumps(
        {"format": removal.RUNTIME_OWNER_FORMAT, "sha256": "0" * 64}), encoding="utf-8")
    plan = removal.find_old_install(root)
    assert plan.overlay_folders == ("0036",)
    named = "\n".join(plan.not_cdmw)
    assert "0037: no CDMW owner mark" in named and "0038: no CDMW owner mark" in named
    assert "0036/notes.txt" in named and removal.RUNTIME_PATH in named
    assert removal.RUNTIME_PATH not in plan.delete_files
    # The mounted look-alike holds the overlay texture too, so the registry keeps that entry.
    assert plan.registry_paths == ()
    assert plan.mount_entries == ("0036",)
    result = _remove(plan, root)
    assert (root / "0037/0.pamt").is_file() and (root / "0038").is_dir()
    assert [item.name for item in parse_papgt((root / "meta/0.papgt").read_bytes())] == ["0037", "0009"]
    assert (root / "0036/notes.txt").read_text(encoding="utf-8") == "the user's file"
    assert result.leftovers == ("0036",)
    assert (root / "bin64/CDMWVirtualLoader.asi").is_file()


def test_a_half_removed_install_is_finished_from_cdmws_records(tmp_path):
    root = _game(tmp_path, overlay=True, half_removed=True)
    plan = removal.find_old_install(root)
    assert plan.overlay_folders == ("0036",) and plan.mount_entries == ("0036",)
    _remove(plan, root)
    assert [item.name for item in parse_papgt((root / "meta/0.papgt").read_bytes())] == ["0009"]
    assert not (root / ".cdmw/overlays.json").exists()


def test_the_current_games_mount_list_is_never_rewritten(tmp_path):
    root = _game(tmp_path, overlay=True)
    names = [b"0036", b"0009"]
    table = b"".join(name + b"\x00" for name in names)
    records = b"".join(struct.pack("<III", PAPGT_DEFAULT_FLAGS, offset, 0) for offset in (0, 5))
    compact = bytes([0, 0, len(names), 2]) + records + struct.pack("<I", len(table)) + table + bytes(64)
    (root / "meta/0.papgt").write_bytes(compact)
    plan = removal.find_old_install(root)
    assert plan.blockers and "Verify integrity" in plan.blockers[0] and not plan.can_remove
    before = _fingerprint(root)
    with pytest.raises(removal.OldInstallRemovalRefused, match="Verify integrity"):
        _remove(plan, root)
    assert _fingerprint(root) == before


@pytest.mark.parametrize("refusal", ["running", "changed", "other_root", "unconfirmed"])
def test_refusals_change_nothing(tmp_path, refusal):
    root = _game(tmp_path, overlay=True)
    plan = removal.find_old_install(root)
    before = _fingerprint(root)
    overrides = {}
    if refusal == "running":
        overrides["running_check"] = lambda: "Close Crimson Desert first."
    elif refusal == "changed":
        (root / "0036/0.paz").write_bytes(b"changed by another program")
        before = _fingerprint(root)
    elif refusal == "other_root":
        overrides["configured_root"] = tmp_path / "another-game"
    else:
        overrides["confirmed"] = False
    with pytest.raises((removal.OldInstallRemovalRefused, PermissionError)):
        _remove(plan, root, **overrides)
    assert _fingerprint(root) == before
    assert not (tmp_path / "backups").exists() or not any((tmp_path / "backups").iterdir())


def test_cancel_before_writing_changes_nothing(tmp_path):
    root = _game(tmp_path, overlay=True, virtual=True)
    plan = removal.find_old_install(root)
    before = _fingerprint(root)
    stop = threading.Event()
    service = ArchiveMutationService()

    def backup_then_cancel(paths, label):
        directory = service.backup_files(paths, description=label)
        stop.set()
        return directory

    with pytest.raises(RunCancelled):
        _remove(plan, root, backup=backup_then_cancel, stop_event=stop)
    assert _fingerprint(root) == before


def test_a_failure_midway_puts_every_file_back(tmp_path, monkeypatch):
    root = _game(tmp_path, overlay=True, virtual=True)
    plan = removal.find_old_install(root)
    before = _fingerprint(root)
    real_unlink = Path.unlink
    count = {"n": 0}

    def failing_unlink(self, *args, **kwargs):
        count["n"] += 1
        if count["n"] == 3:
            raise OSError("owned failure in the middle")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(OSError, match="owned failure"):
        _remove(plan, root)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert _fingerprint(root) == before
    # The mount list was written before the failure and is back as it was.
    assert [item.name for item in parse_papgt((root / "meta/0.papgt").read_bytes())] == ["0036", "0009"]


def test_a_link_in_the_way_refuses_the_check(tmp_path):
    root = _game(tmp_path, overlay=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.json").write_text("{}", encoding="utf-8")
    link = root / ".cdmw" / "retired-overlays"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        import _winapi  # A junction needs no privilege.

        _winapi.CreateJunction(str(outside), str(link))
    plan = removal.find_old_install(root)
    assert all(not path.startswith(".cdmw/retired-overlays") for path in plan.delete_files)
    _remove(plan, root)
    assert (outside / "victim.json").is_file()  # nothing behind the link is touched


def test_the_service_imports_no_removed_installer():
    import ast

    tree = ast.parse(Path(removal.__file__).read_text(encoding="utf-8"))
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {module for module in modules if module and any(name in module for name in (
        "archive_overlay_install", "archive_overlay_manager", "archive_overlay_migration", "virtual_loader",
        "independent_item_install", "overlay_target_recovery"))}
