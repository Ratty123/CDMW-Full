from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.textures_panel import (
    COLUMN_FILE,
    COLUMN_ROLE,
    COLUMN_STATE,
    COLUMN_THUMBNAIL,
    MeshEditorTexturesPanel,
    TextureThumbnailLoader,
    decode_texture_thumbnail,
    texture_role_label,
    texture_rows_from_manifest,
)

SHARED_SHA = "A" * 64
NORMAL_SHA = "B" * 64
MASK_SHA = "C" * 64


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _manifest() -> dict[str, object]:
    """Two parts share one base colour; part 1 has its own normal; part 0 a layer mask."""
    return {
        "textures": [
            {
                "label": "cd_armor_01_d.dds",
                "role": "base_color",
                "file": {"path": "texture-0000-aaaaaaaaaaaa.dds", "sha256": SHARED_SHA},
                "material_indices_by_lod": [[0, 1], []],
            },
            {
                "label": "cd_armor_01_n.dds",
                "role": "normal",
                "file": {"path": "texture-0001-bbbbbbbbbbbb.dds", "sha256": NORMAL_SHA},
                "material_indices_by_lod": [[1], []],
            },
            {
                # A reference without a copied file: still listed, no decoded path.
                "label": "cd_armor_01_e.dds",
                "role": "emissive",
                "file": {},
                "material_indices_by_lod": [[1]],
            },
        ],
        "preview_core_material_graph": {
            "materials": [
                {
                    "lod_index": 0,
                    "material_index": 0,
                    "layers": [
                        {
                            "layer_role": "base",
                            "diffuse": {"path": "texture-0000-aaaaaaaaaaaa.dds", "sha256": SHARED_SHA},
                            "diffuse_archive_path": "character/texture/cd_armor_01_d.dds",
                            "mask": {"path": "texture-0002-cccccccccccc.dds", "sha256": MASK_SHA},
                            "mask_archive_path": "character/texture/cd_armor_01_mask.dds",
                        },
                    ],
                },
            ],
        },
        "state": {
            "skeleton": {"parts": [{"index": 0, "name": "Chest"}, {"index": 1, "name": "Arms"}]},
            "archive_refit_assets": [
                {"path": "character/model/upper.pac", "role": "editable", "part_indices": [0]},
                {"path": "character/model/arms.pac", "role": "editable", "part_indices": [1]},
            ],
        },
    }


def test_shared_texture_is_marked_on_both_parts(tmp_path: Path) -> None:
    groups = texture_rows_from_manifest(_manifest(), session_root=tmp_path)

    assert [(group.part_index, group.part_name, group.source_file) for group in groups] == [
        (0, "Chest", "upper.pac"), (1, "Arms", "arms.pac"),
    ]
    chest, arms = groups
    chest_base = next(row for row in chest.rows if row.role == "base_color")
    arms_base = next(row for row in arms.rows if row.role == "base_color")
    assert chest_base.shared and arms_base.shared
    assert chest_base.game_path == "character/texture/cd_armor_01_d.dds"
    assert chest_base.file_name == "cd_armor_01_d.dds"
    assert chest_base.decoded_path == str(tmp_path / "texture-0000-aaaaaaaaaaaa.dds")
    assert not next(row for row in arms.rows if row.role == "normal").shared
    assert not next(row for row in chest.rows if row.role == "layer_mask").shared


def test_rows_keep_role_order_and_fall_back_to_the_label() -> None:
    groups = texture_rows_from_manifest(_manifest())
    arms = groups[1]

    assert [row.role for row in arms.rows] == ["base_color", "normal", "emissive"]
    # No game path in the layer graph for this file: its resolved file name stands in.
    assert arms.rows[1].game_path == "cd_armor_01_n.dds"
    assert arms.rows[1].decoded_path == "texture-0001-bbbbbbbbbbbb.dds"


def test_missing_decoded_file_keeps_the_row_without_a_path() -> None:
    arms = texture_rows_from_manifest(_manifest())[1]
    emissive = next(row for row in arms.rows if row.role == "emissive")

    assert emissive.decoded_path == ""
    assert emissive.texture_id == "cd_armor_01_e.dds"


