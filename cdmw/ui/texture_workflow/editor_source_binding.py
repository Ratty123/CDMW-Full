from __future__ import annotations

"""Source-binding and metadata display rules for the standalone Texture Editor UI."""

import dataclasses
import html
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding


@dataclasses.dataclass(frozen=True, slots=True)
class TextureEditorCompareRequestState:
    can_request: bool
    relative_path: str
    binding: Optional[TextureEditorSourceBinding]
    status_text: str
    error: bool


@dataclasses.dataclass(frozen=True, slots=True)
class TextureEditorMetadataDisplayState:
    html: str
    warning_text: str
    warning_visible: bool


def configured_texture_editor_root_path(getter: Callable[[], object]) -> Optional[Path]:
    try:
        raw = str(getter()).strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def build_texture_editor_source_binding(
    source_path: Path,
    *,
    launch_origin: str,
    binding: Optional[TextureEditorSourceBinding] = None,
    png_root: Optional[Path] = None,
    original_root: Optional[Path] = None,
) -> TextureEditorSourceBinding:
    resolved = source_path.expanduser().resolve()
    source_binding = dataclasses.replace(binding) if binding is not None else TextureEditorSourceBinding()
    if not source_binding.launch_origin:
        source_binding.launch_origin = launch_origin
    if not source_binding.display_name:
        source_binding.display_name = resolved.name
    if not source_binding.source_path:
        source_binding.source_path = str(resolved)
    if not source_binding.source_identity_path:
        source_binding.source_identity_path = source_binding.source_path

    if not source_binding.relative_path or not source_binding.package_root:
        inferred_relative = ""
        inferred_package = ""
        inferred_archive_relative = ""
        for root in (png_root, original_root):
            if root is None:
                continue
            try:
                relative = resolved.relative_to(root)
            except Exception:
                continue
            inferred_relative = PurePosixPath(relative.as_posix()).as_posix()
            parts = [part for part in PurePosixPath(inferred_relative).parts if part]
            if parts:
                inferred_package = parts[0]
                inferred_archive_relative = PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else ""
            break
        if not inferred_relative:
            parts = list(PurePosixPath(resolved.as_posix()).parts)
            package_index = next((idx for idx, part in enumerate(parts) if len(part) == 4 and part.isdigit()), -1)
            if package_index >= 0 and package_index + 1 < len(parts):
                inferred_relative = PurePosixPath(*parts[package_index:]).as_posix()
                inferred_package = parts[package_index]
                inferred_archive_relative = (
                    PurePosixPath(*parts[package_index + 1:]).as_posix()
                    if package_index + 1 < len(parts)
                    else ""
                )
        if inferred_relative and not source_binding.relative_path:
            source_binding.relative_path = inferred_relative
        if inferred_package and not source_binding.package_root:
            source_binding.package_root = inferred_package
        if inferred_archive_relative and not source_binding.archive_relative_path:
            source_binding.archive_relative_path = inferred_archive_relative

    if not source_binding.original_dds_path:
        if resolved.suffix.lower() == ".dds":
            source_binding.original_dds_path = str(resolved)
        elif original_root is not None and source_binding.relative_path:
            candidate = (original_root / Path(PurePosixPath(source_binding.relative_path))).with_suffix(".dds")
            if candidate.exists():
                source_binding.original_dds_path = str(candidate)
        else:
            sibling_dds = resolved.with_suffix(".dds")
            if sibling_dds.exists():
                source_binding.original_dds_path = str(sibling_dds)
    return source_binding


def texture_editor_combined_warning(document_warning: str, ui_constraint_warning: str) -> str:
    return "\n".join(part for part in [document_warning, ui_constraint_warning] if part).strip()


