"""Helpers for the material sidecar value editor."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.models import ArchiveEntry
from cdmw.services.material_sidecar_preview_service import (
    fast_material_preview_package_from_manifest,
    material_preview_package_matches_entry,
)


def material_editor_color_from_value(value: str) -> Optional[QColor]:
    text = str(value or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", text):
        color = QColor("#" + text.lstrip("#")[:6])
        return color if color.isValid() else None
    numbers: list[float] = []
    for token in re.split(r"[\s,;]+", text):
        try:
            numbers.append(float(token))
        except ValueError:
            continue
        if len(numbers) >= 3:
            break
    if len(numbers) < 3:
        return None
    color = QColor(
        max(0, min(255, round(numbers[0] * 255))),
        max(0, min(255, round(numbers[1] * 255))),
        max(0, min(255, round(numbers[2] * 255))),
    )
    return color if color.isValid() else None


def material_value_swatch_icon(color: QColor, cache: dict[str, QIcon]) -> QIcon:
    key = color.name(QColor.HexRgb)
    cached = cache.get(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#0d1117"), 1))
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(1, 1, 16, 16, 3, 3)
        painter.setPen(QPen(QColor("#d0d7de"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, 16, 16, 3, 3)
    finally:
        painter.end()
    icon = QIcon(pixmap)
    cache[key] = icon
    return icon


def material_preview_entry_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


def selected_value_ready_for_live_refresh(kind_text: str, value_text: str) -> bool:
    value_text = str(value_text or "").strip()
    if not value_text:
        return False
    kind = str(kind_text or "").strip().lower()
    if kind == "float":
        try:
            float(value_text)
        except ValueError:
            return False
        return True
    if kind != "color":
        return False
    if re.fullmatch(r"#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value_text):
        return True
    parts = [part for part in re.split(r"[,\s]+", value_text) if part]
    if len(parts) < 3:
        return False
    try:
        [float(part) for part in parts[:3]]
    except ValueError:
        return False
    return True


def material_sidecar_value_tree_item(row: object) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.group_label,
            row.kind,
            row.parameter_name,
            row.value,
            row.detail,
        ]
    )
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setData(0, Qt.UserRole, row.row_id)
    item.setData(3, Qt.UserRole, row.value)
    item.setToolTip(0, row.group_label)
    item.setToolTip(2, row.parameter_name)
    item.setToolTip(3, row.value)
    item.setToolTip(4, row.detail)
    return item


def material_sidecar_read_failed_status(error: object) -> str:
    return f"Could not read material sidecar: {error}"


def material_sidecar_empty_values_dialog_text() -> tuple[str, str]:
    return (
        "Material Values",
        "No recognized material values were found in this sidecar.",
    )


def material_sidecar_editor_window_title(basename: object) -> str:
    return f"Edit Material Values - {basename}"


def material_sidecar_dialog_size() -> tuple[int, int]:
    return (1460, 760)


def material_sidecar_editor_intro_text() -> str:
    return (
        "Edit recognized values through guided controls. Structural names, shaders, IDs, indexes, raw source, "
        "and connection edges stay locked. Colors also accept comma-separated RGB floats or #RRGGBB. "
        "Undo/reset locally, then export a mod package when ready."
    )


def material_sidecar_preview_warning_text() -> str:
    return (
        "Preview warning: Material Values uses an approximate CDMW preview shader. It cannot exactly match "
        "Crimson Desert's in-game material, lighting, dye, and post-process rendering, so colors shown here "
        "may differ in game. Test the exported mod in game before trusting final colors."
    )


def material_sidecar_tree_headers() -> tuple[str, ...]:
    return ("Part / Material", "Kind", "Parameter", "Value", "Detail")


def material_sidecar_tree_column_widths() -> tuple[int, int, int, int]:
    return (190, 72, 210, 520)


def material_sidecar_preview_color_tooltip(value_text: object, color_name: object) -> str:
    return f"{value_text}\nPreview color: {str(color_name).upper()}"


def material_sidecar_selected_value_label_text() -> str:
    return "Selected value"


def material_sidecar_selected_value_placeholder_text() -> str:
    return "Select a material value row to edit it here."


def material_sidecar_value_edit_tooltip_text() -> str:
    return (
        "The raw value is synchronized with the selected type-specific controls. Colors accept #RRGGBB; "
        "decimal and 0x-prefixed integers are accepted where shown."
    )


def material_sidecar_selected_color_tooltip_text(color_name: object | None = None) -> str:
    if color_name:
        return f"Selected color: {str(color_name).upper()}"
    return "Selected color preview"


def material_sidecar_selected_color_swatch_stylesheet(color_name: object) -> str:
    return (
        "QFrame#SelectedMaterialValueColorSwatch {"
        f"background-color: {color_name};"
        "border: 1px solid #d0d7de;"
        "border-radius: 4px;"
        "}"
    )


def material_sidecar_preview_control_labels() -> tuple[str, str, str, str]:
    return ("Show Preview", "Refresh Preview", "Preview Settings...", "Live Color Preview")


def material_sidecar_preview_settings_tooltip_text() -> str:
    return (
        "Use the same global preview settings as the Archive Preview and Mesh Replacement Alignment previews."
    )


def material_sidecar_skeleton_overlay_label_text() -> str:
    return "Show skeleton overlay"


def material_sidecar_skeleton_overlay_tooltip_text() -> str:
    return (
        "Off by default for PAC XML because related skeleton/HKX data does not affect material values. "
        "Enable it only when rig or deformation context is useful."
    )


def material_sidecar_skeleton_overlay_status_text(enabled: bool) -> str:
    if enabled:
        return "Skeleton overlay will be loaded in the next preview."
    return "Skeleton overlay is off; the next preview will load only material-relevant model data."


def material_sidecar_skeleton_overlay_queued_status() -> str:
    return "Skeleton overlay change queued; the preview will refresh after the current build."


def material_sidecar_initial_preview_status_text() -> str:
    return "Preview has not been built yet."


def material_sidecar_preview_host_minimum_size() -> tuple[int, int]:
    return (420, 300)


def material_sidecar_content_splitter_sizes() -> tuple[int, int]:
    return (850, 560)


def material_sidecar_action_button_labels() -> tuple[str, str, str, str]:
    return ("Pick Color...", "Reset Selected", "Export Edited Material Mod...", "Close")


def material_sidecar_selected_detail_text(group: object, parameter: object, detail: object) -> str:
    return f"Selected: {group} | {parameter} | {detail}"


def material_sidecar_choose_color_dialog_title() -> str:
    return "Choose Material Color"


def material_sidecar_lookup_pending_status() -> str:
    return "Preview model lookup will run after the editor opens."


def material_sidecar_no_preview_model_status() -> str:
    return "No associated .pac, .pam, or .pamlod model was found for this sidecar."


def material_sidecar_preview_model_status(path: object) -> str:
    return f"Associated preview model: {path}"


def material_sidecar_live_preview_scheduled_status() -> str:
    return "Live material preview refresh scheduled..."


def material_sidecar_live_preview_starting_status() -> str:
    return "Live material preview refresh starting..."


def material_sidecar_live_preview_start_failed_status(error: object) -> str:
    return f"Live material preview refresh could not start: {error}"


def material_sidecar_live_preview_waiting_status() -> str:
    return "Preview model lookup is still pending; live preview will be available after lookup finishes."


def material_sidecar_texture_edit_refresh_status() -> str:
    return "Texture path edits refresh when you click Refresh Preview."


def material_sidecar_no_changes_dialog_text() -> tuple[str, str]:
    return ("No Changes", "Change at least one material value before exporting.")


def material_sidecar_edit_failed_dialog_title() -> str:
    return "Material Edit Failed"


def material_sidecar_unexpected_export_payload_status() -> str:
    return "Material mod export finished with an unexpected result payload."


def material_sidecar_export_complete_dialog_text(package_root: object) -> tuple[str, str]:
    return ("Export Complete", f"Exported edited material mod:\n{package_root}")


def material_sidecar_export_complete_status(package_root: object) -> str:
    return f"Exported edited material mod to {package_root}."


def material_sidecar_export_task_status(basename: object) -> str:
    return f"Exporting edited material mod for {basename}..."


def material_sidecar_export_target_title() -> str:
    return "Export Edited Material Mod"


def material_sidecar_preview_process_state() -> dict[str, object]:
    return {
        "process": None,
        "status_file": None,
        "status_signature": (0, 0),
        "status_payload_text": "",
        "summary": "",
    }


def material_sidecar_preview_generation_state() -> dict[str, object]:
    return {"value": 0, "queued_live": False}


def material_sidecar_preview_base_result_state() -> dict[str, object]:
    return {"key": "", "result": None}


def material_sidecar_preview_model_entry_state() -> dict[str, object]:
    return {"entry": None, "resolved": False}


def material_sidecar_selected_value_sync_state() -> dict[str, bool]:
    return {"active": False}


def material_sidecar_row_kind_by_id(rows: Iterable[object]) -> dict[str, str]:
    return {row.row_id: row.kind for row in rows}


def material_sidecar_live_preview_kinds() -> set[str]:
    return {"color", "float"}


def material_sidecar_kind_supports_live_preview(kind_text: object) -> bool:
    return str(kind_text or "").strip().lower() in material_sidecar_live_preview_kinds()


def material_sidecar_live_preview_interval_ms() -> int:
    return 700


def material_sidecar_selected_value_live_refresh_interval_ms() -> int:
    return 750


def material_sidecar_selected_value_sync_interval_ms() -> int:
    return 250


def material_sidecar_preview_status_poll_interval_ms() -> int:
    return 250


def material_sidecar_preview_process_kill_delay_ms() -> int:
    return 750


def material_sidecar_preview_package_cleanup_delay_ms() -> int:
    return 1000


def material_sidecar_initial_lookup_delay_ms() -> int:
    return 0


def material_sidecar_native_loaded_status(
    *,
    batch_count: object,
    vertex_count: object,
    first_frame_ms: object,
    texture_failure_count: object,
) -> str:
    batch_count_value = int(batch_count or 0)
    vertex_count_value = int(vertex_count or 0)
    first_frame_value = float(first_frame_ms or 0.0)
    texture_failure_value = int(texture_failure_count or 0)
    texture_text = (
        "texture failures: none"
        if texture_failure_value <= 0
        else f"texture failures: {texture_failure_value:,}"
    )
    return (
        f".NET/Vortice material preview loaded: {batch_count_value:,} batch(es), "
        f"{vertex_count_value:,} vertices, first frame {first_frame_value:.1f} ms, {texture_text}."
    )


def material_sidecar_preview_payload_status(summary: object, message: object) -> str:
    summary_text = str(summary or "").strip()
    message_text = str(message or "").strip()
    return f"{summary_text}\n{message_text}".strip() if summary_text else message_text


def material_sidecar_native_error_status(message: object = "") -> str:
    return str(message or ".NET/Vortice material preview failed.").strip()


def material_sidecar_package_validation_failed_status(missing_paths: object) -> str:
    paths = tuple(str(path) for path in (missing_paths or ()) if str(path))
    return ".NET/Vortice material preview package validation failed: " + "; ".join(paths[:6])


def material_sidecar_reloading_native_preview_status(summary: object) -> str:
    return material_sidecar_preview_payload_status(summary, "Reloading .NET/Vortice material preview...")


def material_sidecar_native_preview_start_failed_status(error: object) -> str:
    return f".NET/Vortice material preview could not start: {error}"


def material_sidecar_native_preview_stderr_status(chunk: object) -> str:
    return f".NET/Vortice material preview stderr: {str(chunk or '')[-600:]}"


def material_sidecar_native_preview_process_error_status(error_text: object) -> str:
    return f".NET/Vortice material preview process error: {error_text}"


def material_sidecar_native_preview_exited_status(exit_code: object) -> str:
    return f".NET/Vortice material preview exited with code {int(exit_code)}."


def material_sidecar_starting_native_preview_status(summary: object) -> str:
    return material_sidecar_preview_payload_status(summary, "Starting .NET/Vortice material preview...")


def material_sidecar_preview_lookup_pending_status() -> str:
    return "Preview model lookup is still pending."


def material_sidecar_preview_unexpected_entry_status() -> str:
    return "Preview model lookup returned an unexpected entry."


def material_sidecar_preview_blocked_status(error: object) -> str:
    return f"Material edit cannot be previewed yet: {error}"


def material_sidecar_live_preview_queued_status() -> str:
    return "Live material preview refresh queued; current preview build is still running."


def material_sidecar_background_task_busy_status() -> str:
    return "Another background task is still running. Wait for it to finish before refreshing the material preview."


def material_sidecar_building_preview_status() -> str:
    return "Building approximate material preview with DirectXTex/native DDS support..."


def material_sidecar_preview_unexpected_payload_status() -> str:
    return "Material preview finished with an unexpected result payload."


def material_sidecar_no_model_preview_status() -> str:
    return "No model preview available for this material sidecar."


def material_sidecar_preview_task_status(basename: object) -> str:
    return f"Building material preview for {basename}..."


def material_sidecar_reused_package_summary() -> str:
    return (
        "Approximate sidecar preview\n"
        "reused active Archive Preview D3D11 package; no material values changed."
    )


def material_sidecar_cached_geometry_log(path: object) -> str:
    return f"Reusing cached material preview geometry for {path}..."


def material_sidecar_cached_geometry_note() -> str:
    return "Reused cached preview geometry for live material edit."


def material_sidecar_building_model_log(model_path: object, sidecar_path: object) -> str:
    return f"Building material preview for {model_path} from {sidecar_path}..."


def material_sidecar_prepare_failed_message() -> str:
    return "No prepared model preview was produced for the material sidecar."


def _material_sidecar_preview_summary_parts(
    *,
    live: object,
    color_edits_active: object,
    material_effects_active: object = True,
) -> list[str]:
    status_parts = ["Approximate sidecar preview"]
    if live:
        status_parts.append("live color/scalar refresh")
    if color_edits_active:
        status_parts.append("edited material colors shown as solid preview overlay")
    elif material_effects_active:
        status_parts.append("edited scalar material values applied to textured preview")
    return status_parts


def material_sidecar_manifest_update_summary(
    *,
    live: object,
    color_edits_active: object,
    elapsed_ms: object,
    batch_count: object,
    vertex_count: object,
    notes: object,
) -> str:
    status_parts = _material_sidecar_preview_summary_parts(
        live=live,
        color_edits_active=color_edits_active,
    )
    status_parts.append(
        f"manifest updated in {float(elapsed_ms):.1f} ms for "
        f"{int(batch_count):,} batch(es), {int(vertex_count):,} vertices"
    )
    status_parts.extend(str(note) for note in (notes or ()) if str(note or "").strip())
    return "\n".join(status_parts)


def material_sidecar_built_package_summary(
    *,
    live: object,
    color_edits_active: object,
    material_effects_active: object,
    elapsed_ms: object,
    batch_count: object,
    vertex_count: object,
    notes: object,
    warnings: object,
) -> str:
    status_parts = _material_sidecar_preview_summary_parts(
        live=live,
        color_edits_active=color_edits_active,
        material_effects_active=material_effects_active,
    )
    status_parts.append(
        f"package built in {float(elapsed_ms):.1f} ms for "
        f"{int(batch_count):,} batch(es), {int(vertex_count):,} vertices"
    )
    status_parts.extend(str(note) for note in (notes or ()) if str(note or "").strip())
    status_parts.extend(str(warning) for warning in (warnings or ()) if str(warning or "").strip())
    return "\n".join(status_parts)


def material_sidecar_preview_result_summary(
    result_kind: str,
    *,
    live: bool,
    color_edits_active: bool,
    material_effects_active: bool,
    elapsed_ms: float,
    batch_count: int,
    vertex_count: int,
    notes: Iterable[str],
    warnings: Iterable[str],
) -> str:
    if result_kind == "reused":
        return material_sidecar_reused_package_summary()
    if result_kind == "manifest":
        return material_sidecar_manifest_update_summary(
            live=live,
            color_edits_active=color_edits_active,
            elapsed_ms=elapsed_ms,
            batch_count=batch_count,
            vertex_count=vertex_count,
            notes=notes,
        )
    return material_sidecar_built_package_summary(
        live=live,
        color_edits_active=color_edits_active,
        material_effects_active=material_effects_active,
        elapsed_ms=elapsed_ms,
        batch_count=batch_count,
        vertex_count=vertex_count,
        notes=notes,
        warnings=warnings,
    )




__all__ = [
    "fast_material_preview_package_from_manifest",
    "material_sidecar_action_button_labels",
    "material_sidecar_choose_color_dialog_title",
    "material_sidecar_edit_failed_dialog_title",
    "material_sidecar_editor_intro_text",
    "material_sidecar_editor_window_title",
    "material_sidecar_empty_values_dialog_text",
    "material_sidecar_export_complete_dialog_text",
    "material_sidecar_export_complete_status",
    "material_sidecar_export_task_status",
    "material_sidecar_export_target_title",
    "material_sidecar_initial_preview_status_text",
    "material_sidecar_kind_supports_live_preview",
    "material_sidecar_live_preview_kinds",
    "material_sidecar_live_preview_scheduled_status",
    "material_sidecar_live_preview_start_failed_status",
    "material_sidecar_live_preview_starting_status",
    "material_sidecar_live_preview_queued_status",
    "material_sidecar_live_preview_waiting_status",
    "material_sidecar_lookup_pending_status",
    "material_sidecar_no_changes_dialog_text",
    "material_sidecar_background_task_busy_status",
    "material_sidecar_building_preview_status",
    "material_sidecar_building_model_log",
    "material_sidecar_built_package_summary",
    "material_sidecar_cached_geometry_log",
    "material_sidecar_cached_geometry_note",
    "material_sidecar_content_splitter_sizes",
    "material_sidecar_dialog_size",
    "material_sidecar_no_preview_model_status",
    "material_sidecar_no_model_preview_status",
    "material_sidecar_native_error_status",
    "material_sidecar_native_loaded_status",
    "material_sidecar_native_preview_exited_status",
    "material_sidecar_native_preview_process_error_status",
    "material_sidecar_native_preview_start_failed_status",
    "material_sidecar_native_preview_stderr_status",
    "material_sidecar_package_validation_failed_status",
    "material_sidecar_preview_color_tooltip",
    "material_sidecar_preview_control_labels",
    "material_sidecar_preview_blocked_status",
    "material_sidecar_preview_base_result_state",
    "material_sidecar_preview_generation_state",
    "material_sidecar_initial_lookup_delay_ms",
    "material_sidecar_live_preview_interval_ms",
    "material_sidecar_preview_host_minimum_size",
    "material_sidecar_preview_package_cleanup_delay_ms",
    "material_sidecar_preview_process_kill_delay_ms",
    "material_sidecar_preview_process_state",
    "material_sidecar_preview_result_summary",
    "material_sidecar_preview_status_poll_interval_ms",
    "material_sidecar_preview_lookup_pending_status",
    "material_sidecar_preview_model_status",
    "material_sidecar_preview_model_entry_state",
    "material_sidecar_preview_payload_status",
    "material_sidecar_preview_settings_tooltip_text",
    "material_sidecar_skeleton_overlay_label_text",
    "material_sidecar_skeleton_overlay_queued_status",
    "material_sidecar_skeleton_overlay_status_text",
    "material_sidecar_skeleton_overlay_tooltip_text",
    "material_sidecar_preview_task_status",
    "material_sidecar_prepare_failed_message",
    "material_sidecar_reused_package_summary",
    "material_sidecar_manifest_update_summary",
    "material_sidecar_preview_unexpected_entry_status",
    "material_sidecar_preview_unexpected_payload_status",
    "material_sidecar_preview_warning_text",
    "material_sidecar_read_failed_status",
    "material_sidecar_reloading_native_preview_status",
    "material_sidecar_selected_color_swatch_stylesheet",
    "material_sidecar_selected_color_tooltip_text",
    "material_sidecar_selected_detail_text",
    "material_sidecar_selected_value_sync_state",
    "material_sidecar_selected_value_live_refresh_interval_ms",
    "material_sidecar_selected_value_label_text",
    "material_sidecar_selected_value_placeholder_text",
    "material_sidecar_selected_value_sync_interval_ms",
    "material_sidecar_starting_native_preview_status",
    "material_sidecar_row_kind_by_id",
    "material_sidecar_texture_edit_refresh_status",
    "material_sidecar_tree_column_widths",
    "material_sidecar_tree_headers",
    "material_sidecar_unexpected_export_payload_status",
    "material_sidecar_value_tree_item",
    "material_sidecar_value_edit_tooltip_text",
    "material_editor_color_from_value",
    "material_preview_entry_key",
    "material_preview_package_matches_entry",
    "material_value_swatch_icon",
    "selected_value_ready_for_live_refresh",
]
