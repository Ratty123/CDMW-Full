"""Custom item icon helpers for static mesh replacement dialogs."""

from __future__ import annotations

import re
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.item_icons import ITEM_ICON_SOURCE_EXTENSIONS, ItemIconOverrideSpec
from cdmw.services.atomic_file_service import atomic_publish_files
from cdmw.services.item_icon_service import ItemIconService


_ITEM_ICON_SERVICE = ItemIconService()


CUSTOM_ITEM_ICON_DISABLED_STATUS = "Custom item icon disabled."
CUSTOM_ITEM_ICON_NO_TARGET_STATUS = "Current: no existing target icon path. Source: not used. Final: unavailable."
CUSTOM_ITEM_ICON_NO_TARGET_SETUP_STATUS = (
    "No existing target icon path was resolved for this mesh; custom icon packaging is unavailable."
)
CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT = "No resolved existing target icon path"
CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE = "Choose an existing resolved target icon path before building a custom item icon."
CUSTOM_ITEM_ICON_NO_SOURCE_EXPORT_MESSAGE = "Choose a custom icon source file or folder."


@dataclass(frozen=True, slots=True)
class CustomItemIconRegistrationResult:
    output_path: Path
    saved_to_library: bool = False
    error_status: str = ""


def custom_item_icon_control_text() -> dict[str, str]:
    return {
        "use_custom_icon": "Use custom item icon",
        "use_custom_icon_tooltip": (
            "Generate an inventory/UI icon from a selected image file or from a folder match. "
            "The output is written only to an existing resolved target icon path."
        ),
        "source_placeholder": "Choose an image file or a folder to auto-match",
        "file_button": "File...",
        "folder_button": "Folder...",
        "library_button": "Library...",
        "source_label": "Item icon source",
        "target_label": "Item icon target",
        "save_generated_to_library": "Save generated preview icon to Icon Creator library",
        "save_generated_to_library_tooltip": (
            "Optional. When Generate Icon is used, also keep the PNG in workspace/libraries/item_icons/edited "
            "with Mesh Editor metadata for the target and source model."
        ),
        "warning_title": "Custom Item Icon",
        "choose_file_title": "Choose Custom Item Icon",
        "choose_folder_title": "Choose Custom Item Icon Folder",
        "generate_preview_button": "Generate Icon",
        "generate_preview_tooltip": (
            "Generate Icon From Preview: capture the replacement preview without gizmo/axis overlays, "
            "then drag a rectangle around the area to use as this replacement's custom item icon."
        ),
        "generate_preview_warning_title": "Generate Icon From Preview",
        "generate_preview_not_ready": "The replacement preview is not ready to capture yet.",
    }


def custom_item_icon_setup_state(
    *,
    has_target_entries: bool,
    has_item_icons_tab: bool,
) -> dict[str, object]:
    return {
        "save_generated_to_library_enabled": bool(has_item_icons_tab),
        "custom_icon_checkbox_enabled": bool(has_target_entries),
        "add_no_target_combo_item": not bool(has_target_entries),
        "no_target_combo_text": CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT,
        "status_text": "" if has_target_entries else CUSTOM_ITEM_ICON_NO_TARGET_SETUP_STATUS,
    }


def _set_widget_enabled(widget: object, enabled: bool) -> None:
    if hasattr(widget, "setEnabled"):
        widget.setEnabled(bool(enabled))


def _set_widget_text(widget: object, text: object) -> None:
    if hasattr(widget, "setText"):
        widget.setText(str(text))


def custom_item_icon_apply_setup_state(
    state: Mapping[str, object],
    *,
    save_generated_to_library_widget: object,
    custom_icon_widget: object,
    target_combo_widget: object,
    status_widget: object,
) -> None:
    _set_widget_enabled(
        save_generated_to_library_widget,
        bool(state.get("save_generated_to_library_enabled")),
    )
    if state.get("add_no_target_combo_item") and hasattr(target_combo_widget, "addItem"):
        _set_widget_enabled(custom_icon_widget, bool(state.get("custom_icon_checkbox_enabled")))
        target_combo_widget.addItem(str(state.get("no_target_combo_text", "")), None)
        _set_widget_text(status_widget, state.get("status_text", ""))