def test_part_names_default_and_override() -> None:
    manifest = _manifest()
    del manifest["state"]
    groups = texture_rows_from_manifest(manifest)
    assert [group.part_name for group in groups] == ["Part 1", "Part 2"]
    assert [group.source_file for group in groups] == ["", ""]

    named = texture_rows_from_manifest(manifest, part_names=["Body", "Sleeves"])
    assert [group.group_heading for group in named] == ["Body", "Sleeves"]


def test_role_labels() -> None:
    assert texture_role_label("base_color") == "Base colour"
    assert texture_role_label("normal") == "Normal"
    assert texture_role_label("layer_mask") == "Mask"
    assert texture_role_label("shader_mask") == "Mask"
    assert texture_role_label("detail") == "Detail"
    assert texture_role_label("skin_detail_normal") == "Detail"
    assert texture_role_label("layer") == "Layer"
    assert texture_role_label("emissive") == "Emissive"
    assert texture_role_label("material") == "Material"
    assert texture_role_label("something_new") == "Other"


def test_empty_or_malformed_manifest_gives_no_groups() -> None:
    assert texture_rows_from_manifest({}) == []
    assert texture_rows_from_manifest({"textures": "nope", "preview_core_material_graph": []}) == []


def test_missing_file_decodes_to_no_thumbnail(tmp_path: Path) -> None:
    assert decode_texture_thumbnail(tmp_path / "absent.dds", 48) is None


