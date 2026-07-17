from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage, QPainter

from cdmw.ui.archive_browser.static_replacement_custom_icon import (
    CUSTOM_ITEM_ICON_DISABLED_STATUS,
    CUSTOM_ITEM_ICON_NO_SOURCE_EXPORT_MESSAGE,
    CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT,
    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE,
    CUSTOM_ITEM_ICON_NO_TARGET_STATUS,
    custom_item_icon_alignment_generated_path,
    custom_item_icon_apply_control_enabled_state,
    custom_item_icon_apply_setup_state,
    custom_item_icon_control_enabled_state,
    custom_item_icon_control_text,
    custom_item_icon_file_dialog_filter,
    custom_item_icon_generated_apply_state,
    custom_item_icon_generated_output_dir,
    custom_item_icon_generated_status,
    custom_item_icon_generated_stem,
    custom_item_icon_generation_status_message,
    custom_item_icon_maybe_register_generated_icon,
    custom_item_icon_override_spec,
    custom_item_icon_preview_image,
    custom_item_icon_preview_image_from_pixmap,
    custom_item_icon_selected_preview_image,
    custom_item_icon_register_generated_icon,
    custom_item_icon_status_text,
    custom_item_icon_setup_state,
    custom_item_icon_suggested_generated_path,
    custom_item_icon_target_path,
    custom_item_icon_unique_generated_path,
    custom_item_icon_write_failure_message,
)


class WidgetProbe:
    def __init__(self) -> None:
        self.enabled: bool | None = None
        self.text = ""
        self.items: list[tuple[str, object]] = []

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setText(self, text: str) -> None:
        self.text = str(text)

    def addItem(self, text: str, data: object = None) -> None:
        self.items.append((str(text), data))


def test_custom_item_icon_control_text_preserves_setup_copy() -> None:
    text = custom_item_icon_control_text()

    assert text["use_custom_icon"] == "Use custom item icon"
    assert "folder match" in text["use_custom_icon_tooltip"]
    assert text["source_placeholder"] == "Choose an image file or a folder to auto-match"
    assert text["file_button"] == "File..."
    assert text["folder_button"] == "Folder..."
    assert text["library_button"] == "Library..."
    assert text["source_label"] == "Item icon source"
    assert text["target_label"] == "Item icon target"
    assert text["save_generated_to_library"] == "Save generated preview icon to Icon Creator library"
    assert "Mesh Editor metadata" in text["save_generated_to_library_tooltip"]
    assert text["warning_title"] == "Custom Item Icon"
    assert text["choose_file_title"] == "Choose Custom Item Icon"
    assert text["choose_folder_title"] == "Choose Custom Item Icon Folder"
    assert text["generate_preview_button"] == "Generate Icon"
    assert "without gizmo/axis overlays" in text["generate_preview_tooltip"]
    assert text["generate_preview_warning_title"] == "Generate Icon From Preview"
    assert text["generate_preview_not_ready"] == "The replacement preview is not ready to capture yet."


