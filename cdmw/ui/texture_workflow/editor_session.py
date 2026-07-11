from __future__ import annotations

"""Session state container for the standalone Texture Editor UI."""

import dataclasses
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from PySide6.QtGui import QIcon

from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers
from cdmw.models import TextureEditorDocument


@dataclasses.dataclass
class _TextureEditorSession:
    label: str
    document: Optional[TextureEditorDocument]
    layer_pixels: Dict[str, np.ndarray]
    history_snapshots: List[Dict[str, object]]
    history_index: int
    original_flattened: Optional[np.ndarray] = None
    compressed_preview_flattened: Optional[np.ndarray] = None
    layer_property_dirty: bool = False
    floating_pixels: Optional[np.ndarray] = None
    floating_mask: Optional[np.ndarray] = None
    composite_cache: Optional[np.ndarray] = None
    composite_cache_revision: int = -1
    composite_dirty_bounds: Optional[Tuple[int, int, int, int]] = None
    thumbnail_cache: Dict[Tuple[str, int], QIcon] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class TextureEditorSessionTabState:
    label: str
    tooltip: str


@dataclasses.dataclass(frozen=True)
class TextureEditorSessionCloseState:
    has_remaining_sessions: bool
    next_index: int
    adjusted_active_index: int
    status_message: str


@dataclasses.dataclass(frozen=True)
class TextureEditorSessionLabelUpdateState:
    can_update: bool
    index: int
    label: str


def texture_editor_document_key(document: Optional[TextureEditorDocument]) -> str:
    if document is None:
        return ""
    return document.project_path.as_posix() if document.project_path is not None else document.title


def texture_editor_session_document_id(session: _TextureEditorSession) -> str:
    if session.document is not None:
        return texture_editor_document_key(session.document)
    return session.label


def texture_editor_open_document_ids(sessions: Iterable[_TextureEditorSession]) -> Tuple[str, ...]:
    return tuple(texture_editor_session_document_id(session) for session in sessions)


def texture_editor_session_tab_state(session: _TextureEditorSession, index: int) -> TextureEditorSessionTabState:
    label = session.label or f"Document {int(index) + 1}"
    tooltip = ""
    if session.document is not None:
        tooltip = session.document.source_binding.source_path or str(session.document.project_path or "")
    return TextureEditorSessionTabState(label=label, tooltip=tooltip)


def texture_editor_active_session_original_flattened(
    sessions: Iterable[_TextureEditorSession],
    active_index: int,
) -> Optional[np.ndarray]:
    session_list = tuple(sessions)
    if 0 <= int(active_index) < len(session_list):
        return session_list[int(active_index)].original_flattened
    return None


def texture_editor_active_session_compare_flattened(
    sessions: Iterable[_TextureEditorSession],
    active_index: int,
) -> Optional[np.ndarray]:
    session_list = tuple(sessions)
    if 0 <= int(active_index) < len(session_list):
        session = session_list[int(active_index)]
        return session.compressed_preview_flattened if session.compressed_preview_flattened is not None else session.original_flattened
    return None


def texture_editor_active_session_label_update_state(
    sessions: Iterable[_TextureEditorSession],
    active_index: int,
    document_title: str,
) -> TextureEditorSessionLabelUpdateState:
    session_list = tuple(sessions)
    if 0 <= int(active_index) < len(session_list):
        return TextureEditorSessionLabelUpdateState(
            can_update=True,
            index=int(active_index),
            label=str(document_title or ""),
        )
    return TextureEditorSessionLabelUpdateState(can_update=False, index=-1, label="")


def texture_editor_existing_source_session_index(
    sessions: Iterable[_TextureEditorSession],
    source_path: Path,
) -> int:
    resolved_source = Path(source_path).expanduser().resolve()
    for index, session in enumerate(sessions):
        document = session.document
        if document is None or not document.source_binding.source_path:
            continue
        try:
            if Path(document.source_binding.source_path).expanduser().resolve() == resolved_source:
                return int(index)
        except Exception:
            continue
    return -1


def texture_editor_existing_project_session_index(
    sessions: Iterable[_TextureEditorSession],
    project_path: Path,
) -> int:
    resolved_project = Path(project_path).expanduser().resolve()
    for index, session in enumerate(sessions):
        document = session.document
        if document is not None and document.project_path is not None and document.project_path == resolved_project:
            return int(index)
    return -1


def create_texture_editor_session(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    label: str,
) -> _TextureEditorSession:
    original_flattened = flatten_texture_editor_layers(document, layer_pixels)
    original_flattened.setflags(write=False)
    return _TextureEditorSession(
        label=label,
        document=document,
        layer_pixels=layer_pixels,
        history_snapshots=[],
        history_index=-1,
        original_flattened=original_flattened,
        compressed_preview_flattened=None,
        layer_property_dirty=False,
        floating_pixels=None,
        floating_mask=None,
        composite_cache=None,
        composite_cache_revision=-1,
        composite_dirty_bounds=None,
        thumbnail_cache={},
    )


def texture_editor_session_close_state(
    *,
    session_count_before: int,
    active_index: int,
    closed_index: int,
) -> TextureEditorSessionCloseState:
    remaining_count = max(0, int(session_count_before) - 1)
    if remaining_count <= 0:
        return TextureEditorSessionCloseState(
            has_remaining_sessions=False,
            next_index=-1,
            adjusted_active_index=-1,
            status_message="Closed the last Texture Editor document.",
        )

    adjusted_active_index = int(active_index)
    next_index = int(closed_index)
    if closed_index == active_index:
        next_index = min(int(closed_index), remaining_count - 1)
        adjusted_active_index = next_index
    elif closed_index < active_index:
        adjusted_active_index = int(active_index) - 1
        next_index = adjusted_active_index

    return TextureEditorSessionCloseState(
        has_remaining_sessions=True,
        next_index=next_index,
        adjusted_active_index=adjusted_active_index,
        status_message="",
    )


def texture_editor_document_composite_revision(
    document: Optional[TextureEditorDocument],
    *,
    has_floating_pixels: bool,
) -> int:
    if document is None:
        return -1
    revision = int(document.composite_revision)
    revision += sum(int(layer.revision) for layer in document.layers)
    revision += sum(int(layer.revision) for layer in document.adjustment_layers)
    if document.floating_selection is not None and has_floating_pixels:
        revision += 1000003
        revision += int(document.floating_selection.offset_x)
        revision += int(document.floating_selection.offset_y)
        revision += int(round(document.floating_selection.rotation_degrees * 10.0))
        revision += int(round(document.floating_selection.scale_x * 100.0))
        revision += int(round(document.floating_selection.scale_y * 100.0))
        revision += 97 if document.floating_selection.flip_x else 0
        revision += 193 if document.floating_selection.flip_y else 0
    return revision


__all__ = [
    "TextureEditorSessionCloseState",
    "TextureEditorSessionLabelUpdateState",
    "TextureEditorSessionTabState",
    "_TextureEditorSession",
    "create_texture_editor_session",
    "texture_editor_active_session_compare_flattened",
    "texture_editor_active_session_label_update_state",
    "texture_editor_active_session_original_flattened",
    "texture_editor_document_composite_revision",
    "texture_editor_document_key",
    "texture_editor_existing_project_session_index",
    "texture_editor_existing_source_session_index",
    "texture_editor_open_document_ids",
    "texture_editor_session_close_state",
    "texture_editor_session_document_id",
    "texture_editor_session_tab_state",
]
