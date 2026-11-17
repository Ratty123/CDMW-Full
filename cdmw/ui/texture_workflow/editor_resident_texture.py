"""Linked Texture Editor dirty-region handoff for the resident mesh viewport."""

from __future__ import annotations

import dataclasses
import threading
import weakref
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PySide6.QtCore import QTimer

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_session import (
    texture_editor_document_composite_revision,
)
from cdmw.ui.texture_workflow.editor_view_state import (
    clamped_texture_editor_composite_dirty_bounds,
    merged_texture_editor_composite_dirty_bounds,
)


@dataclass(frozen=True, slots=True)
class TextureEditorResidentPatch:
    binding: TextureEditorSourceBinding
    texture_revision: int
    texture_width: int
    texture_height: int
    rect: tuple[int, int, int, int]
    pixel_format: str
    row_pitch: int
    bgra: bytes
    current_rgba: np.ndarray
    composite_lease: "TextureEditorCompositeLease"


@dataclass(slots=True)
class _CompositeLeaseState:
    rgba: weakref.ReferenceType[np.ndarray]
    count: int
    restore_writeable: bool


_COMPOSITE_LEASE_LOCK = threading.Lock()
_COMPOSITE_LEASES: dict[int, _CompositeLeaseState] = {}


class TextureEditorCompositeLease:
    def __init__(self, rgba: np.ndarray) -> None:
        self._rgba = rgba
        self._released = False
        self._key = id(rgba)
        with _COMPOSITE_LEASE_LOCK:
            state = _COMPOSITE_LEASES.get(self._key)
            if state is None or state.rgba() is not rgba:
                state = _CompositeLeaseState(
                    rgba=weakref.ref(rgba),
                    count=0,
                    restore_writeable=bool(rgba.flags.writeable),
                )
                _COMPOSITE_LEASES[self._key] = state
            state.count += 1
            self._state = state
            rgba.setflags(write=False)

    def release(self) -> None:
        with _COMPOSITE_LEASE_LOCK:
            if self._released:
                return
            self._released = True
            self._state.count -= 1
            if self._state.count > 0:
                return
            if _COMPOSITE_LEASES.get(self._key) is self._state:
                _COMPOSITE_LEASES.pop(self._key, None)
            if not self._state.restore_writeable:
                return
            rgba = self._state.rgba()
            if rgba is not None:
                try:
                    rgba.setflags(write=True)
                except ValueError:
                    pass

    @property
    def released(self) -> bool:
        with _COMPOSITE_LEASE_LOCK:
            return self._released


def build_texture_editor_resident_patch(
    binding: TextureEditorSourceBinding,
    composite_rgba: np.ndarray,
    *,
    texture_revision: int,
    dirty_bounds: Optional[tuple[int, int, int, int]],
) -> TextureEditorResidentPatch:
    rgba = np.asarray(composite_rgba)
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("resident texture composite must be uint8 RGBA")
    height, width = int(rgba.shape[0]), int(rgba.shape[1])
    bounds = (
        (0, 0, width, height)
        if dirty_bounds is None
        else clamped_texture_editor_composite_dirty_bounds(
            dirty_bounds,
            document_width=width,
            document_height=height,
        )
    )
    if bounds is None:
        raise ValueError("resident texture dirty region is empty")
    x, y, patch_width, patch_height = bounds
    rgba_region = rgba[y : y + patch_height, x : x + patch_width]
    bgra_region = np.ascontiguousarray(rgba_region[:, :, (2, 1, 0, 3)])
    lease = TextureEditorCompositeLease(rgba)
    return TextureEditorResidentPatch(
        binding=dataclasses.replace(binding),
        texture_revision=max(0, int(texture_revision)),
        texture_width=width,
        texture_height=height,
        rect=bounds,
        pixel_format="bgra8_unorm",
        row_pitch=patch_width * 4,
        bgra=bgra_region.tobytes(order="C"),
        current_rgba=rgba,
        composite_lease=lease,
    )