def test_custom_item_icon_setup_and_enabled_state() -> None:
    assert custom_item_icon_setup_state(
        has_target_entries=True,
        has_item_icons_tab=True,
    ) == {
        "save_generated_to_library_enabled": True,
        "custom_icon_checkbox_enabled": True,
        "add_no_target_combo_item": False,
        "no_target_combo_text": CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT,
        "status_text": "",
    }
    assert custom_item_icon_setup_state(
        has_target_entries=False,
        has_item_icons_tab=False,
    ) == {
        "save_generated_to_library_enabled": False,
        "custom_icon_checkbox_enabled": False,
        "add_no_target_combo_item": True,
        "no_target_combo_text": CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT,
        "status_text": "No existing target icon path was resolved for this mesh; custom icon packaging is unavailable.",
    }
    assert custom_item_icon_control_enabled_state(
        checked=True,
        has_target_entries=True,
    ) == {
        "source_edit_enabled": True,
        "file_button_enabled": True,
        "folder_button_enabled": True,
        "library_button_enabled": True,
        "target_combo_enabled": True,
    }
    assert custom_item_icon_control_enabled_state(
        checked=True,
        has_target_entries=False,
    )["source_edit_enabled"] is False
    assert custom_item_icon_control_enabled_state(
        checked=False,
        has_target_entries=True,
    )["target_combo_enabled"] is False

    save_widget = WidgetProbe()
    checkbox = WidgetProbe()
    combo = WidgetProbe()
    status = WidgetProbe()
    custom_item_icon_apply_setup_state(
        custom_item_icon_setup_state(has_target_entries=False, has_item_icons_tab=False),
        save_generated_to_library_widget=save_widget,
        custom_icon_widget=checkbox,
        target_combo_widget=combo,
        status_widget=status,
    )
    assert save_widget.enabled is False
    assert checkbox.enabled is False
    assert combo.items == [(CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT, None)]
    assert status.text == "No existing target icon path was resolved for this mesh; custom icon packaging is unavailable."

    source_edit = WidgetProbe()
    file_button = WidgetProbe()
    folder_button = WidgetProbe()
    library_button = WidgetProbe()
    target_combo = WidgetProbe()
    custom_item_icon_apply_control_enabled_state(
        custom_item_icon_control_enabled_state(checked=True, has_target_entries=True),
        source_edit_widget=source_edit,
        file_button_widget=file_button,
        folder_button_widget=folder_button,
        library_button_widget=library_button,
        target_combo_widget=target_combo,
    )
    assert source_edit.enabled is True
    assert file_button.enabled is True
    assert folder_button.enabled is True
    assert library_button.enabled is True
    assert target_combo.enabled is True


def test_custom_item_icon_generated_apply_state() -> None:
    assert custom_item_icon_generated_apply_state(
        has_target_entries=True,
        checkbox_enabled=True,
        current_target_entry=None,
    ) == {
        "has_target": True,
        "check_custom_icon": True,
        "select_first_target": True,
    }
    assert custom_item_icon_generated_apply_state(
        has_target_entries=True,
        checkbox_enabled=True,
        current_target_entry=object(),
    ) == {
        "has_target": True,
        "check_custom_icon": True,
        "select_first_target": False,
    }
    assert custom_item_icon_generated_apply_state(
        has_target_entries=False,
        checkbox_enabled=True,
        current_target_entry=None,
    ) == {
        "has_target": False,
        "check_custom_icon": False,
        "select_first_target": False,
    }


def test_custom_item_icon_target_path_and_export_errors() -> None:
    assert CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT == "No resolved existing target icon path"
    assert custom_item_icon_target_path(SimpleNamespace(path="ui/itemicon_sword.dds")) == "ui/itemicon_sword.dds"
    assert custom_item_icon_target_path(object()) == ""

    spec, message = custom_item_icon_override_spec(source_text="", target_entry=object())
    assert spec is None
    assert message == CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE

    spec, message = custom_item_icon_override_spec(
        source_text="",
        target_entry=SimpleNamespace(path="ui/itemicon_sword.dds"),
    )
    assert spec is None
    assert message == CUSTOM_ITEM_ICON_NO_SOURCE_EXPORT_MESSAGE


def test_custom_item_icon_file_dialog_filter_lists_supported_sources() -> None:
    file_filter = custom_item_icon_file_dialog_filter()

    assert file_filter.startswith("Icon images (")
    assert "*.png" in file_filter
    assert "*.dds" in file_filter
    assert file_filter.endswith(");;All files (*.*)")


def test_custom_item_icon_override_spec_accepts_file_and_folder(tmp_path) -> None:
    icon_file = tmp_path / "sword.png"
    icon_file.write_bytes(b"not decoded by source chooser")
    target_entry = SimpleNamespace(path="ui/itemicon_sword.dds")

    file_spec, message = custom_item_icon_override_spec(
        source_text=str(icon_file),
        target_entry=target_entry,
        display_name="Sword",
    )
    assert message == ""
    assert file_spec is not None
    assert file_spec.source_path == icon_file
    assert file_spec.target_entry is target_entry
    assert file_spec.target_path == "ui/itemicon_sword.dds"
    assert file_spec.source_mode == "file"

    folder_spec, message = custom_item_icon_override_spec(
        source_text=str(tmp_path),
        target_entry=target_entry,
        related_stems=("sword",),
        display_name="Sword",
    )
    assert message == ""
    assert folder_spec is not None
    assert folder_spec.source_path == icon_file
    assert folder_spec.source_mode == "folder"


