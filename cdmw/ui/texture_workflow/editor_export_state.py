from __future__ import annotations

"""Export path and document-output state rules for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding
from cdmw.services.texture_editor_service import TextureEditorService


@dataclass(frozen=True, slots=True)
class TextureEditorHandoffDeliveryState:
    target: str
    output_path: Path
    source_binding: TextureEditorSourceBinding
    emit_replace_assistant: bool
    emit_texture_workflow: bool
    emit_item_icons: bool
    status_text: str


def texture_editor_default_workspace_root(base_dir: Path) -> Path:
    return TextureEditorService.make_workspace_root(base_dir)


def texture_editor_selection_region_default_path(
    document: TextureEditorDocument,
    last_save_dir: str,
) -> Path:
    return (Path(last_save_dir) / f"{document.title}_selection.png").resolve()


def texture_editor_selection_region_missing_status_text() -> str:
    return "Create a selection first, then use Export Selection Region."


def texture_editor_selection_region_status_text(output_path: Path) -> str:
    return f"Exported selection region to {Path(output_path).name}."


def texture_editor_selection_region_task_label() -> str:
    return "Exporting selection region PNG..."


def texture_editor_grid_slices_status_text(output_dir: Path, count: int) -> str:
    return f"Exported {int(count)} grid slice(s) to {Path(output_dir).name}."


def texture_editor_grid_slices_task_label() -> str:
    return "Exporting atlas grid slices..."


def texture_editor_project_default_path(
    document: TextureEditorDocument,
    last_save_dir: str,
) -> Path:
    return document.project_path or (Path(last_save_dir) / f"{document.title}.ctfedit.json")


def texture_editor_flattened_png_default_path(
    document: TextureEditorDocument,
    last_save_dir: str,
) -> Path:
    return Path(last_save_dir) / f"{document.title}.png"


def texture_editor_dds_default_path(
    document: TextureEditorDocument,
    last_save_dir: str,
) -> Path:
    return Path(last_save_dir) / f"{document.title}.dds"


def texture_editor_compressed_preview_dds_path(
    document: TextureEditorDocument,
    fallback_workspace_root: Path,
    preset_key: str,
) -> Path:
    safe_preset = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(preset_key or "preset"))
    safe_title = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(document.title or "texture_editor"))
    return texture_editor_workspace_exports_root(document, fallback_workspace_root) / "native_previews" / f"{safe_title}_{safe_preset}.dds"


def texture_editor_workspace_exports_root(
    document: TextureEditorDocument,
    fallback_workspace_root: Path,
) -> Path:
    return (document.workspace_root or fallback_workspace_root) / "exports"


def texture_editor_workspace_png_stem(
    document: Optional[TextureEditorDocument],
    suffix: str,
) -> str:
    if document is None:
        return f"texture_editor_{suffix}"
    if suffix == "replace_assistant":
        binding = document.source_binding
        for candidate in (
            binding.archive_relative_path,
            binding.relative_path,
            binding.source_path,
            document.title,
        ):
            candidate_text = str(candidate or "").strip()
            if not candidate_text:
                continue
            stem = Path(PurePosixPath(candidate_text)).stem.strip()
            if stem:
                return stem
    return f"{document.title}_{suffix}"


def texture_editor_workspace_png_path(
    document: TextureEditorDocument,
    fallback_workspace_root: Path,
    suffix: str,
) -> Path:
    return texture_editor_workspace_exports_root(document, fallback_workspace_root) / f"{texture_editor_workspace_png_stem(document, suffix)}.png"


def texture_editor_document_with_last_flattened_output(
    document: TextureEditorDocument,
    output_path: Path,
) -> TextureEditorDocument:
    return dataclasses.replace(document, last_flattened_png_path=str(output_path))


def texture_editor_existing_project_status_text(project_path: Path) -> str:
    return f"Project {Path(project_path).name} is already open."


def texture_editor_open_project_history_label() -> str:
    return "Open Project"


def texture_editor_open_project_status_text(project_path: Path) -> str:
    return f"Opened project {Path(project_path).name}."


def texture_editor_open_project_task_label(project_path: Path) -> str:
    return f"Opening project {Path(project_path).name}..."


def texture_editor_save_project_status_text(project_path: Path) -> str:
    return f"Saved project to {project_path}."


def texture_editor_save_project_task_label(project_path: Path) -> str:
    return f"Saving project {Path(project_path).name}..."


def texture_editor_flattened_png_status_text(output_path: Path) -> str:
    return f"Saved flattened PNG to {output_path}."


def texture_editor_flattened_png_task_label(output_path: Path) -> str:
    return f"Saving flattened PNG to {Path(output_path).name}..."


def texture_editor_native_dds_status_text(output_path: Path, report: object) -> str:
    report_map = report if isinstance(report, dict) else {}
    fmt = str(report_map.get("format") or report_map.get("actual_dxgi_format") or "DDS")
    mip_count = int(report_map.get("mip_count") or 0)
    size = int(report_map.get("output_byte_size") or 0)
    size_text = f", {size:,} bytes" if size > 0 else ""
    mip_text = f", {mip_count} mip(s)" if mip_count > 0 else ""
    return f"Exported native DDS {Path(output_path).name}: {fmt}{mip_text}{size_text}."


def texture_editor_native_dds_task_label(output_path: Path) -> str:
    return f"Exporting native DDS to {Path(output_path).name}..."


def texture_editor_compressed_preview_status_text(preview_path: Path, report: object) -> str:
    report_map = report if isinstance(report, dict) else {}
    fmt = str(report_map.get("format") or report_map.get("actual_dxgi_format") or "DDS")
    return f"Compressed preview ready: {fmt} from {Path(preview_path).name}."


def texture_editor_compressed_preview_task_label() -> str:
    return "Previewing compressed DDS..."


def texture_editor_workspace_export_task_label(suffix: str) -> str:
    return f"Exporting {str(suffix).replace('_', ' ')} PNG..."


def texture_editor_handoff_source_binding(
    document: TextureEditorDocument,
    *,
    mesh_commit_mode: str = "",
) -> TextureEditorSourceBinding:
    binding = dataclasses.replace(document.source_binding)
    if binding.launch_origin == "mesh_editor" and mesh_commit_mode:
        binding.mesh_commit_mode = str(mesh_commit_mode)
    return binding


def texture_editor_native_dds_action_text(document: Optional[TextureEditorDocument]) -> str:
    if document is not None and document.source_binding.launch_origin == "mesh_editor":
        return "Assign DDS..."
    return "Export DDS..."


def texture_editor_handoff_export_suffix(target: str) -> str:
    suffixes = {
        "replace_assistant": "replace_assistant",
        "texture_workflow": "texture_workflow",
        "item_icons": "item_icons",
    }
    return suffixes.get(str(target or ""), str(target or ""))


def texture_editor_handoff_status_text(target: str, output_path: Path) -> str:
    output_name = Path(output_path).name
    messages = {
        "replace_assistant": f"Sent flattened PNG to Texture Replacer: {output_name}",
        "texture_workflow": f"Preparing Texture Workflow handoff: {output_name}",
        "item_icons": f"Sent flattened PNG to Icon Creator: {output_name}",
    }
    return messages.get(str(target or ""), f"Exported flattened PNG: {output_name}")


def texture_editor_handoff_delivery_state(
    target: str,
    output_path: Path,
    source_binding: TextureEditorSourceBinding,
) -> TextureEditorHandoffDeliveryState:
    target_key = str(target or "")
    return TextureEditorHandoffDeliveryState(
        target=target_key,
        output_path=Path(output_path),
        source_binding=source_binding,
        emit_replace_assistant=target_key == "replace_assistant",
        emit_texture_workflow=target_key == "texture_workflow",
        emit_item_icons=target_key == "item_icons",
        status_text=texture_editor_handoff_status_text(target_key, output_path),
    )
