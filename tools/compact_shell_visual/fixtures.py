"""Synthetic, local-only fixtures used to reveal real tool workspaces."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from tools.compact_shell_visual.contracts import SYNTHETIC_MESH_SESSION_ID
from tools.compact_shell_visual.mesh_fixture import (
    _require_bundled_mesh_helper,
    _wait_for_synthetic_mesh_renderer,
)
from tools.compact_shell_visual.runtime import _process_events, _wait_until


def _write_texture_fixture_pair(fixture_root: Path) -> tuple[Path, Path, QImage, QImage]:
    image_root = fixture_root / "generated-texture-fixtures"
    image_root.mkdir(parents=True, exist_ok=True)
    before_path = image_root / "synthetic-before.png"
    after_path = image_root / "synthetic-after.png"

    def build_image(*, base: str, secondary: str, accent: str, caption: str) -> QImage:
        image = QImage(640, 480, QImage.Format.Format_RGBA8888)
        image.fill(QColor(base))
        painter = QPainter(image)
        try:
            for row in range(0, image.height(), 48):
                for column in range(0, image.width(), 48):
                    if (row // 48 + column // 48) % 2:
                        painter.fillRect(column, row, 48, 48, QColor(secondary))
            painter.fillRect(96, 72, 448, 336, QColor(accent))
            painter.fillRect(128, 104, 384, 272, QColor(base))
            painter.setPen(QColor("#f5eadb"))
            painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, caption)
        finally:
            painter.end()
        return image

    before = build_image(
        base="#3b4656",
        secondary="#56677d",
        accent="#9d835e",
        caption="SYNTHETIC BEFORE",
    )
    after = build_image(
        base="#3d2528",
        secondary="#6b3434",
        accent="#d27a42",
        caption="SYNTHETIC AFTER",
    )
    if not before.save(str(before_path), "PNG") or not after.save(str(after_path), "PNG"):
        raise RuntimeError("Could not create the generated texture preview fixtures.")
    return before_path, after_path, before, after


def _install_new_item_fixture(widget: QWidget) -> None:
    if bool(getattr(widget, "_panels_built", False)):
        return
    mount = getattr(widget, "_mount_panels", None)
    if callable(mount):
        mount()


def _install_mesh_fixture(widget: QWidget, evidence: dict[str, object]) -> None:
    from cdmw.modding.static_mesh_scene_frame import static_scene_source_identity
    from tools.mesh_editor_dev_harness import build_synthetic_mesh

    evidence["helper"] = _require_bundled_mesh_helper(widget)
    mesh = build_synthetic_mesh()
    expected_source_identity = static_scene_source_identity(mesh, mesh)
    status_messages: list[str] = []
    status_signal = getattr(widget, "status_message_requested", None)

    def record_status(message: object, error: object = False) -> None:
        status_messages.append(f"{'error' if bool(error) else 'info'}:{str(message)}")
        del status_messages[:-12]

    if status_signal is not None:
        status_signal.connect(record_status)
    widget._cdmw_compact_mesh_status_messages = status_messages
    try:
        if getattr(widget, "standalone_controller", None) is None:
            widget.window().show()
            _process_events(5)
            widget.open_mesh_session(
                mesh,
                session_id=SYNTHETIC_MESH_SESSION_ID,
                mode="edit",
            )
        evidence["resident_renderer"] = _wait_for_synthetic_mesh_renderer(
            widget,
            expected_source_identity=expected_source_identity,
        )
    finally:
        if status_signal is not None:
            status_signal.disconnect(record_status)


def _install_texture_workflow_fixture(widget: QWidget) -> None:
    paths_section = getattr(widget.window(), "paths_section", None)
    set_expanded = getattr(paths_section, "set_expanded", None)
    if callable(set_expanded):
        set_expanded(True)
    fixture_paths = {
        "original_dds_edit": "C:/CDMW-Harness/OriginalDDS",
        "png_root_edit": "C:/CDMW-Harness/UpscaledPNG",
        "texture_editor_png_root_edit": "C:/CDMW-Harness/TextureEditorPNG",
        "dds_staging_root_edit": "C:/CDMW-Harness/StagingPNG",
        "output_root_edit": "C:/CDMW-Harness/RebuiltTextures",
    }
    for name, value in fixture_paths.items():
        edit = getattr(widget.window(), name, None)
        if edit is not None:
            edit.setText(value)


def _install_replace_fixture(
    widget: QWidget,
    fixture_root: Path,
    evidence: dict[str, object],
) -> None:
    from cdmw.models import MatchedOriginalTexture, ReplaceAssistantItem

    before_path, after_path, _before, _after = _write_texture_fixture_pair(fixture_root)
    widget.items = [
        ReplaceAssistantItem(
            source_path=after_path,
            source_kind="PNG",
            detected_package_root="Synthetic fixture",
            matched_original=MatchedOriginalTexture(
                package_root="Synthetic fixture",
                archive_relative_path="",
                loose_relative_path=Path("synthetic-before.png"),
                original_dds_path=before_path,
                match_reason="Generated visual-harness pair",
            ),
            status="matched",
            status_detail="Generated preview pair ready",
        )
    ]
    widget._refresh_queue_tree()
    row = widget.queue_tree.topLevelItem(0)
    if row is None:
        raise RuntimeError("Replace Textures did not expose the generated fixture item.")
    widget.queue_tree.setCurrentItem(row)
    if getattr(widget, "preview_thread", None) is None:
        widget._schedule_preview(widget.items[0])
    if not _wait_until(
        lambda: getattr(widget, "preview_thread", None) is None
        and widget.preview_meta_label.text() != "Preparing preview..."
    ):
        raise RuntimeError("Replace Textures did not finish the generated PNG preview.")
    if widget.preview_title_label.text() == "Preview failed":
        raise RuntimeError(
            "Replace Textures rejected the generated PNG preview: "
            f"{widget.preview_meta_label.text()}"
        )
    widget.preview_title_label.setText("Synthetic replacement preview")
    widget.preview_details_edit.setPlainText(
        "Source: generated after image\n"
        "Original: generated before image\n"
        "Scope: temporary visual-harness fixture\n"
        "Archive/game access: none"
    )
    widget.status_label.setText("1 safe generated fixture queued.")
    evidence["generated_preview_pair"] = {
        "before": before_path.name,
        "after": after_path.name,
        "queue_items": len(widget.items),
        "preview_ready": True,
    }


def _install_recolor_fixture(
    widget: QWidget,
    fixture_root: Path,
    evidence: dict[str, object],
) -> None:
    from cdmw.core.recolor_variants import (
        RecolorVariantAnalysis,
        RecolorVariantPreviewImage,
        RecolorVariantTarget,
    )
    from cdmw.models import ModPackageInfo

    before_path, after_path, before_image, after_image = _write_texture_fixture_pair(
        fixture_root
    )
    target = RecolorVariantTarget(
        target_id="synthetic-basecolor",
        target_kind="texture_slot",
        game_path="synthetic/fixture_basecolor.dds",
        label="Generated basecolor fixture",
        slot_kind="base",
        texture_type="color",
        semantic_subtype="basecolor",
        editable=True,
        width=640,
        height=480,
        mip_count=1,
        dds_format="Synthetic RGBA preview",
    )
    widget.analysis = RecolorVariantAnalysis(
        package_path="synthetic://compact-visual-fixture",
        package_kind="visual_fixture",
        package_info=ModPackageInfo(title="Synthetic visual fixture"),
        payload_paths=("synthetic/fixture_basecolor.dds",),
        targets=(target,),
    )
    widget.source_path_edit.setText("Synthetic in-memory fixture")
    widget.output_root_edit.setText("Temporary harness output")
    widget._populate_targets_tree()
    widget._refresh_preview_summary()
    widget.current_preview_image = RecolorVariantPreviewImage(
        target_id=target.target_id,
        source_dds_path=before_path,
        source_png=before_path,
        preview_png=after_path,
    )
    widget._set_preview_image(
        widget.preview_source_image_label,
        before_image,
        "Before unavailable",
    )
    widget._set_preview_image(
        widget.preview_result_image_label,
        after_image,
        "After unavailable",
    )
    widget.selected_target_label.setText(
        "Generated basecolor fixture (synthetic, editable preview)"
    )
    widget.summary_label.setText(
        "Synthetic visual fixture: 1 safe in-memory target; no package was opened."
    )
    widget.preview_summary_label.setText(
        "Preview impact: one generated before/after image pair; no files will be built."
    )
    widget.outputs_tree.clear()
    widget.outputs_tree.addTopLevelItem(
        QTreeWidgetItem(["Temporary harness output", "Preview ready", "1 generated target"])
    )
    widget.log_edit.setPlainText(
        "Generated a temporary before/after preview pair.\n"
        "No archive or game data was loaded."
    )
    widget._sync_action_state()
    evidence["generated_preview_pair"] = {
        "before": before_path.name,
        "after": after_path.name,
        "targets": 1,
        "preview_ready": True,
    }


def _install_texture_editor_fixture(
    widget: QWidget,
    fixture_root: Path,
    evidence: dict[str, object],
) -> None:
    if getattr(widget, "document", None) is not None:
        return
    from cdmw.models import TextureEditorSourceBinding

    _before_path, source_path, _before, _after = _write_texture_fixture_pair(
        fixture_root
    )
    widget.open_source_path(
        source_path,
        binding=TextureEditorSourceBinding(
            launch_origin="visual_harness",
            display_name="Synthetic texture fixture",
            source_path="Generated temporary image",
            source_identity_path="compact-visual-fixture",
            relative_path="synthetic/texture-editor-fixture.png",
            package_root="Synthetic fixture",
            texture_type="color",
            semantic_subtype="basecolor",
        ),
    )
    if not _wait_until(lambda: getattr(widget, "document", None) is not None):
        raise RuntimeError("Texture Editor did not open the generated visual fixture PNG.")
    sanitized_binding = dataclasses.replace(
        widget.document.source_binding,
        source_path="Generated temporary image",
        source_identity_path="compact-visual-fixture",
        original_dds_path="",
    )
    widget.document = dataclasses.replace(
        widget.document,
        title="Synthetic texture fixture",
        source_binding=sanitized_binding,
    )
    widget._store_active_session()
    widget._refresh_metadata()
    widget._refresh_canvas_status_strip()
    visible_metadata = widget.metadata_browser.toPlainText()
    if str(fixture_root).casefold() in visible_metadata.casefold():
        raise RuntimeError("Texture Editor exposed the absolute temporary fixture path.")
    evidence["generated_texture"] = {
        "display_name": "Synthetic texture fixture",
        "relative_path": "synthetic/texture-editor-fixture.png",
        "absolute_temp_path_visible": False,
    }


def _install_translation_fixture(widget: QWidget) -> None:
    if getattr(widget, "_catalogue", None) is not None:
        return
    from cdmw.core.paloc_format import LocalizationEntry, LocalizationTable
    from tools.translation_studio.catalogue import TranslationCatalogue

    samples = (
        ("questdialog_main_001", "Du har kommit till rätt person.", "You've come to the right person."),
        ("questdialog_main_002", "Vi kan inte slösa mer tid.", "We cannot waste any more time."),
        ("questdialog_main_003", "Har du några nyheter?", "Do you have any news?"),
        ("questdialog_main_004", "Jag behöver din hjälp.", "I need your help."),
        ("questdialog_main_005", "Förstår du uppdraget?", "Do you understand the mission?"),
        ("questdialog_main_006", "Det här är vårt enda spår.", "This is our only lead."),
        ("questdialog_main_007", "Du måste vara försiktig där ute.", "You must be careful out there."),
        ("questdialog_main_008", "Återvänd när du är redo.", "Return when you are ready."),
        ("questdialog_main_009", "Jag litar på ditt omdöme.", "I trust your judgment."),
        ("questdialog_main_010", "Vi ses vid lägret.", "I will see you at the camp."),
        ("questdialog_main_011", "Lycka till.", "Good luck."),
        ("questdialog_main_012", "Belöningen är din när du är klar.", "Your reward awaits."),
    )
    entries = tuple(
        LocalizationEntry(category=1, key=key_name, text=text)
        for key_name, text, _reference in samples
    )
    catalogue = TranslationCatalogue(
        language="Swedish",
        table=LocalizationTable(entries),
        original=b"",
        reference_language="English",
        reference={key_name: reference for key_name, _text, reference in samples},
    )
    catalogue.set_text(11, "Belöningen väntar när du är klar.")
    widget._catalogue = catalogue
    widget.model.set_catalogue(catalogue)
    widget.language_box.clear()
    widget.language_box.addItem("Swedish")
    widget.reference_box.clear()
    widget.reference_box.addItem("English")
    widget.category_box.clear()
    widget.category_box.addItem("All groups", None)
    widget.category_box.addItem("Quest Dialog", 1)
    for control in (widget.search_box, widget.category_box, widget.edited_only):
        control.setEnabled(True)
    widget.status_label.setText("12 fixture lines loaded.")
    widget.hits_label.setText("12 lines")
    widget.pending_label.setText("1 change")


def _install_placement_fixture(widget: QWidget, fixture_root: Path) -> None:
    if getattr(widget, "_studio", None) is not None:
        return
    install = getattr(widget, "_install", None)
    if callable(install):
        from tools.placement_studio.corpus import Baseline

        install(Baseline(fixture_root / "placement-baseline", {}))


def _install_retrofit_fixture(widget: QWidget) -> None:
    retrofit_ui = getattr(widget, "_retrofit_ui", None)
    source_edit = getattr(retrofit_ui, "source_edit", None)
    output_edit = getattr(retrofit_ui, "output_edit", None)
    if source_edit is not None:
        source_edit.setText("C:/CDMW-Harness/Incoming")
    if output_edit is not None:
        output_edit.setText("C:/CDMW-Harness/Repacked")


def _install_safe_workspace_fixture(
    key: str,
    widget: QWidget,
    fixture_root: Path,
) -> dict[str, object]:
    """Reveal real lazy workspaces without consulting a game installation."""

    evidence: dict[str, object] = {
        "fixture_scope": "synthetic_local_only",
        "no_game_or_archive_data": True,
    }
    if key == "new_item_studio":
        _install_new_item_fixture(widget)
    elif key == "mesh_editor":
        _install_mesh_fixture(widget, evidence)
    elif key == "texture_workflow":
        _install_texture_workflow_fixture(widget)
    elif key == "replace_assistant":
        _install_replace_fixture(widget, fixture_root, evidence)
    elif key == "recolor_variants":
        _install_recolor_fixture(widget, fixture_root, evidence)
    elif key == "texture_editor":
        _install_texture_editor_fixture(widget, fixture_root, evidence)
    elif key == "translation_studio":
        _install_translation_fixture(widget)
    elif key == "placement_studio":
        _install_placement_fixture(widget, fixture_root)
    elif key == "mod_package_retrofit":
        _install_retrofit_fixture(widget)
    return evidence


def _seed_in_memory_rows(widget: QWidget) -> dict[str, int]:
    """Populate empty item-based views for useful, I/O-free geometry captures."""

    tree_rows = 0
    table_rows = 0
    for tree in widget.findChildren(QTreeWidget):
        if tree.topLevelItemCount() or tree.columnCount() <= 0:
            continue
        tree.blockSignals(True)
        try:
            for row_index in range(6):
                values = [
                    f"Fixture {row_index + 1}" if column == 0 else ("Ready" if column == 1 else "—")
                    for column in range(tree.columnCount())
                ]
                tree.addTopLevelItem(QTreeWidgetItem(values))
                tree_rows += 1
        finally:
            tree.blockSignals(False)

    for table in widget.findChildren(QTableWidget):
        if table.rowCount() or table.columnCount() <= 0:
            continue
        table.blockSignals(True)
        try:
            table.setRowCount(6)
            for row_index in range(6):
                for column in range(table.columnCount()):
                    value = f"Fixture {row_index + 1}" if column == 0 else ("Ready" if column == 1 else "—")
                    table.setItem(row_index, column, QTableWidgetItem(value))
                table_rows += 1
        finally:
            table.blockSignals(False)

    for log_view in widget.findChildren(QPlainTextEdit):
        if "log" not in log_view.objectName().casefold() and "log" not in log_view.placeholderText().casefold():
            continue
        if not log_view.toPlainText():
            log_view.setPlainText("Harness fixture ready.\nNo archive or game data was loaded.")
    return {"tree_rows": tree_rows, "table_rows": table_rows}