def test_custom_item_icon_status_text_preserves_dialog_copy(tmp_path) -> None:
    icon_file = tmp_path / "sword.png"
    icon_file.write_bytes(b"x")
    target_entry = SimpleNamespace(path="ui/itemicon_sword.dds")

    assert (
        custom_item_icon_status_text(
            checked=False,
            target_entry=target_entry,
            source_text=str(icon_file),
        )
        == CUSTOM_ITEM_ICON_DISABLED_STATUS
    )
    assert (
        custom_item_icon_status_text(
            checked=True,
            target_entry=object(),
            source_text=str(icon_file),
        )
        == CUSTOM_ITEM_ICON_NO_TARGET_STATUS
    )
    assert custom_item_icon_status_text(
        checked=True,
        target_entry=target_entry,
        source_text="",
    ) == "Current: ui/itemicon_sword.dds. Source: choose file or folder. Final: fit + pad to existing icon template."
    assert custom_item_icon_status_text(
        checked=True,
        target_entry=target_entry,
        source_text=str(tmp_path / "missing"),
    ) == "Current: ui/itemicon_sword.dds. Source: No supported icon source image matched the selected target icon. Final: unavailable."
    assert custom_item_icon_status_text(
        checked=True,
        target_entry=target_entry,
        source_text=str(tmp_path),
        related_stems=("sword",),
    ) == (
        f"Current: ui/itemicon_sword.dds. Source: {icon_file} (1 candidate(s) scanned). "
        "Final: fit + pad to the target icon size, format, and mip count."
    )


def test_custom_item_icon_generated_status_copy() -> None:
    assert custom_item_icon_generated_status(
        output_name="sword.png",
        saved_to_library=False,
        has_target=True,
    ) == "Generated from replacement preview: sword.png. Final: attached to selected target icon."
    assert custom_item_icon_generated_status(
        output_name="sword.png",
        saved_to_library=True,
        has_target=False,
    ) == (
        "Generated from replacement preview: sword.png. Saved to Icon Creator library. "
        "Final: no resolved target icon path, so export attachment is unavailable."
    )
    assert custom_item_icon_write_failure_message("icons/sword.png") == "Could not write generated icon:\nicons/sword.png"
    assert custom_item_icon_generation_status_message(
        "icons/sword.png"
    ) == "Generated mesh replacement icon: icons/sword.png"


def test_custom_item_icon_generated_path_sanitizes_and_avoids_collisions(tmp_path) -> None:
    assert custom_item_icon_generated_stem("objects/weapons/Two Handed Sword.model") == "Two-Handed-Sword"
    assert custom_item_icon_generated_stem("///") == "mesh-replacement"

    first = custom_item_icon_unique_generated_path(
        tmp_path / "generated_icons",
        target_model_path="objects/weapons/Two Handed Sword.model",
        timestamp="20260613-010203",
    )
    assert first == tmp_path / "generated_icons" / "Two-Handed-Sword-alignment-20260613-010203.png"

    first.write_bytes(b"x")
    second = custom_item_icon_unique_generated_path(
        tmp_path / "generated_icons",
        target_model_path="objects/weapons/Two Handed Sword.model",
        timestamp="20260613-010203",
    )
    assert second == tmp_path / "generated_icons" / "Two-Handed-Sword-alignment-20260613-010203-2.png"


def test_custom_item_icon_generated_output_dir_preserves_fallbacks(tmp_path) -> None:
    model_library = SimpleNamespace(catalogue_dir=lambda: tmp_path / "catalogue")

    assert custom_item_icon_generated_output_dir(
        model_library,
        fallback_dir=tmp_path / "fallback",
    ) == tmp_path / "catalogue" / "generated_icons"
    assert custom_item_icon_generated_output_dir(
        None,
        fallback_dir=tmp_path / "fallback",
    ) == tmp_path / "fallback" / "generated_icons"

    def _raise_catalogue_dir() -> None:
        raise RuntimeError("unavailable")

    assert custom_item_icon_generated_output_dir(
        SimpleNamespace(catalogue_dir=_raise_catalogue_dir),
        fallback_dir=tmp_path / "fallback",
    ) == tmp_path / "fallback" / "generated_icons"


