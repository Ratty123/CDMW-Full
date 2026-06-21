from __future__ import annotations

"""History snapshot encoding helpers for the standalone Texture Editor UI."""

import dataclasses
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from cdmw.core.texture_editor import capture_texture_editor_snapshot, restore_texture_editor_snapshot
from cdmw.models import TextureEditorCommand, TextureEditorDocument, TextureEditorHistoryEntry


@dataclasses.dataclass(frozen=True)
class TextureEditorHistoryAppliedState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    floating_pixels: Optional[np.ndarray]
    floating_mask: Optional[np.ndarray]


@dataclasses.dataclass(frozen=True)
class TextureEditorHistoryReplayPlan:
    checkpoint_index: int
    apply_indices: Tuple[int, ...]


@dataclasses.dataclass(frozen=True)
class TextureEditorHistoryRestoreState:
    can_restore: bool
    replay_plan: TextureEditorHistoryReplayPlan
    status_text: str


@dataclasses.dataclass(frozen=True)
class TextureEditorHistorySelectionState:
    selected_index: Optional[int]
    status_text: str


@dataclasses.dataclass(frozen=True)
class TextureEditorHistoryClearedState:
    history_snapshots: List[Dict[str, object]]
    history_index: int
    status_text: str


def encode_texture_editor_rgba_blob(pixels: np.ndarray) -> bytes:
    encoded = cv2.imencode(".png", cv2.cvtColor(np.asarray(pixels, dtype=np.uint8), cv2.COLOR_RGBA2BGRA))[1]
    return bytes(encoded)


def decode_texture_editor_rgba_blob(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if not blob:
        return None
    decoded = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        return None
    if decoded.ndim == 2:
        decoded = cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGRA)
    elif decoded.shape[2] == 3:
        decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2BGRA)
    return np.asarray(cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA), dtype=np.uint8).copy()


def texture_editor_history_layer_canvas_offset(document: TextureEditorDocument, layer_id: str) -> Tuple[int, int]:
    for layer in document.layers:
        if layer.layer_id == layer_id or layer.mask_layer_id == layer_id:
            return (int(layer.offset_x), int(layer.offset_y))
    return (0, 0)


def encode_texture_editor_history_layer_state(
    document: TextureEditorDocument,
    layer_id: str,
    pixels: Optional[np.ndarray],
    *,
    dirty_bounds: Optional[Tuple[int, int, int, int]],
    previous_pixels: Optional[np.ndarray] = None,
) -> Optional[object]:
    if pixels is None:
        return None
    if dirty_bounds is None or previous_pixels is None or previous_pixels.shape != pixels.shape:
        return encode_texture_editor_rgba_blob(pixels)
    offset_x, offset_y = texture_editor_history_layer_canvas_offset(document, layer_id)
    dirty_x, dirty_y, dirty_w, dirty_h = dirty_bounds
    gx0 = max(int(offset_x), int(dirty_x))
    gy0 = max(int(offset_y), int(dirty_y))
    gx1 = min(int(offset_x + pixels.shape[1]), int(dirty_x + dirty_w))
    gy1 = min(int(offset_y + pixels.shape[0]), int(dirty_y + dirty_h))
    if gx1 <= gx0 or gy1 <= gy0:
        return None
    lx0 = int(gx0 - offset_x)
    ly0 = int(gy0 - offset_y)
    lw = int(gx1 - gx0)
    lh = int(gy1 - gy0)
    if lw <= 0 or lh <= 0:
        return None
    patch_area = lw * lh
    full_area = max(1, int(pixels.shape[0]) * int(pixels.shape[1]))
    if patch_area >= int(full_area * 0.6):
        return encode_texture_editor_rgba_blob(pixels)
    patch = pixels[ly0:ly0 + lh, lx0:lx0 + lw]
    return {
        "mode": "patch",
        "shape": [int(pixels.shape[0]), int(pixels.shape[1])],
        "local_bounds": [lx0, ly0, lw, lh],
        "blob": encode_texture_editor_rgba_blob(patch),
    }