def custom_item_icon_control_enabled_state(
    *,
    checked: bool,
    has_target_entries: bool,
) -> dict[str, bool]:
    controls_enabled = bool(checked and has_target_entries)
    return {
        "source_edit_enabled": controls_enabled,
        "file_button_enabled": controls_enabled,
        "folder_button_enabled": controls_enabled,
        "library_button_enabled": controls_enabled,
        "target_combo_enabled": controls_enabled,
    }


def custom_item_icon_apply_control_enabled_state(
    state: Mapping[str, object],
    *,
    source_edit_widget: object,
    file_button_widget: object,
    folder_button_widget: object,
    library_button_widget: object,
    target_combo_widget: object,
) -> None:
    _set_widget_enabled(source_edit_widget, bool(state.get("source_edit_enabled")))
    _set_widget_enabled(file_button_widget, bool(state.get("file_button_enabled")))
    _set_widget_enabled(folder_button_widget, bool(state.get("folder_button_enabled")))
    _set_widget_enabled(library_button_widget, bool(state.get("library_button_enabled")))
    _set_widget_enabled(target_combo_widget, bool(state.get("target_combo_enabled")))


def custom_item_icon_generated_apply_state(
    *,
    has_target_entries: bool,
    checkbox_enabled: bool,
    current_target_entry: object,
) -> dict[str, bool]:
    has_available_target = bool(has_target_entries and checkbox_enabled)
    return {
        "has_target": has_available_target,
        "check_custom_icon": has_available_target,
        "select_first_target": bool(has_available_target and current_target_entry is None),
    }


def custom_item_icon_file_dialog_filter() -> str:
    suffixes = " ".join(f"*{suffix}" for suffix in sorted(ITEM_ICON_SOURCE_EXTENSIONS))
    return f"Icon images ({suffixes});;All files (*.*)"


def custom_item_icon_target_path(target_entry: object) -> str:
    return str(getattr(target_entry, "path", "") or "")


def custom_item_icon_override_spec(
    *,
    source_text: str,
    target_entry: object,
    related_stems: Sequence[str] = (),
    display_name: str = "",
) -> tuple[Optional[ItemIconOverrideSpec], str]:
    target_path = custom_item_icon_target_path(target_entry)
    if not target_path:
        return None, CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE

    source_value = str(source_text or "").strip()
    if not source_value:
        return None, CUSTOM_ITEM_ICON_NO_SOURCE_EXPORT_MESSAGE

    source_root = Path(source_value).expanduser()
    chosen, _candidates, message = _ITEM_ICON_SERVICE.choose_source(
        source_root,
        target_path=target_path,
        related_stems=related_stems,
        display_name=display_name,
    )
    if chosen is None:
        return None, message

    return (
        ItemIconOverrideSpec(
            source_path=chosen.path,
            target_entry=target_entry,
            target_path=target_path,
            source_mode="folder" if source_root.is_dir() else "file",
        ),
        "",
    )


def custom_item_icon_status_text(
    *,
    checked: bool,
    target_entry: object,
    source_text: str,
    related_stems: Sequence[str] = (),
    display_name: str = "",
) -> str:
    if not checked:
        return CUSTOM_ITEM_ICON_DISABLED_STATUS

    target_path = custom_item_icon_target_path(target_entry)
    if not target_path:
        return CUSTOM_ITEM_ICON_NO_TARGET_STATUS

    source_value = str(source_text or "").strip()
    if not source_value:
        return f"Current: {target_path}. Source: choose file or folder. Final: fit + pad to existing icon template."

    source_root = Path(source_value).expanduser()
    chosen, candidates, message = _ITEM_ICON_SERVICE.choose_source(
        source_root,
        target_path=target_path,
        related_stems=related_stems,
        display_name=display_name,
    )
    if chosen is None:
        return f"Current: {target_path}. Source: {message} Final: unavailable."

    extra = f" ({len(candidates):,} candidate(s) scanned)" if source_root.is_dir() else ""
    return (
        f"Current: {target_path}. Source: {chosen.path}{extra}. "
        "Final: fit + pad to the target icon size, format, and mip count."
    )