def test_custom_item_icon_alignment_generated_path_prefers_library_path(tmp_path) -> None:
    class ItemIconsTab:
        def mesh_editor_generated_icon_path(self, *, target_model_path: str, source_model_path: str):
            assert target_model_path == "target.model"
            assert source_model_path == "source.obj"
            return tmp_path / "library" / "target.png"

    result = custom_item_icon_alignment_generated_path(
        save_to_library=True,
        item_icons_tab=ItemIconsTab(),
        model_library_tab=object(),
        target_model_path="target.model",
        target_fallback_path="fallback.model",
        source_model_path="source.obj",
        fallback_dir=tmp_path,
    )

    assert result == tmp_path / "library" / "target.png"


def test_custom_item_icon_alignment_generated_path_uses_catalogue_fallback(tmp_path) -> None:
    result = custom_item_icon_alignment_generated_path(
        save_to_library=False,
        item_icons_tab=object(),
        model_library_tab=SimpleNamespace(catalogue_dir=lambda: tmp_path / "catalogue"),
        target_model_path="target.model",
        target_fallback_path="objects/weapons/Two Handed Sword.model",
        source_model_path="source.obj",
        fallback_dir=tmp_path / "fallback",
    )

    assert result.parent == tmp_path / "catalogue" / "generated_icons"
    assert result.name.startswith("Two-Handed-Sword-alignment-")
    assert result.suffix == ".png"


def test_custom_item_icon_preview_image_uses_formatter_when_available() -> None:
    source = QImage(4, 2, QImage.Format.Format_RGBA8888)
    source.fill(QColor(10, 20, 30, 255))
    formatted = QImage(8, 8, QImage.Format.Format_RGBA8888)
    formatted.fill(QColor(200, 100, 50, 255))

    calls = []

    def formatter(image: QImage, *, size: int) -> QImage:
        calls.append((image.size(), size))
        return formatted

    result = custom_item_icon_preview_image(source, formatter=formatter, size=8)

    assert result is formatted
    assert calls == [(source.size(), 8)]


def test_custom_item_icon_preview_image_from_pixmap_uses_pixmap_image() -> None:
    source = QImage(4, 2, QImage.Format.Format_RGBA8888)
    source.fill(QColor(10, 20, 30, 255))
    pixmap = SimpleNamespace(toImage=lambda: source)

    result = custom_item_icon_preview_image_from_pixmap(pixmap, size=8)

    assert result.width() == 8
    assert result.height() == 8


def test_custom_item_icon_preview_image_falls_back_to_square_crop() -> None:
    source = QImage(4, 2, QImage.Format.Format_RGBA8888)
    source.fill(QColor(10, 20, 30, 255))

    def broken_formatter(_image: QImage, *, size: int) -> QImage:
        raise RuntimeError("ignore formatter errors")

    result = custom_item_icon_preview_image(source, formatter=broken_formatter, size=8)

    assert result.width() == 8
    assert result.height() == 8
    assert result.format() == QImage.Format.Format_RGBA8888


def test_custom_item_icon_selected_preview_image_fits_and_pads_without_stretching(
) -> None:
    source = QImage(400, 200, QImage.Format.Format_RGBA8888)
    source.fill(QColor(0, 0, 0, 0))
    painter = QPainter(source)
    painter.fillRect(40, 40, 320, 120, QColor(220, 30, 20, 255))
    painter.end()

    result = custom_item_icon_selected_preview_image(source, (0, 0, 400, 200), size=100)

    assert result.size().width() == 100
    assert result.size().height() == 100
    opaque = [
        (x, y)
        for y in range(result.height())
        for x in range(result.width())
        if result.pixelColor(x, y).alpha() > 127
    ]
    opaque_x = [point[0] for point in opaque]
    opaque_y = [point[1] for point in opaque]
    assert 79 <= max(opaque_x) - min(opaque_x) + 1 <= 82
    assert 29 <= max(opaque_y) - min(opaque_y) + 1 <= 32
    assert result.pixelColor(50, 10).alpha() == 0
    assert result.pixelColor(50, 50).red() > 200


