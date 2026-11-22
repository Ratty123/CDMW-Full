"""DMM 5's runtime mount: CDMW reads bin64/dmm/manifest.tsv and shows the served files (experimental)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

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



def test_settings_group_follows_the_game_folder_field_and_the_saved_choice(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QLineEdit

    application = QApplication.instance() or QApplication([])
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    from cdmw.ui.dmm_mounted_mods_group import DmmMountedModsGroup

    group = DmmMountedModsGroup(settings)
    field = QLineEdit()
    group.bind_game_folder(field)
    assert "file(s) from" not in group.status_label.text()  # no game folder typed yet
    field.setText(str(game))  # typed, not saved yet
    group._refresh_timer.timeout.emit()
    application.processEvents()
    assert "4 file(s) from 3 mod(s)" in group.status_label.text()
    settings.setValue(dmm.SHOW_MOUNTED_MODS_SETTING, False)  # a profile import, say
    group.reload()
    assert not group.show_checkbox.isChecked() and not overlay.enabled
    assert "turned off" in group.status_label.text()
    settings.setValue(dmm.SHOW_MOUNTED_MODS_SETTING, True)
    group.reload()
    assert group.show_checkbox.isChecked() and overlay.enabled


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


def test_compact_workspace_opens_dmm_mounted_mods_and_edited_results_from_actions(tmp_path, monkeypatch):
    """Compact Workspace exposes the toolbar DMM Mods button, Actions > DMM Mounted Mods..., and Edited Results."""

    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QSplitter, QVBoxLayout, QWidget

    from cdmw.constants import DEFAULT_UI_THEME
    from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
    from cdmw.ui.archive_browser.command_strip import build_archive_command_strip
    from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
    from cdmw.ui.archive_browser.dmm_mounted_mods_dialog import DmmMountedModsDialog
    from cdmw.ui.archive_browser.edited_results import ArchiveEditedResultsMixin

    application = QApplication.instance() or QApplication([])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    class Window(ArchiveControlsPanelMixin, ArchiveAssetCatalogDialogMixin, ArchiveEditedResultsMixin, QWidget):
        def _build_archive_location_controls(self): pass
        def _open_archive_extension_picker(self): pass
        def _canonicalize_archive_extension_filter_control(self): pass
        def _rebuild_archive_extension_filter_choices(self, *_): pass

    window = Window()
    window.archive = window
    window.shell = SimpleNamespace(_archive_controls_sidebar_bounds=lambda: (290, 360, 520),
                                   current_theme_key=DEFAULT_UI_THEME)
    window.textures = SimpleNamespace(_add_combo_choice=lambda combo, label, value: combo.addItem(label, value))
    window.archive_splitter = QSplitter(window)
    window.archive_catalogue_service = SimpleNamespace(character_catalog_available=False)
    window._build_archive_controls_panel(lambda *_: None)
    root = QWidget(window)
    QVBoxLayout(root)
    build_archive_command_strip(window, root)

    actions = root._cdmw_compact_archive_panel_actions
    assert set(actions) == {"edited_results", "dmm_mounted_mods"}
    assert actions["dmm_mounted_mods"].text() == "DMM Mounted Mods..."
    assert root.findChild(QPushButton, "ArchiveDmmModsButton") is window.archive_dmm_mods_button
    assert root._cdmw_compact_archive_actions_button.isEnabled()

    window.resize(1200, 800)
    window.show()
    actions["dmm_mounted_mods"].trigger()
    application.processEvents()
    dialog = getattr(window, "_dmm_mounted_mods_dialog", None)
    assert isinstance(dialog, DmmMountedModsDialog) and dialog.isVisible()
    dialog.close()

    # Edited Results is offered once the Mesh Editor has handed back a result.
    menu = root._cdmw_compact_archive_actions_button.menu()
    menu.aboutToShow.emit()
    assert not actions["edited_results"].isEnabled()
    window.archive_edited_results_list.addItem("helmet.pac (edit 1)")
    menu.aboutToShow.emit()
    assert actions["edited_results"].isEnabled()
    actions["edited_results"].trigger()
    application.processEvents()
    edited_popup = root._cdmw_compact_archive_actions_button.findChild(QFrame, "CompactArchiveEditedResultsPanel")
    assert edited_popup.isVisible() and window.archive_edited_results_group.isVisible()
    edited_popup.hide()
    window.deleteLater()
    application.processEvents()


# ---------------------------------------------------------------- review fixes


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _until(predicate, timeout=5.0) -> bool:
    import time

    application = _qt()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    return bool(predicate())


@pytest.mark.parametrize("path", [
    "gamedata/binary__/client/bin/iteminfo.staticinfobody",
    "gamedata/binary__/client/bin/iteminfo.staticinfoheader",
    "character/model/1_pc/1_phm/cd_phm_01.pappt",
])
def test_current_game_tables_stay_the_games_own(tmp_path, path):
    from cdmw.ui.archive_browser.dmm_added_files import added_files

    game = _game(tmp_path)
    source = _write(tmp_path / "DMM" / "mods" / "Tables" / path, b"merged rows")
    _manifest(game, [f"file\t{path}\t{source}"])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    assert overlay.prepare(game, path) is None
    assert not overlay.serves_any(game, [path])
    mount = dmm.read_runtime_mount(game)
    assert added_files(dict(mount.files), set()) == []
    exported = _write(tmp_path / "out" / path, b"game")
    assert dmm.apply_to_export(game, tmp_path / "out", [(path, exported)], overlay=overlay) == []
    assert exported.read_bytes() == b"game"


def test_state_token_follows_toggles_remounts_and_game_updates(tmp_path):
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    heard = []
    overlay.add_listener(lambda: heard.append(True))
    first = overlay.state_token(game)
    assert overlay.state_token() == first  # nothing changed
    overlay.set_enabled(False)
    assert overlay.state_token() != first and heard == [True]
    overlay.set_enabled(True)
    on = overlay.state_token()
    # A new mount in DMM rewrites the manifest.
    manifest = game / "bin64" / "dmm" / "manifest.tsv"
    os.utime(manifest, ns=(manifest.stat().st_atime_ns, manifest.stat().st_mtime_ns + 5_000_000))
    remounted = overlay.state_token()
    assert remounted != on
    # A game update changes meta/0.paver but not the manifest: the plugin then serves nothing.
    (game / "meta" / "0.paver").write_bytes(PAVER[:-1] + b"\x00")
    assert overlay.state_token() != remounted
    assert overlay.prepare(game, MESH) is None and dmm.describe_mount(game, overlay)["state"] == "stale"
    overlay.refresh(game)
    assert heard == [True, True, True]


def test_build_mod_baseline_never_records_dmm_bytes(tmp_path):
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_archive_results import _source_dependency_note
    from cdmw.workers.mesh_editor_workers import _game_original_reader

    paz = _write(tmp_path / "0009" / "0.paz", b"....game mesh")
    served = _write(tmp_path / "copies" / "ab" / "served.pac", b"modded mesh")
    entry = ArchiveEntry(MESH, tmp_path / "0009" / "0.pamt", paz, 4, 9, 9, 0, 0, prepared_path=served,
                         prepared_sha256=hashlib.sha256(b"modded mesh").hexdigest(), prepared_size=11,
                         prepared_note="Raw,DMM mod: Sword Mod")
    read = _game_original_reader(None)
    assert read(entry) == b"game mesh"
    # Carried into a later pass as a source dependency, it still says DMM serves it.
    assert dmm.is_dmm_note(_source_dependency_note(entry.prepared_note))
    assert not dmm.is_dmm_note(_source_dependency_note("Raw"))
    game = _game(tmp_path)
    mount = dmm.DmmRuntimeMount(game, game / "bin64" / "dmm" / "manifest.tsv", "", 0)
    added = dmm.added_entry(mount, dmm.DmmServedFile(MESH, served, "Sword Mod"),
                            dmm.PreparedDmmFile(served, 11, "a" * 64, "Sword Mod"))
    assert dmm.is_dmm_added_entry(added) and not dmm.is_dmm_added_entry(entry)
    with pytest.raises(FileNotFoundError):
        read(added)  # the game has no original: it stays unknown
    from dataclasses import replace

    from cdmw.services.mesh_archive_results import EDITED_RESULT_NOTE

    with pytest.raises(FileNotFoundError):
        read(replace(added, prepared_note=EDITED_RESULT_NOTE))  # an edited result of it, a later pass


def test_preview_disk_cache_is_keyed_by_the_prepared_bytes(tmp_path, monkeypatch):
    from cdmw.core import archive_media_preview
    from cdmw.models import ArchiveEntry

    monkeypatch.setattr(archive_media_preview, "app_temp_cache_path",
                        lambda *parts: tmp_path.joinpath("cache", *parts))
    paz = _write(tmp_path / "0009" / "0.paz", b"GAME")
    _write(tmp_path / "0009" / "0.pamt", b"pamt")
    vanilla = ArchiveEntry("ui/x.txt", tmp_path / "0009" / "0.pamt", paz, 0, 4, 4, 0, 0)
    served = _write(tmp_path / "served.txt", b"DMM!")
    modded = ArchiveEntry("ui/x.txt", vanilla.pamt_path, paz, 0, 4, 4, 0, 0, prepared_path=served,
                          prepared_sha256=hashlib.sha256(b"DMM!").hexdigest(), prepared_size=4,
                          prepared_note="DMM mod: UI")
    dmm_path, _note = archive_media_preview.ensure_archive_preview_source(modded)
    game_path, _note = archive_media_preview.ensure_archive_preview_source(vanilla)
    assert dmm_path.read_bytes() == b"DMM!" and game_path.read_bytes() == b"GAME"
    assert dmm_path.parent != game_path.parent


def test_catalogue_results_with_dmm_files_are_copied_off_the_ui_thread_in_order(tmp_path, monkeypatch):
    import threading

    from PySide6.QtCore import QObject, Signal

    _qt()

    class Client(QObject):
        request_progress = Signal(str, object)
        request_batch = Signal(str, object)
        request_succeeded = Signal(str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)
        state_changed = Signal(str)
        worker_crashed = Signal(str)
        worker_ready = Signal()

        def submit(self, *_args, **_kwargs):
            return None

        def cancel(self, _request_id):
            return True

        def shutdown(self):
            return None

    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    copied_on = []
    original_copy = overlay._copy

    def copy(*args):
        copied_on.append(threading.current_thread())
        return original_copy(*args)

    monkeypatch.setattr(overlay, "_copy", copy)
    client = Client()
    service = ArchiveCatalogueService(client)
    request = _CatalogueRequest(ArchiveBackendOperation.PREPARE_ENTRY, None, 1, lambda value: value,
                                session_id="session", package_root=str(game))
    published = []
    batch = PrepareEntriesResult("session", (_item(MESH),), 1, 1, 3)
    vanilla = PrepareEntriesResult("session", (_item("character/model/vanilla.pac", 8),), 2, 2, 3)
    service._publish_with_dmm("r", request, batch, final=False, publish=published.append)
    # Nothing DMM serves, but it waits behind the batch that is being copied.
    service._publish_with_dmm("r", request, vanilla, final=True, publish=published.append)
    assert published == []
    assert _until(lambda: len(published) == 2)
    assert published[0].items[0].note.endswith("DMM mod: Sword_1.0_zip/Sword Mod") and published[1] is vanilla
    assert copied_on and copied_on[0] is not threading.main_thread()
    # With nothing in flight, a result DMM serves nothing of is published at once.
    service._publish_with_dmm("s", request, vanilla, final=True, publish=published.append)
    assert published[-1] is vanilla
    # A cancel drops what is still being copied.
    service._publish_with_dmm("t", request, _item(MESH), final=True, publish=published.append)
    service.cancel("t")
    count = len(published)
    assert _until(lambda: "t" not in service._dmm_inflight)
    assert len(published) == count
    # A request that keeps the game's own files is never swapped.
    games_own = _CatalogueRequest(ArchiveBackendOperation.PREPARE_ENTRY, None, 1, lambda value: value,
                                  session_id="session", package_root=str(game), dmm_overlay=False)
    assert ArchiveCatalogueService._with_dmm_mounted_files(games_own, batch) is batch
    service._publish_with_dmm("u", games_own, batch, final=False, publish=published.append)
    assert published[-1] is batch
    service.request_shutdown()


def test_copies_are_pruned_without_walking_the_folder_each_time(tmp_path, monkeypatch):
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    old = _write(tmp_path / "copies" / "aa" / "old" / "cd_old.pac", b"x" * 64)  # an earlier version's named copy
    os.utime(old, ns=(1, 1))
    monkeypatch.setattr(dmm, "COPY_FOLDER_LIMIT_BYTES", 40)
    walks = []
    original = Path.rglob

    def rglob(self, pattern):
        walks.append(self)
        return original(self, pattern)

    monkeypatch.setattr(Path, "rglob", rglob)
    prepared = overlay.prepare(game, MESH)
    assert prepared.path.is_file() and not old.exists() and not old.parent.exists()
    assert len(walks) == 1
    monkeypatch.setattr(dmm, "COPY_FOLDER_LIMIT_BYTES", 1024)
    overlay.prepare(game, "ui/xml/gamemain/play/hudview2.css")
    assert len(walks) == 1  # counted once, then kept up to date


def test_package_reuse_checks_the_bytes_it_was_built_from(tmp_path):
    import json

    from cdmw.models import ArchiveEntry
    from cdmw.ui.mesh_editor.shell_bridge import _package_source_bytes_match

    package = tmp_path / "entry" / "package"
    package.mkdir(parents=True)
    vanilla = ArchiveEntry(MESH, Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0, prepared_path=Path("v"),
                           prepared_sha256="a" * 64, prepared_note="Raw")
    served = ArchiveEntry(MESH, Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0, prepared_path=Path("d"),
                          prepared_sha256="b" * 64, prepared_note="Raw,DMM mod: Sword Mod")

    def load(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError:
            return None

    assert _package_source_bytes_match(package, vanilla, load)
    assert not _package_source_bytes_match(package, served, load)  # records nothing: not for a DMM file
    (package.parent / "cache_entry.json").write_text(json.dumps({"entry_prepared_sha256": "a" * 64}), encoding="utf-8")
    assert _package_source_bytes_match(package, vanilla, load)
    assert not _package_source_bytes_match(package, served, load)


def test_new_item_previews_the_games_own_files():
    from PySide6.QtCore import QObject, Signal

    from cdmw.ui.new_item.template_preview_dependencies import TemplatePreviewDependencies

    _qt()

    class Service(QObject):
        batch_ready = Signal(str, str, object)
        result_ready = Signal(str, str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)
        progress = Signal(str, object)
        current_session = None

    service = Service()
    dependencies = TemplatePreviewDependencies(service)
    assert dependencies._provider._dmm_overlay is False


def test_files_dmm_adds_open_goes_through_the_archive_open(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from cdmw.ui.archive_browser.command_strip import _ArchiveFiltersPopup
    from cdmw.ui.archive_browser.dmm_added_files import DmmAddedFilesGroup, added_files

    _qt()
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    calls = []

    class Tab:
        def open_archive_session(self, entry, *, archive_dependencies=None):
            calls.append(("open", entry, archive_dependencies))

        def open_mesh_file_session_async(self, *_args, **_kwargs):
            raise AssertionError("a lone file open drops unsaved edits")

    class Shell:
        mesh_editor_tab = Tab()
        answer = False

        def _prepare_mesh_editor_archive_launch(self, entry):
            calls.append(("ask", entry))
            return self.answer

        def _activate_tool_widget(self, _tab):
            calls.append(("show",))

        def set_status_message(self, message, error=False):
            calls.append(("status", message))

    class Session:
        session_id = "s"
        package_root = str(game)

    class Bridge:
        current_session = Session()

    class Archive(QWidget):
        archive_remote_bridge = Bridge()
        shell = Shell()

    archive = Archive()
    button = QWidget(archive)
    group = DmmAddedFilesGroup(archive)
    popup = _ArchiveFiltersPopup(group, button)  # the Actions panel holds it in Compact Workspace
    popup.show()
    mount = dmm.read_runtime_mount(game)
    group._show_rows(added_files(dict(mount.files), {"ui/xml/gamemain/play/hudview2.css",
                                                      "ui/xml/texture/cd_ink_bg_00.xml"}), "")
    group.select_paths([MESH])
    assert group.open_selected() == MESH
    assert not popup.isVisible()
    # An unfinished edit the user keeps: nothing opens.
    assert _until(lambda: any(call[0] == "ask" for call in calls))
    assert not any(call[0] == "open" for call in calls)
    Shell.answer = True
    calls.clear()
    group.open_selected()
    assert _until(lambda: any(call[0] == "open" for call in calls))
    _kind, entry, context = next(call for call in calls if call[0] == "open")
    assert entry.path == MESH and dmm.is_dmm_added_entry(entry) and entry.prepared_path.read_bytes() == b"modded mesh"
    assert context.selected_entry is entry and context.remote
    # Turning the overlay off empties the list, which named what DMM served then.
    overlay.set_enabled(False)
    assert group.rows == []
    popup.deleteLater()
    archive.deleteLater()


def test_dmm_added_files_copy_tool_normalizes_duplicate_paths(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from cdmw.mcp.dmm_mount_tools import _added_copy
    from cdmw.ui.archive_browser.dmm_added_files import DmmAddedFilesGroup, DmmAddedFile

    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    class Archive:
        archive_remote_bridge = SimpleNamespace(current_session=SimpleNamespace(session_id="s", package_root=str(game)))
        shell = None

    group = DmmAddedFilesGroup(Archive())
    group._show_rows([DmmAddedFile(MESH, "Sword_1.0_zip/Sword Mod", Path("x"))], "")
    out_dir = tmp_path / "copied"

    class Context:
        window = SimpleNamespace(archive=SimpleNamespace(archive_dmm_added_files_group=group))

        @staticmethod
        def ui_call(fn):
            return fn()

        @staticmethod
        def resolve_output_folder(path):
            return Path(path)

        @staticmethod
        def approve_write(*_args, **_kwargs):
            return True

    call = SimpleNamespace(
        context=Context(),
        arguments={"paths": [MESH.replace("/", "\\"), "/" + MESH.upper()], "folder": str(out_dir)},
    )
    # Test directly with mocked output helper or real context
    monkeypatch.setattr("cdmw.mcp.dmm_mount_tools.output", lambda _call, path, folder=False: Path(path))
    monkeypatch.setattr("cdmw.mcp.dmm_mount_tools.window", lambda _call: Context.window)
    result = _added_copy(call)
    assert len(result["written"]) == 1 and Path(result["written"][0]).read_bytes() == b"modded mesh"


def test_files_dmm_adds_copy_dialog_runs_off_the_ui_thread(tmp_path, monkeypatch):
    import threading
    from PySide6.QtWidgets import QFileDialog, QWidget
    import cdmw.ui.archive_browser.dmm_added_files as dmm_ui

    _qt()
    game, _store = _mounted(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    class Bridge:
        current_session = SimpleNamespace(session_id="s", package_root=str(game))

    class Archive(QWidget):
        archive_remote_bridge = Bridge()
        shell = None

    archive = Archive()
    group = dmm_ui.DmmAddedFilesGroup(archive)
    mount = dmm.read_runtime_mount(game)
    group._show_rows(dmm_ui.added_files(dict(mount.files), set()), "")
    group.select_paths([MESH])
    out_dir = tmp_path / "copied-async"
    out_dir.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(out_dir))
    thread_ids = []
    real_copy = dmm_ui._copy_added_rows

    def traced_copy(game_root, rows, target_root):
        thread_ids.append(threading.get_ident())
        return real_copy(game_root, rows, target_root)

    monkeypatch.setattr(dmm_ui, "_copy_added_rows", traced_copy)
    ui_thread_id = threading.get_ident()
    group.copy_selected_dialog()
    assert _until(lambda: not group._copy_in_progress and group.status_label.text().startswith("Copied "))
    assert thread_ids and thread_ids[0] != ui_thread_id
    assert (out_dir / MESH).read_bytes() == b"modded mesh"
    archive.deleteLater()


def test_files_dmm_adds_open_prepares_referenced_vanilla_game_textures(tmp_path, monkeypatch):
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtWidgets import QWidget
    from cdmw.domain.archives.catalogue import (
        ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRef, ArchiveEntryRole, ArchiveLookupResult,
    )
    from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult, PrepareEntryResult
    from cdmw.ui.archive_browser.dmm_added_files import DmmAddedFilesGroup, _expected_sidecar_path, added_files

    _qt()
    game = _game(tmp_path)
    mods = tmp_path / "mods"
    xml_path = _expected_sidecar_path(MESH)
    vanilla_tex = "character/texture/vanilla_shared_d.dds"
    dmm_sidecar = _write(mods / "Sword" / xml_path, f'<Root><ResourceReferencePath_ITexture _path="{vanilla_tex}"/></Root>'.encode("utf-8"))
    dmm_pac = _write(mods / "Sword" / MESH, b"modded mesh")
    _manifest(game, [f"file\t{MESH}\t{dmm_pac}", f"file\t{xml_path}\t{dmm_sidecar}"])
    vanilla_prepared = tmp_path / "vanilla_tex.dds"
    vanilla_prepared.write_bytes(b"DDS vanilla")
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    class Service(QObject):
        batch_ready = Signal(str, str, object)
        result_ready = Signal(str, str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)

        def __init__(self):
            super().__init__()
            self.n = 0
            self.prepared_ids = []

        def resolve_entries(self, request, *, ui_generation=0):
            self.n += 1
            req_id = f"res-{self.n}"
            wanted = {path.casefold() for path in request.values}
            entries = ()
            if vanilla_tex in wanted:
                ident = ArchiveDurableIdentity(vanilla_tex, "0.pamt", 1, 64)
                entries = (ArchiveEntryDto(
                    "s", 42, ident, vanilla_tex, "0.pamt", "0.paz", 1, 64, 11, 11, 0,
                    ".dds", "0", ArchiveEntryRole.IMAGE, "Texture", True, is_active_override=True,
                ),)
            QTimer.singleShot(0, lambda: self.result_ready.emit(
                req_id, "resolve_entries", ArchiveLookupResult("s", entries, len(entries), False),
            ))
            return req_id

        def prepare_entries(self, request, *, ui_generation=0, dmm_overlay=True):
            self.n += 1
            req_id = f"prep-{self.n}"
            self.prepared_ids.append(tuple(request.entry_ids))
            items = (PrepareEntryResult(
                ArchiveEntryRef("s", 42, ArchiveDurableIdentity(vanilla_tex, "0.pamt", 1, 64), vanilla_tex),
                str(vanilla_prepared), 11, "deadbeef", None,
            ),)
            QTimer.singleShot(0, lambda: self.result_ready.emit(
                req_id, "prepare_entries", PrepareEntriesResult("s", items, 1, 1, 11),
            ))
            return req_id

        def cancel(self, _request_id):
            pass

    opened = []

    class Tab:
        def open_archive_session(self, entry, *, archive_dependencies=None):
            opened.append((entry, archive_dependencies))

    class Shell:
        mesh_editor_tab = Tab()

        def _prepare_mesh_editor_archive_launch(self, _entry):
            return True

        def _activate_tool_widget(self, _tab):
            pass

        def set_status_message(self, *_args, **_kwargs):
            pass

    service = Service()

    class Archive(QWidget):
        archive_remote_bridge = SimpleNamespace(
            current_session=SimpleNamespace(session_id="s", package_root=str(game)),
            controller=SimpleNamespace(generation=1),
        )
        archive_catalogue_service = service
        shell = Shell()

    archive = Archive()
    group = DmmAddedFilesGroup(archive)
    mount = dmm.read_runtime_mount(game)
    group._show_rows(added_files(dict(mount.files), set()), "")
    group.select_paths([MESH])
    group.open_selected()
    assert _until(lambda: len(opened) == 1)
    entry, context = opened[0]
    assert entry.path == MESH
    assert service.prepared_ids == [(42,)]
    vanilla_dep = context.entry_for_path(vanilla_tex)
    assert vanilla_dep is not None and vanilla_dep.prepared_path == vanilla_prepared
    archive.deleteLater()


def test_mod_label_strips_mismatched_internal_paths_and_formats_badges():
    source = (
        r"C:\DMM\mods\Weapon_Carry_-_Base_Game_1.1.2\Weapon Carry 2 - Kliff - 2H Sword on Hip"
        r"\character\motion\1_pc\1_phm\cd_phm_longsword_01_03_normal_stand_weapon_out_001.paa"
    )
    game_path = "character/motion/1_pc/1_phm/00_mon/cd_phm_longsword_01_03_normal_stand_weapon_out_001.paa"
    assert dmm.mod_label(source, game_path) == "Weapon_Carry_-_Base_Game_1.1.2/Weapon Carry 2 - Kliff - 2H Sword on Hip"
    assert dmm.dmm_mod_from_note("Raw,DMM mod: Sword_1.0_zip/Sword Mod") == "Sword_1.0_zip/Sword Mod"
    assert dmm.dmm_mod_from_note("Raw") == ""
    assert dmm.short_mod_name("KC-UI-EDITION/KC - UI EDITION/files") == "KC - UI EDITION"
    assert dmm.short_mod_name("A" * 50, max_chars=20) == ("A" * 17) + "..."


def test_dmm_mounted_mods_dialog_lists_filters_scopes_and_opens_replaced_and_added_files(tmp_path, monkeypatch):
    from PySide6.QtCore import QObject, QSettings, QTimer, Signal
    from PySide6.QtWidgets import QWidget
    from cdmw.domain.archives.catalogue import (
        ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRole, ArchiveLookupResult,
    )
    from cdmw.ui.archive_browser.dmm_mounted_mods_dialog import show_dmm_mounted_mods_dialog
    from cdmw.ui.dmm_mounted_mods_group import DmmMountedModsGroup

    _qt()
    game = _game(tmp_path)
    store = tmp_path / "DMM" / "mods"
    replaced_mesh = MESH
    added_mesh = "character/model/1_pc/1_phm/weapon/cd_phm_01_sword_9999_added.pac"
    replaced_dds = "character/texture/cd_phm_01_sword_0109_d.dds"
    table_path = "gamedata/binary__/client/bin/iteminfo.pabgb"
    _write(store / "SwordPack" / replaced_mesh, b"replaced-pac")
    _write(store / "SwordPack" / added_mesh, b"added-pac")
    _write(store / "SwordPack" / replaced_dds, b"replaced-dds")
    _write(store / "TablePack" / table_path, b"table-bytes")
    _manifest(game, [
        f"file\t{replaced_mesh}\t{store / 'SwordPack' / replaced_mesh}",
        f"file\t{added_mesh}\t{store / 'SwordPack' / added_mesh}",
        f"file\t{replaced_dds}\t{store / 'SwordPack' / replaced_dds}",
        f"file\t{table_path}\t{store / 'TablePack' / table_path}",
    ])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    dto_mesh = ArchiveEntryDto(
        "s", 11, ArchiveDurableIdentity(replaced_mesh, "0009/0.pamt", 0, 128), replaced_mesh,
        "0009/0.pamt", "0009/0.paz", 0, 128, 12, 12, 0, ".pac", "0009", ArchiveEntryRole.MODEL, "Model", True,
        is_active_override=True,
    )
    dto_dds = ArchiveEntryDto(
        "s", 12, ArchiveDurableIdentity(replaced_dds, "0009/0.pamt", 0, 256), replaced_dds,
        "0009/0.pamt", "0009/0.paz", 0, 256, 12, 12, 0, ".dds", "0009", ArchiveEntryRole.IMAGE, "Texture", True,
        is_active_override=True,
    )

    class Service(QObject):
        batch_ready = Signal(str, str, object)
        result_ready = Signal(str, str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)

        def resolve_entries(self, request, *, ui_generation=0):
            wanted = {path.casefold() for path in request.values}
            found = tuple(dto for path, dto in ((replaced_mesh, dto_mesh), (replaced_dds, dto_dds)) if path in wanted)
            QTimer.singleShot(0, lambda: self.result_ready.emit(
                "r-1", "resolve_entries", ArchiveLookupResult("s", found, len(found), False),
            ))
            return "r-1"

        def cancel(self, _request_id):
            pass

    scoped = []
    mesh_opened = []
    tex_opened = []

    class Bridge:
        current_session = SimpleNamespace(session_id="s", package_root=str(game))
        controller = SimpleNamespace(generation=1)

        def apply_entry_id_scope(self, entry_ids, *, label=""):
            scoped.append((tuple(entry_ids), label))
            return True

    class Shell:
        def __init__(self):
            self.settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
            self.mesh_editor_tab = SimpleNamespace(
                open_archive_session=lambda entry, *, archive_dependencies=None: mesh_opened.append((entry, archive_dependencies))
            )
            self.textures = SimpleNamespace(
                open_prepared_archive_texture=lambda entry, path: tex_opened.append((entry, Path(path)))
            )
            self.archive_browser_tab = QWidget()

        def _prepare_mesh_editor_archive_launch(self, _entry):
            return True

        def _activate_tool_widget(self, _tab):
            pass

        def set_status_message(self, *_args, **_kwargs):
            pass

    class Archive(QWidget):
        def __init__(self):
            super().__init__()
            self.archive_remote_bridge = Bridge()
            self.archive_catalogue_service = Service()
            self.shell = Shell()
            self.settings = self.shell.settings

    archive = Archive()
    settings_group = DmmMountedModsGroup(archive.settings)
    settings_group.setChecked(True) if hasattr(settings_group, "setChecked") else None

    dialog = show_dmm_mounted_mods_dialog(archive)
    assert _until(lambda: any(row.in_catalogue is True for row in dialog._all_rows))
    assert len(dialog.visible_rows()) == 4

    # Syncs toggle with Settings > Paths checkbox & persists setting.
    dialog.enabled_checkbox.setChecked(False)
    assert not overlay.enabled and not settings_group.show_checkbox.isChecked()
    assert dmm.setting_enabled(archive.settings) is False
    dialog.enabled_checkbox.setChecked(True)
    assert overlay.enabled and settings_group.show_checkbox.isChecked()

    # Filters by kind cleanly.
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("replaces"))
    assert {row.game_path for row in dialog.visible_rows()} == {replaced_mesh, replaced_dds}
    assert dialog.filter_browse_archives() is True
    assert scoped and scoped[-1][0] == (11, 12)

    # Opening a replaced vanilla mesh preserves vanilla archive identity while using DMM bytes.
    dialog = show_dmm_mounted_mods_dialog(archive)
    assert _until(lambda: any(row.in_catalogue is True for row in dialog._all_rows))
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("all"))
    dialog.select_paths([replaced_mesh])
    assert dialog.show_in_browse_button.isEnabled()
    dialog.open_selected_in_mesh_editor()
    assert _until(lambda: len(mesh_opened) == 1)
    rep_entry, _ctx = mesh_opened[0]
    assert rep_entry.path == replaced_mesh
    assert rep_entry.prepared_path.read_bytes() == b"replaced-pac"
    assert not dmm.is_dmm_added_entry(rep_entry) and Path(rep_entry.pamt_path) == Path("0009/0.pamt")

    # Opening an added mesh marks manifest provenance as added.
    dialog = show_dmm_mounted_mods_dialog(archive)
    assert _until(lambda: any(row.in_catalogue is False for row in dialog._all_rows))
    dialog.select_paths([added_mesh])
    dialog.open_selected_in_mesh_editor()
    assert _until(lambda: len(mesh_opened) == 2)
    add_entry, _ctx = mesh_opened[1]
    assert add_entry.path == added_mesh and dmm.is_dmm_added_entry(add_entry)
    assert add_entry.prepared_path.read_bytes() == b"added-pac"

    # Opening a mounted DDS sends DMM's copy directly to Texture Editor.
    dialog = show_dmm_mounted_mods_dialog(archive)
    assert _until(lambda: any(row.in_catalogue is True for row in dialog._all_rows))
    dialog.select_paths([replaced_dds])
    dialog.open_selected_in_texture_editor()
    assert _until(lambda: len(tex_opened) == 1)
    tex_entry, tex_path = tex_opened[0]
    assert tex_entry.path == replaced_dds and tex_path.read_bytes() == b"replaced-dds"

    dialog.close()
    settings_group.deleteLater()
    archive.deleteLater()


def test_preview_health_and_texture_editor_reflect_dmm_overlay_and_refresh(tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry, ArchivePreviewResult
    from cdmw.ui.archive_browser.dmm_added_files import DmmAddedFilesGroup
    from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin
    from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin

    _qt()
    game = _game(tmp_path)
    store = tmp_path / "DMM" / "mods" / "ArmorMod"
    dds_path = "character/texture/cd_armor_d.dds"
    _write(store / dds_path, b"DDS dmm texture")
    _manifest(game, [f"file\t{dds_path}\t{store / dds_path}"])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    class PreviewPanel(ArchivePreviewTextToolsMixin):
        def __init__(self):
            self.archive_preview_request_entry = None
            self.archive_remote_bridge = None

        def _archive_entry_role_label(self, _entry):
            return "Model"

        def _archive_reference_role_label(self, _ref):
            return ""

        def _archive_known_used_by_references(self, _entry):
            return False

        def _archive_entry_item_name_match(self, _entry):
            return False, False, ""

        def _ui_compact_status_line(self, parts):
            return " | ".join(parts)

    panel = PreviewPanel()
    entry = ArchiveEntry(
        MESH, Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0,
        prepared_note="Raw,DMM mod: Sword_1.0_zip/Sword Mod",
    )
    text = panel._archive_preview_health_text(ArchivePreviewResult(title="x", status="ok", preferred_view="model"), entry)
    assert "DMM: Sword Mod" in text

    # Companion DMM file badge when primary entry is vanilla.
    companion = ArchiveEntry(dds_path, Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0, prepared_note="DMM mod: ArmorMod")
    vanilla_primary = ArchiveEntry(MESH, Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0, prepared_note="Raw")
    panel.archive_remote_bridge = SimpleNamespace(
        prepared_dependencies_for=lambda _e: SimpleNamespace(entries=(vanilla_primary, companion))
    )
    comp_text = panel._archive_preview_health_text(
        ArchivePreviewResult(title="x", status="ok", preferred_view="model"), vanilla_primary,
    )
    assert "DMM Companion Files" in comp_text

    # Toggling overlay refreshes active Browse preview & DMM Mods button.
    events = []
    fake_archive = SimpleNamespace(
        archive_remote_bridge=SimpleNamespace(
            current_session=None,
            cancel_preview_dependencies=lambda *, clear_snapshot=False: events.append(("cancel", clear_snapshot)),
        ),
        editing_in_place=False,
        _clear_archive_preview_cache=lambda: events.append(("clear",)),
        _clear_archive_asset_family_cache=lambda: events.append(("clear_family",)),
        _refresh_archive_dmm_mods_button=lambda: events.append(("refresh_btn",)),
        _current_archive_entry=lambda: vanilla_primary,
        _render_archive_preview=lambda item, *, force=False: events.append(("render", item.path, force)),
    )
    group = DmmAddedFilesGroup(fake_archive)
    overlay.set_enabled(False)
    assert ("refresh_btn",) in events
    assert ("cancel", True) in events
    assert ("render", MESH, True) in events

    # Opening an unprepared DDS in Texture Editor still picks DMM's mounted file.
    overlay.set_enabled(True)
    paz = _write(tmp_path / "0009" / "0.paz", b"vanilla paz bytes")
    opened_textures = []

    class TexBridge(TextureWorkflowEditorBridgeMixin):
        def __init__(self):
            self.archive = SimpleNamespace(
                archive_remote_bridge=SimpleNamespace(current_session=SimpleNamespace(package_root=str(game)))
            )
            self.shell = SimpleNamespace(set_status_message=lambda *a, **kw: None)

        def open_prepared_archive_texture(self, target_entry, source_path):
            opened_textures.append((target_entry, Path(source_path)))

    unprepared = ArchiveEntry(
        dds_path, tmp_path / "0009" / "0.pamt", paz, 0, 17, 17, 0, 0,
    )
    TexBridge()._open_archive_entry_in_texture_editor(unprepared)
    assert len(opened_textures) == 1
    assert opened_textures[0][1].read_bytes() == b"DDS dmm texture"
    assert dmm.dmm_mod_from_note(opened_textures[0][0].prepared_note) == "ArmorMod"
    group.deleteLater()