def custom_item_icon_generated_status(
    *,
    output_name: str,
    saved_to_library: bool,
    has_target: bool,
) -> str:
    library_note = " Saved to Icon Creator library." if saved_to_library else ""
    if has_target:
        return f"Generated from replacement preview: {output_name}.{library_note} Final: attached to selected target icon."
    return (
        f"Generated from replacement preview: {output_name}.{library_note} "
        "Final: no resolved target icon path, so export attachment is unavailable."
    )


def custom_item_icon_write_failure_message(output_path: object) -> str:
    return f"Could not write generated icon:\n{output_path}"


def custom_item_icon_generation_status_message(output_path: object) -> str:
    return f"Generated mesh replacement icon: {output_path}"


def custom_item_icon_generated_stem(target_model_path: object) -> str:
    stem = PurePosixPath(str(target_model_path or "")).stem
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "mesh-replacement"


def custom_item_icon_unique_generated_path(
    output_dir: Path,
    *,
    target_model_path: object,
    timestamp: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target_stem = custom_item_icon_generated_stem(target_model_path)
    generated_at = timestamp or time.strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"{target_stem}-alignment-{generated_at}.png"
    counter = 1
    while output_path.exists():
        counter += 1
        output_path = output_dir / f"{target_stem}-alignment-{generated_at}-{counter}.png"
    return output_path


def custom_item_icon_suggested_generated_path(
    item_icons_tab: object,
    *,
    target_model_path: str,
    source_model_path: str,
) -> Optional[Path]:
    suggested_path = getattr(item_icons_tab, "mesh_editor_generated_icon_path", None)
    if not callable(suggested_path):
        return None
    try:
        return Path(
            suggested_path(
                target_model_path=target_model_path,
                source_model_path=source_model_path,
            )
        )
    except Exception:
        return None


def custom_item_icon_generated_output_dir(
    model_library_tab: object,
    *,
    fallback_dir: Path,
) -> Path:
    try:
        if model_library_tab is not None:
            return model_library_tab.catalogue_dir() / "generated_icons"
    except Exception:
        pass
    return fallback_dir / "generated_icons"


def custom_item_icon_alignment_generated_path(
    *,
    save_to_library: bool,
    item_icons_tab: object,
    model_library_tab: object,
    target_model_path: str,
    target_fallback_path: str,
    source_model_path: str,
    fallback_dir: Path,
) -> Path:
    if save_to_library:
        suggested_path = custom_item_icon_suggested_generated_path(
            item_icons_tab,
            target_model_path=target_model_path,
            source_model_path=source_model_path,
        )
        if suggested_path is not None:
            return suggested_path
    output_dir = custom_item_icon_generated_output_dir(model_library_tab, fallback_dir=fallback_dir)
    return custom_item_icon_unique_generated_path(output_dir, target_model_path=target_fallback_path)


def custom_item_icon_register_generated_icon(
    item_icons_tab: object,
    output_path: Path,
    *,
    target_model_path: str,
    source_model_path: str,
    target_icon_entry: object,
) -> CustomItemIconRegistrationResult:
    register_generated_icon = getattr(item_icons_tab, "register_mesh_editor_generated_icon", None)
    if not callable(register_generated_icon):
        return CustomItemIconRegistrationResult(output_path=output_path)
    try:
        stored_path = register_generated_icon(
            output_path,
            target_model_path=target_model_path,
            source_model_path=source_model_path,
            target_icon_path=custom_item_icon_target_path(target_icon_entry),
            select=False,
        )
    except Exception as exc:
        return CustomItemIconRegistrationResult(
            output_path=output_path,
            error_status=f"Generated icon could not be saved to Icon Creator library: {exc}",
        )
    return CustomItemIconRegistrationResult(output_path=Path(stored_path), saved_to_library=True)


def custom_item_icon_maybe_register_generated_icon(
    *,
    save_to_library: bool,
    item_icons_tab: object,
    output_path: Path,
    target_model_path: str,
    source_model_path: str,
    target_icon_entry: object,
) -> CustomItemIconRegistrationResult:
    if not save_to_library:
        return CustomItemIconRegistrationResult(output_path=output_path)
    return custom_item_icon_register_generated_icon(
        item_icons_tab,
        output_path,
        target_model_path=target_model_path,
        source_model_path=source_model_path,
        target_icon_entry=target_icon_entry,
    )


def custom_item_icon_preview_image(
    image: QImage,
    *,
    formatter: Callable[..., QImage] | None = None,
    size: int = 512,
) -> QImage:
    if callable(formatter):
        try:
            return formatter(image, size=size)
        except Exception:
            pass
    output_size = max(1, int(size))
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    scaled = source.scaled(output_size, output_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - output_size) // 2)
    y = max(0, (scaled.height() - output_size) // 2)
    return scaled.copy(x, y, min(output_size, scaled.width()), min(output_size, scaled.height()))


def custom_item_icon_selected_preview_image(
    image: QImage,
    selection: tuple[int, int, int, int],
    *,
    size: int = 512,
) -> QImage:
    """Crop a chosen source region, then fit and pad it without stretching."""

    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("generated item icon image is empty")
    x, y, width, height = (int(value) for value in selection)
    left = min(max(0, x), image.width())
    top = min(max(0, y), image.height())
    right = min(max(left, x + width), image.width())
    bottom = min(max(top, y + height), image.height())
    if right <= left or bottom <= top:
        raise ValueError("generated item icon selection is empty")

    output_size = max(1, int(size))
    full_source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    background = full_source.pixelColor(0, 0)
    source = full_source.copy(
        left,
        top,
        right - left,
        bottom - top,
    )
    scaled = source.scaled(
        output_size,
        output_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    output = QImage(output_size, output_size, QImage.Format.Format_RGBA8888)
    output.fill(background)
    painter = QPainter(output)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(
            (output_size - scaled.width()) // 2,
            (output_size - scaled.height()) // 2,
            scaled,
        )
    finally:
        painter.end()
    return output


def custom_item_icon_preview_image_from_pixmap(
    pixmap: object,
    *,
    formatter: Callable[..., QImage] | None = None,
    size: int = 512,
) -> QImage:
    return custom_item_icon_preview_image(pixmap.toImage(), formatter=formatter, size=size)


def write_custom_item_icon_image_atomic(
    image: QImage,
    output_path: Path | str,
    *,
    stop_event: object = None,
) -> Path:
    """Encode a detached image and publish it only after cancellation checks."""

    if image.isNull():
        raise ValueError("generated item icon image is empty")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        raise_if_cancelled(stop_event, "Generated item icon save cancelled.")
        if not image.save(str(staging), "PNG"):
            raise OSError(f"could not encode generated item icon: {target}")
        with staging.open("rb+") as handle:
            os.fsync(handle.fileno())
        raise_if_cancelled(stop_event, "Generated item icon save cancelled.")
        atomic_publish_files({staging: target})
        return target
    finally:
        staging.unlink(missing_ok=True)


__all__ = [
    "CUSTOM_ITEM_ICON_DISABLED_STATUS",
    "CUSTOM_ITEM_ICON_NO_SOURCE_EXPORT_MESSAGE",
    "CUSTOM_ITEM_ICON_NO_TARGET_COMBO_TEXT",
    "CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE",
    "CUSTOM_ITEM_ICON_NO_TARGET_SETUP_STATUS",
    "CUSTOM_ITEM_ICON_NO_TARGET_STATUS",
    "CustomItemIconRegistrationResult",
    "custom_item_icon_alignment_generated_path",
    "custom_item_icon_apply_control_enabled_state",
    "custom_item_icon_apply_setup_state",
    "custom_item_icon_control_enabled_state",
    "custom_item_icon_control_text",
    "custom_item_icon_file_dialog_filter",
    "custom_item_icon_generated_apply_state",
    "custom_item_icon_generated_status",
    "custom_item_icon_generated_stem",
    "custom_item_icon_generated_output_dir",
    "custom_item_icon_generation_status_message",
    "custom_item_icon_maybe_register_generated_icon",
    "custom_item_icon_override_spec",
    "custom_item_icon_preview_image",
    "custom_item_icon_preview_image_from_pixmap",
    "custom_item_icon_selected_preview_image",
    "custom_item_icon_register_generated_icon",
    "custom_item_icon_status_text",
    "custom_item_icon_setup_state",
    "custom_item_icon_suggested_generated_path",
    "custom_item_icon_target_path",
    "custom_item_icon_unique_generated_path",
    "custom_item_icon_write_failure_message",
    "write_custom_item_icon_image_atomic",
]