def decode_texture_editor_history_layer_state(
    current_pixels: Optional[np.ndarray],
    payload: object,
) -> Optional[np.ndarray]:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        return decode_texture_editor_rgba_blob(bytes(payload))
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("mode", "") or "")
    if mode != "patch":
        blob = payload.get("blob")
        return decode_texture_editor_rgba_blob(blob if isinstance(blob, (bytes, bytearray)) else None)
    shape_raw = payload.get("shape")
    bounds_raw = payload.get("local_bounds")
    blob = payload.get("blob")
    if not (
        isinstance(shape_raw, list)
        and len(shape_raw) == 2
        and isinstance(bounds_raw, list)
        and len(bounds_raw) == 4
        and isinstance(blob, (bytes, bytearray))
    ):
        return None
    target_h = max(1, int(shape_raw[0]))
    target_w = max(1, int(shape_raw[1]))
    lx0, ly0, lw, lh = (max(0, int(value)) for value in bounds_raw)
    patch = decode_texture_editor_rgba_blob(bytes(blob))
    if patch is None:
        return None
    if current_pixels is not None and current_pixels.shape == (target_h, target_w, 4):
        restored = current_pixels.copy()
    else:
        restored = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    restored[ly0:ly0 + min(lh, patch.shape[0]), lx0:lx0 + min(lw, patch.shape[1])] = patch[:lh, :lw]
    return restored


def texture_editor_history_auxiliary_layer_ids(document: TextureEditorDocument) -> set[str]:
    aux_ids: set[str] = set()
    for layer in document.layers:
        if layer.mask_layer_id:
            aux_ids.add(layer.mask_layer_id)
    for adjustment in document.adjustment_layers:
        if adjustment.mask_layer_id:
            aux_ids.add(adjustment.mask_layer_id)
    return aux_ids


def texture_editor_history_should_checkpoint(
    *,
    history_count: int,
    force_checkpoint: bool,
) -> bool:
    return bool(force_checkpoint or history_count <= 0 or ((history_count + 1) % 20 == 0))


def texture_editor_history_tracked_layer_ids(
    before_document: TextureEditorDocument,
    after_document: TextureEditorDocument,
) -> set[str]:
    tracked_ids = {layer.layer_id for layer in before_document.layers}
    tracked_ids.update(layer.layer_id for layer in after_document.layers)
    tracked_ids.update(texture_editor_history_auxiliary_layer_ids(before_document))
    tracked_ids.update(texture_editor_history_auxiliary_layer_ids(after_document))
    return tracked_ids


def build_texture_editor_checkpoint_record(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    label: str,
    *,
    timestamp: float,
    floating_pixels: Optional[np.ndarray] = None,
) -> Dict[str, object]:
    snapshot = capture_texture_editor_snapshot(document, layer_pixels, label)
    return {
        "entry": snapshot["entry"],
        "command": dataclasses.asdict(
            TextureEditorCommand(kind="checkpoint", label=label, timestamp=timestamp, checkpoint=True)
        ),
        "checkpoint": snapshot,
        "floating_pixels": None if floating_pixels is None else encode_texture_editor_rgba_blob(floating_pixels),
    }


def build_texture_editor_delta_history_record(
    *,
    label: str,
    before_document: TextureEditorDocument,
    after_document: TextureEditorDocument,
    before_layer_pixels: Dict[str, np.ndarray],
    after_layer_pixels: Dict[str, np.ndarray],
    kind: str,
    timestamp: float,
    dirty_bounds: Optional[Tuple[int, int, int, int]] = None,
    tracked_layer_ids: Optional[Sequence[str]] = None,
    before_floating_pixels: Optional[np.ndarray] = None,
    after_floating_pixels: Optional[np.ndarray] = None,
) -> Dict[str, object]:
    if tracked_layer_ids is None:
        tracked_ids = texture_editor_history_tracked_layer_ids(before_document, after_document)
    else:
        tracked_ids = set(tracked_layer_ids)
    before_blobs: Dict[str, object] = {}
    after_blobs: Dict[str, object] = {}
    for layer_id in tracked_ids:
        before_pixels = before_layer_pixels.get(layer_id)
        after_pixels = after_layer_pixels.get(layer_id)
        if before_pixels is not None and after_pixels is not None and before_pixels.shape == after_pixels.shape and np.array_equal(before_pixels, after_pixels):
            continue
        before_payload = encode_texture_editor_history_layer_state(
            before_document,
            layer_id,
            before_pixels,
            dirty_bounds=dirty_bounds,
            previous_pixels=after_pixels,
        )
        after_payload = encode_texture_editor_history_layer_state(
            after_document,
            layer_id,
            after_pixels,
            dirty_bounds=dirty_bounds,
            previous_pixels=before_pixels,
        )
        if before_payload is None and after_payload is None:
            continue
        before_blobs[layer_id] = before_payload
        after_blobs[layer_id] = after_payload
    command = TextureEditorCommand(
        kind=kind,
        label=label,
        timestamp=timestamp,
        dirty_bounds=dirty_bounds,
        checkpoint=False,
    )
    return {
        "entry": TextureEditorHistoryEntry(label=label, timestamp=command.timestamp),
        "command": dataclasses.asdict(command),
        "before_document": dataclasses.replace(before_document),
        "after_document": dataclasses.replace(after_document),
        "before_layers": before_blobs,
        "after_layers": after_blobs,
        "before_floating_pixels": None if before_floating_pixels is None else encode_texture_editor_rgba_blob(before_floating_pixels),
        "after_floating_pixels": None if after_floating_pixels is None else encode_texture_editor_rgba_blob(after_floating_pixels),
    }