def texture_editor_browse_archive_request_path(document: Optional[TextureEditorDocument]) -> str:
    if document is None:
        return ""
    binding = document.source_binding
    archive_path = (binding.archive_relative_path or "").strip()
    if archive_path or not binding.relative_path or not binding.package_root:
        return archive_path
    relative_parts = [part for part in PurePosixPath(binding.relative_path).parts if part]
    if len(relative_parts) > 1 and relative_parts[0] == binding.package_root:
        return PurePosixPath(*relative_parts[1:]).as_posix()
    return ""


def texture_editor_existing_source_status_text(source_path: Path) -> str:
    return f"{Path(source_path).name} is already open in Texture Editor."


def texture_editor_open_source_history_label() -> str:
    return "Open Document"


def texture_editor_open_source_status_text(source_path: Path) -> str:
    return f"Opened {Path(source_path).name} in Texture Editor."


def texture_editor_open_source_task_label(source_path: Path) -> str:
    return f"Opening {Path(source_path).name} in Texture Editor..."


def texture_editor_compare_request_state(
    document: Optional[TextureEditorDocument],
) -> TextureEditorCompareRequestState:
    if document is None:
        return TextureEditorCompareRequestState(
            can_request=False,
            relative_path="",
            binding=None,
            status_text="Open a texture first, then use Open In Compare.",
            error=True,
        )
    binding = dataclasses.replace(document.source_binding)
    relative_path = (binding.relative_path or binding.archive_relative_path).strip()
    if not relative_path:
        return TextureEditorCompareRequestState(
            can_request=False,
            relative_path="",
            binding=binding,
            status_text="The current document does not have a relative game path, so Compare cannot focus it automatically.",
            error=True,
        )
    return TextureEditorCompareRequestState(
        can_request=True,
        relative_path=relative_path,
        binding=binding,
        status_text="",
        error=False,
    )


def texture_editor_metadata_html(document: TextureEditorDocument) -> str:
    binding = document.source_binding

    def _cell_text(value: str) -> str:
        text = value.strip() or "-"
        return (
            "<div style='white-space:pre-wrap; word-break:break-word; color:#D8E1EE; line-height:1.25;'>"
            f"{html.escape(text)}</div>"
        )

    semantics_text = f"{binding.texture_type}/{binding.semantic_subtype}"
    if semantics_text == "unknown/unknown":
        semantics_text = "Unknown"
    refined_html = [
        f"<div style='font-weight:600; color:#E7EDF7; margin-bottom:2px; line-height:1.2;'>{html.escape(document.title)}</div>",
        f"<div style='margin-bottom:8px; color:#B4C0D4; line-height:1.2;'>{document.width}x{document.height} px</div>",
        "<table style='width:100%; border-collapse:separate; border-spacing:0 6px;'>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Origin</td><td>{_cell_text(binding.launch_origin or 'file')}</td></tr>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Source</td><td>{_cell_text(binding.source_path)}</td></tr>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Relative path</td><td>{_cell_text(binding.relative_path or binding.archive_relative_path)}</td></tr>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Package</td><td>{_cell_text(binding.package_root)}</td></tr>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Original DDS</td><td>{_cell_text(binding.original_dds_path)}</td></tr>",
        f"<tr><td style='width:96px; vertical-align:top; color:#E7EDF7; font-weight:600;'>Semantics</td><td>{_cell_text(semantics_text)}</td></tr>",
        "</table>",
    ]
    return "".join(refined_html)


def texture_editor_metadata_display_state(
    document: Optional[TextureEditorDocument],
    *,
    ui_constraint_warning: str = "",
) -> TextureEditorMetadataDisplayState:
    if document is None:
        return TextureEditorMetadataDisplayState(
            html="<p>No document open.</p>",
            warning_text="",
            warning_visible=False,
        )
    combined_warning = texture_editor_combined_warning(document.technical_warning, ui_constraint_warning)
    return TextureEditorMetadataDisplayState(
        html=texture_editor_metadata_html(document),
        warning_text=combined_warning,
        warning_visible=bool(combined_warning),
    )