def _resident_patch_document_key(document: object) -> tuple[str, ...]:
    """Which texture a patch belongs to. Not the document object: every edit and most
    view refreshes replace it (``dataclasses.replace``), so a patch scheduled by an edit
    was dropped whenever the refresh after it (a layer's visibility, Move, an Undo of a
    layer or adjustment step, a History restore) made a new one before the patch went
    out. A switch to another texture's document still drops it."""

    binding = getattr(document, "source_binding", None)
    return tuple(
        str(getattr(binding, name, "") or "")
        for name in ("launch_origin", "mesh_session_id", "mesh_resource_id", "source_path")
    )


class TextureEditorResidentTextureMixin:
    def _initialize_resident_texture_patch_state(self) -> None:
        self._resident_texture_patch_dirty_bounds: Optional[tuple[int, int, int, int]] = None
        self._resident_texture_patch_full_dirty = False
        self._resident_texture_patch_document_key: Optional[tuple[str, ...]] = None
        self._resident_texture_patch_timer = QTimer(self)
        self._resident_texture_patch_timer.setSingleShot(True)
        self._resident_texture_patch_timer.timeout.connect(self._emit_resident_texture_patch)

    def _schedule_resident_texture_patch(
        self,
        dirty_bounds: Optional[tuple[int, int, int, int]],
    ) -> None:
        document = self.document
        if document is None:
            return
        binding = document.source_binding
        channel = str(binding.mesh_channel or "base").strip().lower()
        if binding.launch_origin != "mesh_editor":
            return
        # A texture opened from the Mesh Editor's Textures panel shows every
        # channel live (step 8); the older hand-off only showed base colour.
        if binding.mesh_commit_mode != "live" and channel not in {"base", "base_color", "albedo"}:
            return
        document_key = _resident_patch_document_key(document)
        if self._resident_texture_patch_document_key not in {None, document_key}:
            self._resident_texture_patch_dirty_bounds = None
            self._resident_texture_patch_full_dirty = False
        self._resident_texture_patch_document_key = document_key
        if dirty_bounds is None:
            self._resident_texture_patch_full_dirty = True
            self._resident_texture_patch_dirty_bounds = None
        elif not self._resident_texture_patch_full_dirty:
            self._resident_texture_patch_dirty_bounds = merged_texture_editor_composite_dirty_bounds(
                self._resident_texture_patch_dirty_bounds,
                dirty_bounds,
            )
        self._resident_texture_patch_timer.start(0)

    def _emit_resident_texture_patch(self) -> None:
        document = self.document
        if document is None or _resident_patch_document_key(document) != self._resident_texture_patch_document_key:
            self._clear_resident_texture_patch_state()
            return
        dirty_bounds = None if self._resident_texture_patch_full_dirty else self._resident_texture_patch_dirty_bounds
        self._clear_resident_texture_patch_state(stop_timer=False)
        composite = self._current_composite_rgba()
        if composite is None:
            return
        try:
            patch = build_texture_editor_resident_patch(
                document.source_binding,
                composite,
                texture_revision=texture_editor_document_composite_revision(
                    document,
                    has_floating_pixels=self._floating_pixels is not None,
                ),
                dirty_bounds=dirty_bounds,
            )
        except (TypeError, ValueError):
            return
        self.resident_texture_patch_ready.emit(patch)

    def _clear_resident_texture_patch_state(self, *, stop_timer: bool = True) -> None:
        if stop_timer:
            self._resident_texture_patch_timer.stop()
        self._resident_texture_patch_dirty_bounds = None
        self._resident_texture_patch_full_dirty = False
        self._resident_texture_patch_document_key = None


__all__ = [
    "TextureEditorResidentPatch",
    "TextureEditorCompositeLease",
    "TextureEditorResidentTextureMixin",
    "build_texture_editor_resident_patch",
]