def texture_editor_history_with_appended_record(
    history_snapshots: Sequence[Dict[str, object]],
    history_index: int,
    record: Dict[str, object],
    *,
    limit: int = 100,
) -> Tuple[List[Dict[str, object]], int]:
    updated = list(history_snapshots)
    if int(history_index) < len(updated) - 1:
        updated = updated[: int(history_index) + 1]
    updated.append(record)
    if len(updated) > int(limit):
        updated.pop(0)
    return updated, len(updated) - 1


def texture_editor_applied_history_document_state(
    document: TextureEditorDocument,
    current_layer_pixels: Dict[str, np.ndarray],
    layer_blobs: Dict[str, object],
) -> Dict[str, np.ndarray]:
    target_ids = {layer.layer_id for layer in document.layers}
    target_ids.update(texture_editor_history_auxiliary_layer_ids(document))
    new_pixels: Dict[str, np.ndarray] = {}
    for layer_id in target_ids:
        if layer_id in current_layer_pixels:
            new_pixels[layer_id] = current_layer_pixels[layer_id]
    for layer_id, blob in layer_blobs.items():
        if blob is None:
            new_pixels.pop(layer_id, None)
            continue
        decoded = decode_texture_editor_history_layer_state(new_pixels.get(layer_id), blob)
        if decoded is not None:
            new_pixels[layer_id] = decoded
    return new_pixels


def texture_editor_history_record_application_state(
    record: Dict[str, object],
    *,
    direction: str,
    current_layer_pixels: Dict[str, np.ndarray],
) -> TextureEditorHistoryAppliedState:
    checkpoint = record.get("checkpoint")
    if checkpoint is not None:
        document, layer_pixels, _entry = restore_texture_editor_snapshot(checkpoint)
        floating_blob = record.get("floating_pixels")
        floating_pixels = decode_texture_editor_rgba_blob(
            bytes(floating_blob) if isinstance(floating_blob, (bytes, bytearray)) else None
        )
        floating_mask = None if floating_pixels is None else floating_pixels[..., 3].copy()
        return TextureEditorHistoryAppliedState(
            document=document,
            layer_pixels=layer_pixels,
            floating_pixels=floating_pixels,
            floating_mask=floating_mask,
        )
    if direction == "before":
        document = dataclasses.replace(record["before_document"])  # type: ignore[arg-type]
        layer_blobs = record.get("before_layers") or {}
        floating_blob = record.get("before_floating_pixels")
    else:
        document = dataclasses.replace(record["after_document"])  # type: ignore[arg-type]
        layer_blobs = record.get("after_layers") or {}
        floating_blob = record.get("after_floating_pixels")
    layer_pixels = texture_editor_applied_history_document_state(
        document,
        current_layer_pixels,
        layer_blobs,  # type: ignore[arg-type]
    )
    floating_pixels = decode_texture_editor_rgba_blob(
        bytes(floating_blob) if isinstance(floating_blob, (bytes, bytearray)) else None
    )
    floating_mask = None if floating_pixels is None else floating_pixels[..., 3].copy()
    return TextureEditorHistoryAppliedState(
        document=document,
        layer_pixels=layer_pixels,
        floating_pixels=floating_pixels,
        floating_mask=floating_mask,
    )


