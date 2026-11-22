"""DMM 5's runtime mount: CDMW reads bin64/dmm/manifest.tsv and shows the served files (experimental)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryRef
from cdmw.domain.archives.catalogue_operations import ArchiveBackendOperation, PrepareEntriesResult, PrepareEntryResult
from cdmw.services import dmm_runtime_mount as dmm
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService, _CatalogueRequest

PAVER = bytes.fromhex("0200050001000100000006000000646c635f30310900000086bef44e")
MESH = "character/model/1_pc/1_phm/weapon/cd_phm_01_sword_0109.pac"


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.paver").write_bytes(PAVER)
    (game / "bin64" / "dmm" / "files").mkdir(parents=True)
    (game / "bin64" / "CrimsonDesert.exe").write_bytes(b"MZ" + bytes(98))
    return game


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _manifest(game: Path, lines: list[str], *, build: str | None = None, exe_size: int = 100) -> Path:
    text = ["# Written by DMM. The runtime plugin (DmmRuntime.asi) serves these files to the game.",
            "dmm-runtime\t1", f"build\t{build or PAVER.hex()}\t{exe_size}", *lines]
    path = game / "bin64" / "dmm" / "manifest.tsv"
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    return path


def _mounted(tmp_path: Path):
    game = _game(tmp_path)
    store = tmp_path / "DMM"
    mesh = _write(store / "archive_cache" / "Sword_1.0_zip" / "Sword Mod" / "0041" / MESH, b"modded mesh")
    table = "gamedata/binary__/client/bin/iteminfo.pabgb"
    _write(store / "archive_cache" / "Sword_1.0_zip" / "Sword Mod" / "0041" / table, b"modded table")
    css = "ui/xml/gamemain/play/hudview2.css"
    loose = _write(store / "mods" / "KC-UI" / "KC - UI EDITION" / css, b"loose css")
    merged = _write(game / "bin64" / "dmm" / "files" / "ui/xml/texture/cd_ink_bg_00.xml", b"<merged/>")
    _manifest(game, [
        f"file\t{MESH}\t{mesh}",
        f"file\t{table}\t{store / 'archive_cache' / 'Sword_1.0_zip' / 'Sword Mod' / '0041' / table}",
        f"file\t{css}\t{loose}",
        f"file\tui/xml/texture/cd_ink_bg_00.xml\t{merged}",
    ])
    return game, store


def test_reads_the_manifest_as_dmm_runtime_does(tmp_path):
    game, _store = _mounted(tmp_path)
    mount = dmm.read_runtime_mount(game)
    assert mount is not None and mount.serving and mount.problem == ""
    assert len(mount.files) == 4
    assert mount.files[MESH].mod == "Sword_1.0_zip/Sword Mod"
    assert mount.files["ui/xml/gamemain/play/hudview2.css"].mod == "KC-UI/KC - UI EDITION"
    assert mount.files["ui/xml/texture/cd_ink_bg_00.xml"].mod == dmm.DMM_MERGED_LABEL


def test_mod_label_follows_the_mount_log_names():
    source = (r"C:\DMM\archive_cache\CrimsonFastLoad_1.1.6_3768/CrimsonFastLoad\0041\paconfig.txt")
    assert dmm.mod_label(source, "paconfig.txt") == "CrimsonFastLoad_1.1.6_3768/CrimsonFastLoad"
    built = r"C:\games\Steam\steamapps\common\Crimson Desert\bin64\dmm\files\ui/xml/texture/cd_hud_status_01.xml"
    assert dmm.mod_label(built, "ui/xml/texture/cd_hud_status_01.xml") == dmm.DMM_MERGED_LABEL


def test_nothing_mounted_and_unreadable_manifests(tmp_path):
    game = _game(tmp_path)
    assert dmm.read_runtime_mount(game) is None
    (game / "bin64" / "dmm" / "manifest.tsv").write_text("dmm-runtime\t2\n", encoding="utf-8")
    with pytest.raises(dmm.DmmManifestError, match="version 2"):
        dmm.read_runtime_mount(game)
    (game / "bin64" / "dmm" / "manifest.tsv").write_text("dmm-runtime\t1\nfile\ta.pac\tC:\\a.pac\n", encoding="utf-8")
    with pytest.raises(dmm.DmmManifestError, match="before the build line"):
        dmm.read_runtime_mount(game)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    mount, error = overlay.mount(game)
    assert mount is None and "cannot be read" in error
    assert dmm.describe_mount(game, overlay)["state"] == "unreadable"


def test_a_game_update_after_the_mount_serves_nothing(tmp_path):
    game, _store = _mounted(tmp_path)
    (game / "bin64" / "CrimsonDesert.exe").write_bytes(bytes(101))
    mount = dmm.read_runtime_mount(game)
    assert mount is not None and not mount.serving and "updated" in mount.problem
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    assert overlay.prepare(game, MESH) is None
    assert dmm.describe_mount(game, overlay)["state"] == "stale"


def test_prepare_copies_the_served_file_and_keeps_game_tables(tmp_path):
    game, store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    prepared = overlay.prepare(game, MESH.upper())
    assert prepared is not None
    assert prepared.path.read_bytes() == b"modded mesh"
    assert prepared.sha256 == hashlib.sha256(b"modded mesh").hexdigest() and prepared.size == 11
    assert prepared.path.is_relative_to(tmp_path / "copies") and prepared.path.suffix == ".pac"
    assert prepared.mod == "Sword_1.0_zip/Sword Mod"
    assert overlay.prepare(game, "gamedata/binary__/client/bin/iteminfo.pabgb") is None
    assert overlay.prepare(game, "character/model/vanilla_only.pac") is None
    # A new mount that changes the served file gives a new copy; the old copy stays for open editors.
    source = store / "archive_cache" / "Sword_1.0_zip" / "Sword Mod" / "0041" / MESH
    source.write_bytes(b"modded mesh, second mount")
    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 5_000_000))
    again = overlay.prepare(game, MESH)
    assert again is not None and again.path != prepared.path and prepared.path.read_bytes() == b"modded mesh"


def test_turned_off_or_unmounted_shows_the_game_files(tmp_path):
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    overlay.set_enabled(False)
    assert overlay.prepare(game, MESH) is None
    assert dmm.describe_mount(game, overlay)["state"] == "off"
    overlay.set_enabled(True)
    assert dmm.describe_mount(game, overlay)["state"] == "serving"
    (game / "bin64" / "dmm" / "manifest.tsv").unlink()
    assert overlay.prepare(game, MESH) is None
    assert dmm.describe_mount(game, overlay)["state"] == "not_mounted"


def test_a_source_that_is_not_the_named_file_is_not_read(tmp_path):
    game = _game(tmp_path)
    other = _write(tmp_path / "elsewhere" / "secret.txt", b"not a mesh")
    _manifest(game, [f"file\t{MESH}\t{other}"])
    assert dmm.DmmMountOverlay(tmp_path / "copies").prepare(game, MESH) is None


def _item(path: str, entry_id: int = 7) -> PrepareEntryResult:
    identity = ArchiveDurableIdentity(path, "0009/0.pamt", 0, 4096)
    return PrepareEntryResult(ArchiveEntryRef("session", entry_id, identity, path), "C:/prepared/x.bin", 3, "a" * 64,
                              note="Raw", content_analysis_json_path="C:/analysis.json")


def test_catalogue_results_use_the_files_dmm_serves(tmp_path, monkeypatch):
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    request = _CatalogueRequest(ArchiveBackendOperation.PREPARE_ENTRY, None, 1, lambda value: value,
                                session_id="session", package_root=str(game))
    swapped = ArchiveCatalogueService._with_dmm_mounted_files(request, _item(MESH))
    assert Path(swapped.prepared_path).read_bytes() == b"modded mesh"
    assert swapped.size == 11 and swapped.sha256 == hashlib.sha256(b"modded mesh").hexdigest()
    assert swapped.note == "Raw,DMM mod: Sword_1.0_zip/Sword Mod"
    assert swapped.content_analysis_json_path is None
    batch = PrepareEntriesResult("session", (_item(MESH), _item("character/model/vanilla.pac", 8)), 2, 2, 6)
    result = ArchiveCatalogueService._with_dmm_mounted_files(request, batch)
    assert result.items[0].size == 11 and result.items[1] == batch.items[1] and result.total_bytes == 14
    overlay.set_enabled(False)
    assert ArchiveCatalogueService._with_dmm_mounted_files(request, batch) is batch
    other = _CatalogueRequest(ArchiveBackendOperation.PREPARE_ENTRY, None, 1, lambda value: value)
    overlay.set_enabled(True)
    assert ArchiveCatalogueService._with_dmm_mounted_files(other, batch) is batch


def test_settings_group_and_ai_tool(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("archive/package_root", str(game))
    from cdmw.ui.dmm_mounted_mods_group import DmmMountedModsGroup

    group = DmmMountedModsGroup(settings)
    assert group.show_checkbox.isChecked() and "4 file(s) from 3 mod(s)" in group.status_label.text()
    group.show_checkbox.setChecked(False)
    assert not overlay.enabled and dmm.setting_enabled(settings) is False
    assert "turned off" in group.status_label.text()
    group.show_checkbox.setChecked(True)

    from cdmw.mcp.dmm_mount_tools import _mounted as tool_handler

    class Context:
        def game_folder(self):
            return str(game)

    class Call:
        context = Context()
        arguments = {"path_contains": "sword"}

    report = tool_handler(Call())
    assert report["experimental"] is True and report["state"] == "serving" and report["matching"] == 1
    assert report["served"][0]["game_path"] == MESH and report["served"][0]["shown"] is True


def test_export_writes_the_files_dmm_serves(tmp_path, monkeypatch):
    import json

    from cdmw.domain.archives.catalogue_operations import (
        ArchiveExportItem, ArchiveExportRequest, ArchiveExportResult, ArchiveExportSelectionKind)

    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    out = tmp_path / "export"
    table = "gamedata/binary__/client/bin/iteminfo.pabgb"
    for path in (MESH, table, "character/model/vanilla.pac"):
        _write(out / path, b"vanilla")
    manifest = out / "cdmw-export-manifest.json"
    manifest.write_text(json.dumps({"schema": "cdmw_full_archive_export_v2", "entries": [
        {"path": path, "output_path": path, "original_size": 7} for path in (MESH, table, "character/model/vanilla.pac")]}),
        encoding="utf-8")
    payload = ArchiveExportRequest("session", ArchiveExportSelectionKind.ENTRY_IDS, str(out), entry_ids=(1, 2, 3))
    request = _CatalogueRequest(ArchiveBackendOperation.EXPORT, payload, 1, lambda value: value,
                                session_id="session", package_root=str(game))
    # A batch only collects items: its files are still in the export's staging folder.
    batch = ArchiveExportResult("session", 3, 0, 0, 0, False, None,
                                (ArchiveExportItem(MESH, str(out / MESH), "exported"),), False)
    assert ArchiveCatalogueService._with_dmm_mounted_files(request, batch, final=False) is batch
    assert (out / MESH).read_bytes() == b"vanilla"
    result = ArchiveExportResult("session", 3, 3, 0, 0, False, str(manifest),
                                 (ArchiveExportItem(MESH, str(out / MESH), "exported"),), False)
    noted = ArchiveCatalogueService._with_dmm_mounted_files(request, result)
    assert (out / MESH).read_bytes() == b"modded mesh"
    assert (out / table).read_bytes() == b"vanilla" and (out / "character/model/vanilla.pac").read_bytes() == b"vanilla"
    assert noted.items[0].message == "DMM mod: Sword_1.0_zip/Sword Mod"
    rows = {row["path"]: row for row in json.loads(manifest.read_text(encoding="utf-8"))["entries"]}
    assert rows[MESH]["dmm_mod"] == "Sword_1.0_zip/Sword Mod" and rows[MESH]["dmm_size"] == 11
    assert "dmm_mod" not in rows[table]


def test_export_without_a_manifest_uses_the_streamed_items(tmp_path):
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    out = tmp_path / "export"
    _write(out / "x" / MESH, b"vanilla")
    files, short = dmm.exported_files(out, None, [(MESH, str(out / "x" / MESH), "renamed"),
                                                  (MESH, str(out / "y.pac"), "skipped")], True)
    assert files == [(MESH, out / "x" / MESH)] and short == ""
    assert dmm.exported_files(out, None, [], False)[1]
    swaps = dmm.apply_to_export(game, out, files, None, overlay)
    assert len(swaps) == 1 and (out / "x" / MESH).read_bytes() == b"modded mesh"
    # Never outside the export folder.
    outside = _write(tmp_path / "outside" / "a.pac", b"keep")
    assert dmm.apply_to_export(game, out, [(MESH, outside)], None, overlay) == []
    assert outside.read_bytes() == b"keep"


def test_previews_find_files_a_dmm_mod_adds(tmp_path):
    from cdmw.models import ArchiveEntry
    from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet

    game = _game(tmp_path)
    store = tmp_path / "DMM" / "mods" / "Blade"
    xml = "character/model/1_pc/1_phm/weapon/cd_phm_01_sword_9000.pac_xml"
    dds = "character/texture/cd_phm_01_sword_9000_d.dds"
    unrelated = "character/texture/cd_other_9001_d.dds"
    _write(store / MESH, b"pac names cd_phm_01_sword_9000.pac_xml")
    _write(store / xml, b'<Texture Path="Character/Texture/CD_PHM_01_SWORD_9000_D.dds"/>')
    _write(store / dds, b"DDS new texture")
    _write(store / unrelated, b"DDS unrelated")
    _manifest(game, [f"file\t{path}\t{store / path}" for path in (MESH, xml, dds, unrelated)])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    served = overlay.prepare(game, MESH)
    selected = ArchiveEntry(MESH, Path("0009/0.pamt"), Path("0009/0.paz"), 0, 1, 1, 0, 0, prepared_path=served.path,
                            prepared_size=served.size, prepared_sha256=served.sha256, prepared_note="DMM mod: Blade")
    vanilla = ArchiveEntry("character/model/x.pac", Path("0009/0.pamt"), Path("0009/0.paz"), 9, 1, 1, 0, 0,
                           prepared_path=_write(tmp_path / "v.pac", b"cd_other_9001_d.dds"), prepared_size=19)
    added = dmm.added_dependency_entries(game, [selected, vanilla], overlay=overlay)
    assert [entry.path for entry in added] == [xml, dds]
    assert added[1].prepared_path.read_bytes() == b"DDS new texture" and "DMM mod: Blade" in added[1].prepared_note
    snapshot = ArchivePreviewDependencySet("s", 1, (selected,), {MESH: (selected,)}, {"cd_phm_01_sword_0109.pac": (selected,)},
                                           1, False)
    grown = snapshot.with_added_entries(tuple(added))
    assert grown.entries_by_normalized_path[dds] == (added[1],) and grown.total_candidates == 3
    overlay.set_enabled(False)
    assert dmm.added_dependency_entries(game, [selected], overlay=overlay) == []


def test_files_dmm_adds_list(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from cdmw.ui.archive_browser.dmm_added_files import DmmAddedFilesGroup, added_files

    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    mount = dmm.read_runtime_mount(game)
    rows = added_files(dict(mount.files), {"ui/xml/gamemain/play/hudview2.css", "ui/xml/texture/cd_ink_bg_00.xml"})
    assert [row.game_path for row in rows] == [MESH]  # the table stays the game's and is never listed

    class Session:
        session_id = "s"
        package_root = str(game)

    class Bridge:
        current_session = None

    class Archive:
        archive_remote_bridge = Bridge()
        shell = None

    group = DmmAddedFilesGroup(Archive())
    assert group.find() is False and "Load the game archives" in group.status_label.text()
    Archive.archive_remote_bridge.current_session = Session()
    group._show_rows(rows, "")
    assert group.select_paths([MESH.upper()]) == [MESH]
    assert group.open_button.isEnabled() and group.copy_button.isEnabled()
    written = group.copy_selected(tmp_path / "out")
    assert Path(written[0]).read_bytes() == b"modded mesh" and Path(written[0]).as_posix().endswith(MESH)
    with pytest.raises(ValueError):
        group.copy_selected(game / "mods-here")