def _wait_for(app: QApplication, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def test_panel_fills_the_tree_and_clear_shows_the_placeholder(tmp_path: Path) -> None:
    app = _app()
    image = QImage(16, 16, QImage.Format.Format_RGBA8888)
    image.fill(QColor(200, 40, 40))
    assert image.save(str(tmp_path / "texture-0000-aaaaaaaaaaaa.dds.png"))
    (tmp_path / "texture-0000-aaaaaaaaaaaa.dds").write_bytes(b"stand-in")
    decoded: list[str] = []

    def decoder(path: Path, size: int, _role: str) -> QImage | None:
        # Stands in for the native DDS decoder, which the test never starts.
        decoded.append(path.name)
        result = QImage(str(path) + ".png")
        return None if result.isNull() else result.scaled(size, size)

    pool = QThreadPool()
    loader = TextureThumbnailLoader(pool=pool, decoder=decoder)
    panel = MeshEditorTexturesPanel(thumbnail_loader=loader)
    activated: list[str] = []
    panel.texture_activated.connect(activated.append)
    try:
        assert panel.objectName() == "MeshEditorTexturesDock"
        assert panel.windowTitle() == "Textures"
        assert panel.stack.currentWidget() is panel.placeholder_label
        assert panel.placeholder_label.text() == "Open a mesh to see its textures."

        panel.set_manifest(_manifest(), session_root=tmp_path)

        assert panel.stack.currentWidget() is panel.tree
        # Two files: each is named once, over its parts, not after every part's name.
        assert [panel.tree.topLevelItem(i).text(COLUMN_THUMBNAIL) for i in range(2)] == ["upper.pac", "arms.pac"]
        chest = panel.part_item(0)
        assert chest.text(COLUMN_THUMBNAIL) == "Chest" and chest.parent() is panel.tree.topLevelItem(0)
        assert chest.toolTip(COLUMN_THUMBNAIL) == "Chest (upper.pac)"
        first = chest.child(0)
        assert first.text(COLUMN_ROLE) == "Base colour"
        assert first.text(COLUMN_FILE) == "cd_armor_01_d.dds"
        assert first.toolTip(COLUMN_FILE) == "character/texture/cd_armor_01_d.dds"
        assert first.text(COLUMN_STATE) == "Shared"
        assert chest.child(1).text(COLUMN_STATE) == ""

        # Collapsed parts do not trigger an upfront decode flood; expanding a part decodes
        # its textures once and shares the decoded icon across all matching rows.
        pool.waitForDone(5000)
        app.processEvents()
        assert decoded == []
        chest.setExpanded(True)
        arms_base = panel.part_item(1).child(0)
        assert _wait_for(app, lambda: not first.icon(COLUMN_THUMBNAIL).isNull()
                         and not arms_base.icon(COLUMN_THUMBNAIL).isNull())
        pool.waitForDone(5000)
        app.processEvents()
        assert decoded.count("texture-0000-aaaaaaaaaaaa.dds") == 1
        # Files that do not exist never reach the decoder and show no icon.
        panel.part_item(1).setExpanded(True)
        pool.waitForDone(5000)
        app.processEvents()
        assert "texture-0001-bbbbbbbbbbbb.dds" not in decoded
        assert panel.part_item(1).child(1).icon(COLUMN_THUMBNAIL).isNull()

        panel.tree.itemDoubleClicked.emit(first, COLUMN_ROLE)
        panel.tree.itemDoubleClicked.emit(chest, COLUMN_THUMBNAIL)
        assert activated == ["texture-0000-aaaaaaaaaaaa.dds"]

        panel.clear()
        assert panel.tree.topLevelItemCount() == 0
        assert panel.stack.currentWidget() is panel.placeholder_label
        assert panel.placeholder_label.text() == "Open a mesh to see its textures."

        panel.set_manifest({})
        assert panel.stack.currentWidget() is panel.placeholder_label
        assert panel.placeholder_label.text() == "No textures were resolved for this mesh."

        panel.set_manifest(None)
        assert panel.placeholder_label.text() == "Open a mesh to see its textures."
    finally:
        panel.shutdown()
        pool.waitForDone(5000)
        panel.deleteLater()
        loader.deleteLater()
        app.processEvents()


def test_the_list_starts_closed_and_keeps_what_the_user_opened(tmp_path: Path) -> None:
    """Fredric, 2026-11-17: "Textures list should start not expanded"."""

    _app()
    panel = MeshEditorTexturesPanel(thumbnail_loader=TextureThumbnailLoader(decoder=lambda *_args: None))
    try:
        panel.set_manifest(_manifest(), session_root=tmp_path)
        chest, arms = panel.part_item(0), panel.part_item(1)
        assert not chest.isExpanded() and not arms.isExpanded()
        # The file headers only group: they are open, so every part is in view.
        assert all(panel.tree.topLevelItem(i).isExpanded() for i in range(panel.tree.topLevelItemCount()))
        arms.setExpanded(True)
        # The same session's list rebuilt (the editor reports again) keeps it open.
        panel.set_manifest(_manifest(), session_root=tmp_path)
        assert panel.part_item(1).isExpanded() and not panel.part_item(0).isExpanded()
        # Another mesh starts closed again.
        panel.set_manifest(_manifest(), session_root=tmp_path / "other")
        assert not panel.part_item(1).isExpanded()
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_the_list_is_compact(tmp_path: Path) -> None:
    """Fredric, 2026-11-17: the list "takes just too much space for no reason"."""

    app = _app()
    manifest = _manifest()
    manifest["state"]["archive_refit_assets"] = []  # one file: no header at all
    panel = MeshEditorTexturesPanel(thumbnail_loader=TextureThumbnailLoader(decoder=lambda *_args: None))
    try:
        panel.resize(420, 400)
        panel.show()
        panel.set_manifest(manifest, session_root=tmp_path)
        assert [panel.tree.topLevelItem(i).text(COLUMN_THUMBNAIL) for i in range(2)] == ["Chest", "Arms"]
        panel.part_item(0).setExpanded(True)
        app.processEvents()
        # Three columns: the thumbnail sits in front of the role.
        assert panel.tree.columnCount() == 3 and COLUMN_THUMBNAIL == COLUMN_ROLE
        text_row = panel.tree.fontMetrics().height()
        icon_side = panel.tree.iconSize().height()
        part_row = panel.tree.visualItemRect(panel.part_item(0)).height()
        texture_row = panel.tree.visualItemRect(panel.part_item(0).child(0)).height()
        # Part rows stay compact; texture rows cleanly frame a recognizable 32-36px preview.
        assert part_row <= text_row * 2
        assert 32 <= icon_side <= 36
        assert icon_side <= texture_row <= icon_side + 14
        # Column proportions: Texture and State stay tight while Game file takes remaining width.
        role_w = panel.tree.columnWidth(COLUMN_ROLE)
        file_w = panel.tree.columnWidth(COLUMN_FILE)
        state_w = panel.tree.columnWidth(COLUMN_STATE)
        base_role_w = panel.tree.fontMetrics().horizontalAdvance("Base colour")
        shared_w = panel.tree.fontMetrics().horizontalAdvance("Shared")
        assert role_w <= base_role_w + icon_side + panel.tree.indentation() * 3 + 48
        assert state_w <= max(68, shared_w + 32)
        assert file_w >= 110
        # Widening the dock grows Game file instead of ballooning Texture.
        panel.resize(620, 400)
        app.processEvents()
        assert panel.tree.columnWidth(COLUMN_ROLE) == role_w
        assert panel.tree.columnWidth(COLUMN_STATE) == state_w
        assert panel.tree.columnWidth(COLUMN_FILE) > file_w + 150
        # The file name keeps both ends when it is cut short.
        from PySide6.QtCore import Qt

        assert panel.tree.textElideMode() == Qt.TextElideMode.ElideMiddle
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_the_panel_reads_a_session_folder_off_the_ui_thread(tmp_path: Path) -> None:
    import json

    app = _app()
    panel = MeshEditorTexturesPanel()
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    panel.show_session(tmp_path)
    assert _wait_for(app, lambda: panel.tree.topLevelItemCount() > 0)
    assert panel.stack.currentWidget() is panel.tree
    # A later call wins over a read still in flight; None clears.
    panel.show_session(tmp_path)
    panel.show_session(None)
    _wait_for(app, lambda: False, timeout=0.3)
    assert panel.stack.currentWidget() is panel.placeholder_label
    panel.shutdown()
    panel.deleteLater()


def test_the_mesh_editor_docks_the_panel_on_the_right_and_remembers_where_it_was(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings, Qt

    from cdmw.ui.mesh_editor.textures_panel import DOCK_LAYOUT_KEY, remember_dock_layout
    from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

    _app()
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    host, dock = page.dock_host, page.textures_dock
    assert host.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert dock.features() & dock.DockWidgetFeature.DockWidgetFloatable
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    remember_dock_layout(host, dock, settings)
    host.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    assert settings.value(DOCK_LAYOUT_KEY) is not None
    again = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    remember_dock_layout(again.dock_host, again.textures_dock, settings)
    assert again.dock_host.dockWidgetArea(again.textures_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    page.deleteLater()
    again.deleteLater()


def test_a_saved_layout_never_leaves_the_panel_off_screen(tmp_path: Path) -> None:
    """A saved layout says where the panel is, not whether it shows (TexturePanels does,
    see test_mesh_editor_texture_panels_shown); a panel left off every screen docks again."""

    from PySide6.QtCore import QSettings

    from cdmw.ui.mesh_editor.textures_panel import DOCK_LAYOUT_KEY, remember_dock_layout
    from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

    _app()
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    page.show()
    host, dock = page.dock_host, page.textures_dock
    assert dock.features() & dock.DockWidgetFeature.DockWidgetClosable
    dock.setFloating(True)
    dock.move(-100000, -100000)
    dock.hide()
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue(DOCK_LAYOUT_KEY, host.saveState())
    again = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    again.show()
    remember_dock_layout(again.dock_host, again.textures_dock, settings)
    # Off every screen it docks again (offscreen Qt restores a floating panel at 0,0, so
    # the check is tested on its own).
    from cdmw.ui.mesh_editor.textures_panel import _on_a_screen

    again.textures_dock.setFloating(True)
    assert _on_a_screen(again.textures_dock)
    again.textures_dock.move(-100000, -100000)
    assert not _on_a_screen(again.textures_dock)
    page.deleteLater()
    again.deleteLater()


def test_stale_thumbnail_generation_cancels_before_decoding_and_reuses_framed_icons(tmp_path: Path) -> None:
    import threading

    app = _app()
    (tmp_path / "texture-0000-aaaaaaaaaaaa.dds").write_bytes(b"stand-in")
    (tmp_path / "texture-0001-bbbbbbbbbbbb.dds").write_bytes(b"stand-in")
    gate = threading.Event()
    decoded: list[str] = []

    def decoder(path: Path, size: int, _role: str) -> QImage | None:
        gate.wait(timeout=2.0)
        decoded.append(path.name)
        im = QImage(size, size, QImage.Format.Format_RGBA8888)
        im.fill(QColor(80, 140, 200))
        return im

    pool = QThreadPool()
    pool.setMaxThreadCount(1)  # serialize so the 2nd job stays queued while gen advances
    loader = TextureThumbnailLoader(pool=pool, decoder=decoder)
    panel = MeshEditorTexturesPanel(thumbnail_loader=loader)
    try:
        panel.set_manifest(_manifest(), session_root=tmp_path)
        panel.part_item(0).setExpanded(True)
        panel.part_item(1).setExpanded(True)
        # Advance generation before the 2nd queued job even starts decoding.
        loader.set_generation(panel._generation + 1)
        gate.set()
        pool.waitForDone(5000)
        app.processEvents()
        # At most the single already-running job ran; the queued obsolete job aborted before decoding.
        assert len(decoded) <= 1

        # Fresh generation decodes expanded parts, caches framed icons, and reuses them on rebuild.
        decoded.clear()
        panel.set_manifest(_manifest(), session_root=tmp_path)
        assert _wait_for(app, lambda: not panel.part_item(0).child(0).icon(COLUMN_THUMBNAIL).isNull())
        pool.waitForDone(5000)
        app.processEvents()
        # Rebuild same session: cached icon is already present immediately without waiting on workers.
        panel.set_manifest(_manifest(), session_root=tmp_path)
        assert not panel.part_item(0).child(0).icon(COLUMN_THUMBNAIL).isNull()
    finally:
        gate.set()
        panel.shutdown()
        pool.waitForDone(5000)
        panel.deleteLater()
        loader.deleteLater()
        app.processEvents()


def test_collapsed_parts_do_not_decode_thumbnails_until_expanded(tmp_path: Path) -> None:
    app = _app()
    parts = 20
    for i in range(parts):
        (tmp_path / f"tex-{i:02d}.dds").write_bytes(b"stand-in")
    manifest = {
        "textures": [
            {"label": f"cd_armor_{i:02d}_d.dds", "role": "base_color",
             "file": {"path": f"tex-{i:02d}.dds", "sha256": f"{i:064x}"},
             "material_indices_by_lod": [[i]]}
            for i in range(parts)
        ],
        "state": {"skeleton": {"parts": [{"index": i, "name": f"Part_{i:02d}"} for i in range(parts)]}},
    }
    decoded: list[str] = []

    def decoder(path: Path, size: int, _role: str) -> QImage | None:
        decoded.append(path.name)
        im = QImage(size, size, QImage.Format.Format_RGBA8888)
        im.fill(QColor(90, 140, 180))
        return im

    pool = QThreadPool()
    loader = TextureThumbnailLoader(pool=pool, decoder=decoder)
    panel = MeshEditorTexturesPanel(thumbnail_loader=loader)
    try:
        panel.set_manifest(manifest, session_root=tmp_path)
        pool.waitForDone(5000)
        app.processEvents()
        assert decoded == []
        panel.part_item(3).setExpanded(True)
        assert _wait_for(app, lambda: not panel.part_item(3).child(0).icon(COLUMN_THUMBNAIL).isNull())
        pool.waitForDone(5000)
        app.processEvents()
        assert decoded == ["tex-03.dds"]
    finally:
        panel.shutdown()
        pool.waitForDone(5000)
        panel.deleteLater()
        loader.deleteLater()
        app.processEvents()