def texture_editor_history_replay_plan(
    history_snapshots: Sequence[Dict[str, object]],
    index: int,
) -> TextureEditorHistoryReplayPlan:
    if index < 0 or index >= len(history_snapshots):
        return TextureEditorHistoryReplayPlan(checkpoint_index=-1, apply_indices=())
    checkpoint_index = int(index)
    while checkpoint_index >= 0 and "checkpoint" not in history_snapshots[checkpoint_index]:
        checkpoint_index -= 1
    if checkpoint_index >= 0:
        apply_indices = (checkpoint_index, *range(checkpoint_index + 1, int(index) + 1))
    else:
        apply_indices = tuple(range(0, int(index) + 1))
    return TextureEditorHistoryReplayPlan(checkpoint_index=checkpoint_index, apply_indices=tuple(apply_indices))


def texture_editor_history_restore_state(
    history_snapshots: Sequence[Dict[str, object]],
    index: int,
) -> TextureEditorHistoryRestoreState:
    replay_plan = texture_editor_history_replay_plan(history_snapshots, index)
    if index < 0 or index >= len(history_snapshots) or not replay_plan.apply_indices:
        return TextureEditorHistoryRestoreState(can_restore=False, replay_plan=replay_plan, status_text="")
    entry = history_snapshots[index]["entry"]
    return TextureEditorHistoryRestoreState(
        can_restore=True,
        replay_plan=replay_plan,
        status_text=texture_editor_history_restored_status_text(entry.label),  # type: ignore[union-attr]
    )


def texture_editor_history_selected_row_state(
    history_snapshots: Sequence[Dict[str, object]],
    row: int,
    *,
    history_index: int,
) -> TextureEditorHistorySelectionState:
    if row < 0 or row == history_index or row >= len(history_snapshots):
        return TextureEditorHistorySelectionState(selected_index=None, status_text="")
    entry = history_snapshots[row]["entry"]
    return TextureEditorHistorySelectionState(
        selected_index=int(row),
        status_text=texture_editor_history_selection_status_text(entry.label),  # type: ignore[union-attr]
    )


def texture_editor_history_cleared_state(record: Dict[str, object]) -> TextureEditorHistoryClearedState:
    return TextureEditorHistoryClearedState(
        history_snapshots=[record],
        history_index=0,
        status_text=texture_editor_history_cleared_status_text(),
    )


def texture_editor_history_list_item_text(entry_label: str, *, current: bool) -> str:
    return f"{entry_label} (current)" if current else entry_label


def texture_editor_history_selection_status_text(entry_label: str) -> str:
    return f"Selected history step '{entry_label}'. Double-click or use Restore Selected to jump to it."


def texture_editor_history_restored_status_text(entry_label: str) -> str:
    return f"Restored history step: {entry_label}."


def texture_editor_history_cleared_status_text() -> str:
    return "Texture Editor history cleared. Current state kept as the new baseline."


__all__ = [
    "TextureEditorHistoryAppliedState",
    "TextureEditorHistoryClearedState",
    "TextureEditorHistoryReplayPlan",
    "TextureEditorHistoryRestoreState",
    "TextureEditorHistorySelectionState",
    "build_texture_editor_checkpoint_record",
    "build_texture_editor_delta_history_record",
    "decode_texture_editor_history_layer_state",
    "decode_texture_editor_rgba_blob",
    "encode_texture_editor_history_layer_state",
    "encode_texture_editor_rgba_blob",
    "texture_editor_applied_history_document_state",
    "texture_editor_history_auxiliary_layer_ids",
    "texture_editor_history_layer_canvas_offset",
    "texture_editor_history_list_item_text",
    "texture_editor_history_record_application_state",
    "texture_editor_history_replay_plan",
    "texture_editor_history_restore_state",
    "texture_editor_history_restored_status_text",
    "texture_editor_history_selected_row_state",
    "texture_editor_history_cleared_status_text",
    "texture_editor_history_cleared_state",
    "texture_editor_history_selection_status_text",
    "texture_editor_history_should_checkpoint",
    "texture_editor_history_tracked_layer_ids",
    "texture_editor_history_with_appended_record",
]