def test_custom_item_icon_selected_preview_image_clamps_and_rejects_empty_regions(
) -> None:
    source = QImage(20, 10, QImage.Format.Format_RGBA8888)
    source.fill(QColor("red"))

    result = custom_item_icon_selected_preview_image(source, (-5, -5, 15, 12), size=16)

    assert result.size().width() == 16
    assert result.size().height() == 16

    try:
        custom_item_icon_selected_preview_image(source, (30, 0, 4, 4), size=16)
    except ValueError as exc:
        assert "selection is empty" in str(exc)
    else:
        raise AssertionError("Expected an out-of-bounds icon selection to be rejected.")


def test_custom_item_icon_suggested_generated_path_uses_item_icon_tab(tmp_path) -> None:
    class ItemIconsTab:
        def mesh_editor_generated_icon_path(self, *, target_model_path: str, source_model_path: str):
            assert target_model_path == "target.model"
            assert source_model_path == "source.obj"
            return tmp_path / "library" / "target.png"

    assert custom_item_icon_suggested_generated_path(
        ItemIconsTab(),
        target_model_path="target.model",
        source_model_path="source.obj",
    ) == tmp_path / "library" / "target.png"
    assert custom_item_icon_suggested_generated_path(
        object(),
        target_model_path="target.model",
        source_model_path="source.obj",
    ) is None


def test_custom_item_icon_register_generated_icon_returns_saved_path(tmp_path) -> None:
    output_path = tmp_path / "generated.png"
    stored_path = tmp_path / "library" / "generated.png"
    calls = []

    class ItemIconsTab:
        def register_mesh_editor_generated_icon(self, path, **kwargs):
            calls.append((path, kwargs))
            return stored_path

    result = custom_item_icon_register_generated_icon(
        ItemIconsTab(),
        output_path,
        target_model_path="target.model",
        source_model_path="source.obj",
        target_icon_entry=SimpleNamespace(path="ui/itemicon_target.dds"),
    )

    assert result.output_path == stored_path
    assert result.saved_to_library is True
    assert result.error_status == ""
    assert calls == [
        (
            output_path,
            {
                "target_model_path": "target.model",
                "source_model_path": "source.obj",
                "target_icon_path": "ui/itemicon_target.dds",
                "select": False,
            },
        )
    ]


def test_custom_item_icon_maybe_register_generated_icon_skips_when_disabled(tmp_path) -> None:
    output_path = tmp_path / "generated.png"

    result = custom_item_icon_maybe_register_generated_icon(
        save_to_library=False,
        item_icons_tab=object(),
        output_path=output_path,
        target_model_path="target.model",
        source_model_path="source.obj",
        target_icon_entry=object(),
    )

    assert result.output_path == output_path
    assert result.saved_to_library is False
    assert result.error_status == ""


def test_custom_item_icon_maybe_register_generated_icon_uses_library_when_enabled(tmp_path) -> None:
    output_path = tmp_path / "generated.png"
    stored_path = tmp_path / "library" / "generated.png"

    class ItemIconsTab:
        def register_mesh_editor_generated_icon(self, *_args, **_kwargs):
            return stored_path

    result = custom_item_icon_maybe_register_generated_icon(
        save_to_library=True,
        item_icons_tab=ItemIconsTab(),
        output_path=output_path,
        target_model_path="target.model",
        source_model_path="source.obj",
        target_icon_entry=SimpleNamespace(path="ui/itemicon_target.dds"),
    )

    assert result.output_path == stored_path
    assert result.saved_to_library is True
    assert result.error_status == ""


def test_custom_item_icon_register_generated_icon_reports_errors(tmp_path) -> None:
    output_path = tmp_path / "generated.png"

    class ItemIconsTab:
        def register_mesh_editor_generated_icon(self, *_args, **_kwargs):
            raise RuntimeError("library locked")

    result = custom_item_icon_register_generated_icon(
        ItemIconsTab(),
        output_path,
        target_model_path="target.model",
        source_model_path="source.obj",
        target_icon_entry=object(),
    )

    assert result.output_path == output_path
    assert result.saved_to_library is False
    assert result.error_status == "Generated icon could not be saved to Icon Creator library: library locked"
