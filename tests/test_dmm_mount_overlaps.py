"""Tests for DMM Mounted Mods tab in Mod Management, overlap detection, and overridden previews."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.services import dmm_runtime_mount as dmm
from cdmw.services.dmm_mount_overlaps import (
    DmmOverlapAnalysis,
    format_overlap_report,
    infer_game_path,
    scan_dmm_mount_overlaps,
)
from cdmw.ui.tools.mod_management import ModManagementTab

PAVER = bytes.fromhex("0200050001000100000006000000646c635f30310900000086bef44e")
MESH = "character/model/1_pc/1_phm/weapon/cd_phm_01_sword_0109.pac"
XML_SIDECAR = "character/modelproperty/1_pc/1_phm/weapon/cd_phm_01_sword_0109.pac_xml"
DDS = "character/texture/cd_phm_01_sword_0109_d.dds"
MERGED_XML = "ui/xml/texture/cd_ink_bg_00.xml"


def _qt() -> QApplication:
    return QApplication.instance() or QApplication([])


def _until(predicate, *, timeout: float = 4.0) -> bool:
    app = _qt()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "Crimson Desert"
    _write(game / "meta" / "0.paver", PAVER)
    _write(game / "bin64" / "CrimsonDesert.exe", b"MZ" + bytes(98))
    (game / "bin64" / "dmm" / "files").mkdir(parents=True, exist_ok=True)
    return game


def _manifest(game: Path, lines: list[str], *, exe_size: int = 100) -> Path:
    text = [
        "# Written by DMM.",
        "dmm-runtime\t1",
        f"build\t{PAVER.hex()}\t{exe_size}",
        *lines,
    ]
    return _write(game / "bin64" / "dmm" / "manifest.tsv", "\n".join(text) + "\n")


def _dmm_setup(tmp_path: Path):
    game = _game(tmp_path)
    install = tmp_path / "DMM"
    _write(install / "DMM.exe", b"dmm")
    mods = install / "mods"
    cache = install / "archive_cache"

    # WinnerMod (loose): wins MESH and DDS; DisabledMod (not active) must be ignored.
    win_mesh = _write(mods / "WinnerMod" / MESH, b"winner-mesh")
    win_dds = _write(mods / "WinnerMod" / DDS, b"winner-dds")
    _write(mods / "WinnerMod" / MERGED_XML, b"<winner/>")

    # LoserMod (loose, enabled): ships MESH (with sidecar + DDS) and DDS, overridden on MESH & DDS; wins own extra file.
    _write(mods / "LoserMod" / MESH, b"loser-mesh")
    _write(mods / "LoserMod" / XML_SIDECAR, f'<Model texture="{DDS}"/>'.encode("utf-8"))
    _write(mods / "LoserMod" / DDS, b"loser-dds")
    loser_unique = _write(mods / "LoserMod" / "character/texture/loser_unique.dds", b"loser-unique")
    _write(mods / "LoserMod" / MERGED_XML, b"<loser/>")

    # FullyOverriddenZip (cached archive mod, enabled): 0 wins in manifest, overridden on MESH.
    _write(mods / "FullyOverriddenZip.zip", b"pk")
    _write(cache / "FullyOverriddenZip_zip" / "FullyOverridden" / "0041" / MESH, b"zip-loser-mesh")

    # DisabledMod (loose, NOT in activeBrowserMods): touches MESH, must be ignored.
    _write(mods / "DisabledMod" / MESH, b"disabled-mesh")

    merged_file = _write(game / "bin64" / "dmm" / "files" / MERGED_XML, b"<merged/>")

    _write(
        install / "config.json",
        json.dumps({
            "configVersion": 1,
            "activeBrowserMods": ["WinnerMod", "LoserMod", "FullyOverriddenZip.zip"],
        }),
    )
    _manifest(game, [
        f"file\t{MESH}\t{win_mesh}",
        f"file\t{DDS}\t{win_dds}",
        f"file\tcharacter/texture/loser_unique.dds\t{loser_unique}",
        f"file\t{MERGED_XML}\t{merged_file}",
    ])
    return game, install, mods


def test_read_runtime_mount_records_manifest_duplicates(tmp_path):
    game = _game(tmp_path)
    first = _write(tmp_path / "DMM" / "mods" / "ModA" / MESH, b"a")
    second = _write(tmp_path / "DMM" / "mods" / "ModB" / MESH, b"b")
    _manifest(game, [f"file\t{MESH}\t{first}", f"file\t{MESH}\t{second}"])

    mount = dmm.read_runtime_mount(game)
    assert mount is not None
    assert mount.files[MESH].mod == "ModA"
    assert [item.mod for item in mount.duplicates[MESH]] == ["ModB"]


def test_scan_dmm_mount_overlaps_finds_loose_and_cached_overrides_and_sync_issues(tmp_path, monkeypatch):
    game, install, mods = _dmm_setup(tmp_path)
    mount = dmm.read_runtime_mount(game)
    assert mount is not None

    analysis = scan_dmm_mount_overlaps(mount, saved_dmm_folder=str(install))
    assert analysis.config_checked is True
    assert analysis.unmounted_enabled_mods == ()
    assert analysis.disabled_but_mounted_mods == ()

    mesh_losers = {item.mod for item in analysis.overlaps_by_path[MESH]}
    assert mesh_losers == {"LoserMod", "FullyOverriddenZip_zip/FullyOverridden"}
    assert "DisabledMod" not in mesh_losers

    dds_losers = {item.mod for item in analysis.overlaps_by_path[DDS]}
    assert dds_losers == {"LoserMod"}

    # Merged files record contributors separately and do not create an overlap warning.
    assert MERGED_XML not in analysis.overlaps_by_path
    assert {item.mod for item in analysis.merged_contributors_by_path[MERGED_XML]} == {"WinnerMod", "LoserMod"}
    assert analysis.mod_folders["LoserMod"] == mods / "LoserMod"

    # Enabling an unmounted mod and disabling a mounted mod triggers conservative sync warnings.
    _write(mods / "FreshEnabledMod" / "character/texture/fresh_only.dds", b"fresh")
    _write(
        install / "config.json",
        json.dumps({
            "configVersion": 1,
            "activeBrowserMods": ["WinnerMod", "FreshEnabledMod"],
        }),
    )
    sync_analysis = scan_dmm_mount_overlaps(mount, saved_dmm_folder=str(install))
    assert "FreshEnabledMod" in sync_analysis.unmounted_enabled_mods
    assert "LoserMod" in sync_analysis.disabled_but_mounted_mods

    # Report formatting includes overlaps, fully overridden mods, and sync warnings.
    report = format_overlap_report(mount, analysis, overlay_enabled=True)
    assert "Overlaps: 2" in report
    assert "Fully overridden enabled mods" in report
    assert "FullyOverriddenZip_zip/FullyOverridden" in report
    assert f"{MESH} | Active: WinnerMod | Overridden:" in report

    # Clean mount fallback without DMM config (even if host C:\DMM exists).
    monkeypatch.setattr("cdmw.services.dmm_mount_overlaps.find_dmm", lambda _saved="": None)
    clean_game = _game(tmp_path / "clean")
    clean_file = _write(tmp_path / "StandaloneMods" / "OnlyMod" / DDS, b"only")
    _manifest(clean_game, [f"file\t{DDS}\t{clean_file}"])
    clean_mount = dmm.read_runtime_mount(clean_game)
    fallback = scan_dmm_mount_overlaps(clean_mount, saved_dmm_folder=str(tmp_path / "missing-dmm"))
    assert fallback.config_checked is False
    assert "manifest.tsv entries only" in fallback.config_note
    clean_report = format_overlap_report(clean_mount, fallback)
    assert "No overlapping files detected" in clean_report


def test_mod_management_mounted_tab_rust_projection_overlaps_and_open_overridden(tmp_path, monkeypatch):
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs

    _qt()
    game, install, _mods = _dmm_setup(tmp_path)
    # Also make an unmounted enabled mod so the notice banner renders too.
    _write(install / "mods" / "NotYetMounted" / "character/texture/unmounted.dds", b"x")
    _write(
        install / "config.json",
        json.dumps({
            "configVersion": 1,
            "activeBrowserMods": ["WinnerMod", "LoserMod", "FullyOverriddenZip.zip", "NotYetMounted"],
        }),
    )
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    settings.setValue("dmm/install_folder", str(install))

    mesh_opened = []
    tex_opened = []
    shell = SimpleNamespace(
        settings=settings,
        mesh_editor_tab=SimpleNamespace(
            open_archive_session=lambda entry, *, archive_dependencies=None: mesh_opened.append(
                (entry, archive_dependencies)
            )
        ),
        textures=SimpleNamespace(
            open_prepared_archive_texture=lambda entry, path: tex_opened.append((entry, Path(path)))
        ),
        _prepare_mesh_editor_archive_launch=lambda _entry: True,
        _activate_tool_widget=lambda _w: None,
        set_status_message=lambda *_args, **_kwargs: None,
    )
    archive = SimpleNamespace(
        settings=settings,
        shell=shell,
        archive_remote_bridge=SimpleNamespace(current_session=None),
        archive_catalogue_service=None,
    )

    tab = ModManagementTab(
        window=shell,
        repackage_owner=archive,
        get_package_root=lambda: str(game),
    )
    visible = QWidget()
    dialogs = PresentationDialogs(tab, visible)
    dialogs.active = True
    bridge = NewItemPresentationBridge(tab, dialogs=dialogs.dialogs)
    try:
        assert [tab.pages.tabText(i) for i in range(tab.pages.count())] == ["Item Packages", "Mounted in DMM"]
        assert tab.pages.tabBar().isVisibleTo(tab) or not tab.pages.tabBar().isHidden()
        assert tab._current_page() is tab.mods_page
        # Lazy load: Mounted in DMM did not scan before being opened.
        assert tab.mounted_page._dirty is True
        assert not bridge.snapshot()["unsupported"]

        tab.open_page("mounted")
        assert tab._current_page() is tab.mounted_page
        assert _until(lambda: tab.mounted_page._overlap_analysis is not None and not tab.mounted_page._overlap_scanning)
        assert not bridge.snapshot()["unsupported"]

        page = tab.mounted_page
        # Notice banner warns about NotYetMounted.
        assert not page.notice_label.isHidden()
        assert "NotYetMounted" in page.notice_label.text()

        # All mounted mods: 1 active row per game path (4 total), with amber warning on overlapping paths.
        assert page.selected_mod() == ""
        assert len(page.visible_rows()) == 4
        warning_color = QColor(page._semantic_color_for_test if hasattr(page, "_semantic_color_for_test") else page.file_tree.topLevelItem(0).foreground(1).color())
        mesh_items = [
            page.file_tree.topLevelItem(i)
            for i in range(page.file_tree.topLevelItemCount())
            if page.file_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == MESH
        ]
        assert len(mesh_items) == 1
        assert "Overrides 2 mods" in mesh_items[0].text(1)
        assert isinstance(mesh_items[0].foreground(1), QBrush)
        assert mesh_items[0].foreground(1).color() != page.file_tree.palette().text().color()

        # Merged by DMM stays calm info tint and matches the Merged filter.
        merged_items = [
            page.file_tree.topLevelItem(i)
            for i in range(page.file_tree.topLevelItemCount())
            if page.file_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == MERGED_XML
        ]
        assert len(merged_items) == 1
        assert merged_items[0].text(1) == "Merged by DMM"
        assert merged_items[0].foreground(1).color() != mesh_items[0].foreground(1).color()

        # Detail bar shows winner + overridden mods when selecting the overlapping active row.
        page.select_paths([MESH])
        assert "WinnerMod" in page.detail_label.text()
        assert "LoserMod" in page.detail_label.text()

        # Overlaps filter limits to MESH and DDS.
        page.kind_combo.setCurrentIndex(page.kind_combo.findData("overlaps"))
        assert {row.game_path for row in page.visible_rows()} == {MESH, DDS}
        page.kind_combo.setCurrentIndex(page.kind_combo.findData("all"))

        # Selecting a fully-overridden mod (0 active files) shows its overridden row!
        assert page.select_mod("FullyOverriddenZip_zip/FullyOverridden")
        assert _until(lambda: len(page.visible_rows()) == 1)
        assert page.visible_rows()[0].is_overridden is True
        assert page.visible_rows()[0].winning_mod == "WinnerMod"

        # Selecting LoserMod shows its 1 active file + 2 overridden files, and opens LoserMod's own bytes!
        assert page.select_mod("LoserMod")
        assert page.open_mod_folder_button.isEnabled()
        rows_loser = page.visible_rows()
        assert len(rows_loser) == 3
        assert {r.game_path: r.is_overridden for r in rows_loser} == {
            "character/texture/loser_unique.dds": False,
            MESH: True,
            DDS: True,
        }

        page.select_paths([MESH])
        assert "Active (served): WinnerMod" in page.detail_label.text()
        assert "Selected (overridden): LoserMod" in page.detail_label.text()
        page.open_selected_in_mesh_editor()
        assert _until(lambda: len(mesh_opened) == 1)
        opened_entry, dep_ctx = mesh_opened[0]
        assert opened_entry.prepared_path.read_bytes() == b"loser-mesh"
        assert "overridden by WinnerMod" in opened_entry.prepared_note
        assert dep_ctx.entry_for_path(XML_SIDECAR).prepared_path.read_bytes().startswith(b"<Model")
        assert dep_ctx.entry_for_path(DDS).prepared_path.read_bytes() == b"loser-dds"

        page.select_paths([DDS])
        page.open_selected_in_texture_editor()
        assert _until(lambda: len(tex_opened) == 1)
        tex_entry, tex_path = tex_opened[0]
        assert tex_path.read_bytes() == b"loser-dds"
        assert "overridden by WinnerMod" in tex_entry.prepared_note

        # Copy Overlap Report copies summary to clipboard.
        report = page.copy_overlap_report()
        assert QApplication.clipboard().text() == report
        assert "LoserMod" in report
    finally:
        dialogs.close()
        tab.request_shutdown()
        assert _until(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        visible.deleteLater()
        _qt().sendPostedEvents(None, QEvent.DeferredDelete)


def test_mounted_page_shutdown_cancels_inflight_overlap_scan(tmp_path, monkeypatch):
    from cdmw.ui.tools import dmm_mounted_mods_page as page_mod

    _qt()
    game, _install, _mods = _dmm_setup(tmp_path)
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)

    started = threading.Event()
    release = threading.Event()
    delivered = []

    def slow_scan(_mount, *, saved_dmm_folder="", stop_event=None, **_kwargs):
        started.set()
        while not stop_event.is_set() and not release.is_set():
            time.sleep(0.01)
        return scan_dmm_mount_overlaps(_mount, saved_dmm_folder=saved_dmm_folder, stop_event=stop_event)

    monkeypatch.setattr(page_mod, "scan_dmm_mount_overlaps", slow_scan)
    page = page_mod.DmmMountedModsPage(get_game_root=lambda: str(game))
    orig_finished = page._overlap_finished
    page._overlap_finished = lambda *args: (delivered.append(args), orig_finished(*args))
    try:
        assert started.wait(timeout=2.0)
        assert page._overlap_scanning is True
        page.request_shutdown()
        assert page._overlap_scanning is False
        release.set()
        _qt().processEvents()
        time.sleep(0.05)
        _qt().processEvents()
        assert delivered == []
    finally:
        release.set()
        page.request_shutdown()
        page.deleteLater()
        _qt().sendPostedEvents(None, QEvent.DeferredDelete)


def test_infer_game_path_strips_patch_and_merge_and_skips_containers():
    assert (
        infer_game_path(("character", "descriptors", "kliff.xml.patch"))
        == "character/descriptors/kliff.xml"
    )
    assert (
        infer_game_path(("0012", "ui", "xml", "texture", "hud.xml.merge"))
        == "ui/xml/texture/hud.xml"
    )
    assert infer_game_path(("0041", "0.pamt")) is None
    assert infer_game_path(("0041", "0.paz")) is None
    assert infer_game_path(("modinfo.json",)) is None
    assert infer_game_path(("dmm_pack.json",)) is None


def test_scan_dmm_mount_overlaps_handles_patch_merge_and_pamt_cache_mods(tmp_path):
    game = _game(tmp_path)
    install = tmp_path / "DMM"
    _write(install / "DMM.exe", b"dmm")
    mods = install / "mods"
    cache = install / "archive_cache"

    patch_entry = "WeaponPack/Option 1 - Patch"
    merge_entry = "UiPack/UI Mod"
    pamt_entry = "FastLoad_1.0_pkg/FastLoad"

    _write(mods / "WeaponPack" / "Option 1 - Patch" / "modinfo.json", "{}")
    _write(
        mods / "WeaponPack" / "Option 1 - Patch" / "character/descriptors/kliff.xml.patch",
        "<patch/>",
    )
    _write(
        mods / "UiPack" / "UI Mod" / "files" / "0012" / (MERGED_XML + ".merge"),
        "<merge/>",
    )
    # Packed .pamt/.paz mod in mods/, with its unpacked files mounted from archive_cache/.
    _write(mods / "FastLoad_1.0_pkg" / "FastLoad" / "0041" / "0.pamt", b"pamt")
    _write(mods / "FastLoad_1.0_pkg" / "FastLoad" / "0041" / "0.paz", b"paz")
    cached_dds = _write(
        cache / "FastLoad_1.0_pkg" / "FastLoad" / "0041" / "fastload/logo.dds",
        b"dds",
    )

    merged_kliff = _write(
        game / "bin64" / "dmm" / "files" / "character/descriptors/kliff.xml",
        "<merged-kliff/>",
    )
    merged_hud = _write(game / "bin64" / "dmm" / "files" / MERGED_XML, "<merged-hud/>")

    _write(
        install / "config.json",
        json.dumps({
            "configVersion": 1,
            "activeBrowserMods": [patch_entry, f"{merge_entry}/files", pamt_entry],
        }),
    )
    _manifest(game, [
        f"file\tcharacter/descriptors/kliff.xml\t{merged_kliff}",
        f"file\t{MERGED_XML}\t{merged_hud}",
        f"file\tfastload/logo.dds\t{cached_dds}",
    ])

    mount = dmm.read_runtime_mount(game)
    assert mount is not None
    analysis = scan_dmm_mount_overlaps(mount, saved_dmm_folder=str(install))
    assert analysis.config_checked is True
    assert analysis.unmounted_enabled_mods == ()
    assert analysis.disabled_but_mounted_mods == ()
    assert {
        item.mod for item in analysis.merged_contributors_by_path["character/descriptors/kliff.xml"]
    } == {"WeaponPack/Option 1 - Patch"}
    assert {item.mod for item in analysis.merged_contributors_by_path[MERGED_XML]} == {
        "UiPack/UI Mod/files"
    }


def test_mounted_page_notice_banner_truncates_long_lists_with_full_tooltip(tmp_path, monkeypatch):
    from cdmw.ui.tools.dmm_mounted_mods_page import DmmMountedModsPage

    _qt()
    game = _game(tmp_path)
    dds_file = _write(tmp_path / "DMM" / "mods" / "WinnerMod" / DDS, b"dds")
    _manifest(game, [f"file\t{DDS}\t{dds_file}"])
    overlay = dmm.DmmMountOverlay(tmp_path / "copies")
    monkeypatch.setattr(dmm, "_overlay", overlay)
    mount = dmm.read_runtime_mount(game)
    assert mount is not None

    unmounted = (
        "LongArchive_1.1.6_3768_2026-11-19T21-01Z_CuEZpVMCK/FastLoad",
        "Weapon_Carry_1.1.2/Weapon Carry 1 - Core",
        "Weapon_Carry_1.1.2/Weapon Carry 2 - Kliff",
        "Weapon_Carry_1.1.2/Weapon Carry 3 - Damiane",
        "Weapon_Carry_1.1.2/Weapon Carry 5 - Hide Shield",
    )
    analysis = DmmOverlapAnalysis(
        config_checked=True,
        unmounted_enabled_mods=unmounted,
    )
    page = DmmMountedModsPage(get_game_root=lambda: str(game), defer_initial_load=True)
    try:
        info = dmm.describe_mount(str(game), dmm.current_overlay())
        page._update_notice_banner(info, mount, analysis)
        text = page.notice_label.text()
        assert not page.notice_label.isHidden()
        assert "LongArchive_1.1.6" not in text
        assert "FastLoad" in text
        assert "Weapon Carry 1 - Core" in text
        assert "Weapon Carry 2 - Kliff" in text
        assert "+2 more" in text
        assert "Weapon Carry 5 - Hide Shield" not in text
        tooltip = page.notice_label.toolTip()
        for full_name in unmounted:
            assert full_name in tooltip
    finally:
        page.request_shutdown()
        page.deleteLater()
        _qt().sendPostedEvents(None, QEvent.DeferredDelete)
