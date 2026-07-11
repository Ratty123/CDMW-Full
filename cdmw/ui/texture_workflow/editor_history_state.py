from __future__ import annotations

"""History snapshot encoding helpers for the standalone Texture Editor UI."""

import dataclasses
import struct
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import lz4.frame
import numpy as np

from cdmw.models import TextureEditorCommand, TextureEditorDocument, TextureEditorHistoryEntry


_RGBA_LZ4_MAGIC = b"CDMWLZ4\0"
_RGBA_LZ4_HEADER = struct.Struct("<8sIII")
_RGBA_ASYNC_THRESHOLD_BYTES = 256 * 1024
_RGBA_ENCODER_LOCK = threading.Lock()
_RGBA_ENCODER: Optional[ThreadPoolExecutor] = None


def _texture_editor_history_encoder() -> ThreadPoolExecutor:
    global _RGBA_ENCODER
    with _RGBA_ENCODER_LOCK:
        if _RGBA_ENCODER is None:
            _RGBA_ENCODER = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cdmw-texture-history")
        return _RGBA_ENCODER


def shutdown_texture_editor_history_encoder() -> None:
    global _RGBA_ENCODER
    with _RGBA_ENCODER_LOCK:
        encoder = _RGBA_ENCODER
        _RGBA_ENCODER = None
    if encoder is not None:
        encoder.shutdown(wait=False, cancel_futures=True)


def _compress_texture_editor_rgba(pixels: np.ndarray) -> bytes:
    array = np.ascontiguousarray(pixels, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("Texture Editor history pixels must be RGBA.")
    header = _RGBA_LZ4_HEADER.pack(_RGBA_LZ4_MAGIC, int(array.shape[0]), int(array.shape[1]), 4)
    return header + lz4.frame.compress(memoryview(array), compression_level=0)


class _PendingRgbaBlob:
    def __init__(self, pixels: np.ndarray) -> None:
        self._lock = threading.Lock()
        self._array: Optional[np.ndarray] = np.ascontiguousarray(pixels, dtype=np.uint8).copy()
        self._blob: Optional[bytes] = None
        self._future: Future[bytes] = _texture_editor_history_encoder().submit(
            _compress_texture_editor_rgba,
            self._array,
        )
        self._future.add_done_callback(self._encoded)

    def _encoded(self, future: Future[bytes]) -> None:
        try:
            blob = future.result()
        except Exception:
            return
        with self._lock:
            self._blob = blob
            self._array = None

    def decode(self) -> Optional[np.ndarray]:
        with self._lock:
            array = self._array
            blob = self._blob
        if array is not None:
            return array.copy()
        return _decode_texture_editor_rgba_bytes(blob)


def _is_rgba_blob(value: object) -> bool:
    return isinstance(value, (bytes, bytearray, _PendingRgbaBlob))


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


@dataclasses.dataclass(frozen=True, slots=True)
class TextureEditorHistoryLayerPatch:
    pixels: np.ndarray
    shape: Tuple[int, int, int]
    local_bounds: Tuple[int, int, int, int]


class _PendingTextureEditorCheckpoint:
    """Materialize an evicted history prefix off the UI thread."""

    def __init__(self, base_record: Dict[str, object], apply_record: Dict[str, object]) -> None:
        self._lock = threading.RLock()
        self._base_record = base_record
        self._apply_records = [apply_record]
        self._revision = 1
        self._wake = threading.Event()
        self._future: Optional[Future[object]] = None
        self._schedule_locked()

    def append(self, apply_record: Dict[str, object]) -> None:
        with self._lock:
            self._apply_records.append(apply_record)
            self._revision += 1
            self._wake.set()
            self._schedule_locked()

    def snapshot(self) -> Tuple[Dict[str, object], Tuple[Dict[str, object], ...]]:
        with self._lock:
            if self._apply_records:
                self._schedule_locked()
            return self._base_record, tuple(self._apply_records)

    def _schedule_locked(self) -> None:
        if self._future is not None:
            return
        try:
            self._future = _texture_editor_history_encoder().submit(self._materialize)
        except RuntimeError:
            self._future = None

    def _materialize(self) -> None:
        try:
            while True:
                with self._lock:
                    revision = self._revision
                self._wake.clear()
                self._wake.wait(0.05)
                with self._lock:
                    if revision != self._revision:
                        continue
                    base_record = self._base_record
                    apply_records = tuple(self._apply_records)
                state = texture_editor_history_record_application_state(
                    base_record,
                    direction="after",
                    current_layer_pixels={},
                    copy_patch_pixels=False,
                )
                for apply_record in apply_records:
                    state = texture_editor_history_record_application_state(
                        apply_record,
                        direction="after",
                        current_layer_pixels=state.layer_pixels,
                        copy_patch_pixels=False,
                    )
                entry = apply_records[-1].get("entry")
                if not isinstance(entry, TextureEditorHistoryEntry):
                    raise ValueError("Texture Editor history entry is invalid.")
                materialized = build_texture_editor_checkpoint_record(
                    state.document,
                    state.layer_pixels,
                    entry.label,
                    timestamp=float(entry.timestamp),
                    floating_pixels=state.floating_pixels,
                    encode_async=False,
                )
                with self._lock:
                    prefix_matches = len(self._apply_records) >= len(apply_records) and all(
                        self._apply_records[index] is record
                        for index, record in enumerate(apply_records)
                    )
                    if not prefix_matches or self._base_record is not base_record:
                        continue
                    self._base_record = materialized
                    del self._apply_records[: len(apply_records)]
                    if not self._apply_records:
                        self._future = None
                        return
        except Exception:
            with self._lock:
                self._future = None


def encode_texture_editor_rgba_blob(pixels: np.ndarray) -> object:
    array = np.asarray(pixels, dtype=np.uint8)
    if array.nbytes >= _RGBA_ASYNC_THRESHOLD_BYTES:
        return _PendingRgbaBlob(array)
    return _compress_texture_editor_rgba(array)


def _decode_texture_editor_rgba_bytes(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if not blob:
        return None
    if blob.startswith(_RGBA_LZ4_MAGIC) and len(blob) >= _RGBA_LZ4_HEADER.size:
        _magic, height, width, channels = _RGBA_LZ4_HEADER.unpack_from(blob)
        if channels != 4 or height <= 0 or width <= 0:
            return None
        try:
            raw = lz4.frame.decompress(blob[_RGBA_LZ4_HEADER.size:])
        except (RuntimeError, ValueError):
            return None
        expected = int(height) * int(width) * 4
        if len(raw) != expected:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4)).copy()
    decoded = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        return None
    if decoded.ndim == 2:
        decoded = cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGRA)
    elif decoded.shape[2] == 3:
        decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2BGRA)
    return np.asarray(cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA), dtype=np.uint8).copy()


def decode_texture_editor_rgba_blob(blob: object) -> Optional[np.ndarray]:
    if isinstance(blob, _PendingRgbaBlob):
        return blob.decode()
    if isinstance(blob, (bytes, bytearray)):
        return _decode_texture_editor_rgba_bytes(bytes(blob))
    return None


def texture_editor_history_layer_canvas_offset(document: TextureEditorDocument, layer_id: str) -> Tuple[int, int]:
    for layer in document.layers:
        if layer.layer_id == layer_id or layer.mask_layer_id == layer_id:
            return (int(layer.offset_x), int(layer.offset_y))
    return (0, 0)


def capture_texture_editor_history_layer_patch(
    document: TextureEditorDocument,
    layer_id: str,
    pixels: np.ndarray,
    dirty_bounds: Optional[Tuple[int, int, int, int]],
) -> Optional[TextureEditorHistoryLayerPatch]:
    if dirty_bounds is None:
        return None
    array = np.asarray(pixels, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 4:
        return None
    offset_x, offset_y = texture_editor_history_layer_canvas_offset(document, layer_id)
    dirty_x, dirty_y, dirty_w, dirty_h = dirty_bounds
    gx0 = max(offset_x, int(dirty_x))
    gy0 = max(offset_y, int(dirty_y))
    gx1 = min(offset_x + array.shape[1], int(dirty_x + dirty_w))
    gy1 = min(offset_y + array.shape[0], int(dirty_y + dirty_h))
    if gx1 <= gx0 or gy1 <= gy0:
        return None
    lx0 = gx0 - offset_x
    ly0 = gy0 - offset_y
    width = gx1 - gx0
    height = gy1 - gy0
    return TextureEditorHistoryLayerPatch(
        pixels=np.array(
            array[ly0:ly0 + height, lx0:lx0 + width],
            dtype=np.uint8,
            copy=True,
            order="C",
        ),
        shape=(int(array.shape[0]), int(array.shape[1]), 4),
        local_bounds=(int(lx0), int(ly0), int(width), int(height)),
    )


def _encode_texture_editor_captured_patch(patch: TextureEditorHistoryLayerPatch) -> Dict[str, object]:
    return {
        "mode": "patch",
        "shape": [int(patch.shape[0]), int(patch.shape[1])],
        "local_bounds": [int(value) for value in patch.local_bounds],
        "blob": encode_texture_editor_rgba_blob(patch.pixels),
    }


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
    *,
    copy_current: bool = True,
) -> Optional[np.ndarray]:
    if payload is None:
        return None
    if _is_rgba_blob(payload):
        return decode_texture_editor_rgba_blob(payload)
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("mode", "") or "")
    if mode != "patch":
        blob = payload.get("blob")
        return decode_texture_editor_rgba_blob(blob)
    shape_raw = payload.get("shape")
    bounds_raw = payload.get("local_bounds")
    blob = payload.get("blob")
    if not (
        isinstance(shape_raw, list)
        and len(shape_raw) == 2
        and isinstance(bounds_raw, list)
        and len(bounds_raw) == 4
        and _is_rgba_blob(blob)
    ):
        return None
    target_h = max(1, int(shape_raw[0]))
    target_w = max(1, int(shape_raw[1]))
    lx0, ly0, lw, lh = (max(0, int(value)) for value in bounds_raw)
    patch = decode_texture_editor_rgba_blob(blob)
    if patch is None:
        return None
    if current_pixels is not None and current_pixels.shape == (target_h, target_w, 4):
        restored = current_pixels.copy() if copy_current else current_pixels
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
    return bool(force_checkpoint or history_count <= 0)


def texture_editor_history_tracked_layer_ids(
    before_document: TextureEditorDocument,
    after_document: TextureEditorDocument,
) -> set[str]:
    tracked_ids = {layer.layer_id for layer in before_document.layers}
    tracked_ids.update(layer.layer_id for layer in after_document.layers)
    tracked_ids.update(texture_editor_history_auxiliary_layer_ids(before_document))
    tracked_ids.update(texture_editor_history_auxiliary_layer_ids(after_document))
    return tracked_ids


def _texture_editor_history_pixels_equal(
    document: TextureEditorDocument,
    layer_id: str,
    before_pixels: np.ndarray,
    after_pixels: np.ndarray,
    dirty_bounds: Optional[Tuple[int, int, int, int]],
) -> bool:
    if before_pixels.shape != after_pixels.shape:
        return False
    if dirty_bounds is None:
        return bool(np.array_equal(before_pixels, after_pixels))
    offset_x, offset_y = texture_editor_history_layer_canvas_offset(document, layer_id)
    dirty_x, dirty_y, dirty_w, dirty_h = dirty_bounds
    left = max(offset_x, int(dirty_x))
    top = max(offset_y, int(dirty_y))
    right = min(offset_x + before_pixels.shape[1], int(dirty_x + dirty_w))
    bottom = min(offset_y + before_pixels.shape[0], int(dirty_y + dirty_h))
    if right <= left or bottom <= top:
        return True
    x0 = left - offset_x
    y0 = top - offset_y
    return bool(
        np.array_equal(
            before_pixels[y0:y0 + bottom - top, x0:x0 + right - left],
            after_pixels[y0:y0 + bottom - top, x0:x0 + right - left],
        )
    )


def build_texture_editor_checkpoint_record(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    label: str,
    *,
    timestamp: float,
    floating_pixels: Optional[np.ndarray] = None,
    encode_async: bool = True,
) -> Dict[str, object]:
    encode = encode_texture_editor_rgba_blob if encode_async else _compress_texture_editor_rgba
    snapshot = {
        "entry": TextureEditorHistoryEntry(label=label, timestamp=timestamp),
        "document": dataclasses.replace(document),
        "layer_blobs": {
            layer_id: encode(pixels)
            for layer_id, pixels in layer_pixels.items()
        },
    }
    return {
        "entry": snapshot["entry"],
        "command": dataclasses.asdict(
            TextureEditorCommand(kind="checkpoint", label=label, timestamp=timestamp, checkpoint=True)
        ),
        "checkpoint": snapshot,
        "floating_pixels": None if floating_pixels is None else encode(floating_pixels),
    }


def _restore_texture_editor_checkpoint(
    snapshot: object,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], TextureEditorHistoryEntry]:
    if not isinstance(snapshot, dict):
        raise ValueError("Texture Editor checkpoint is invalid.")
    document = snapshot.get("document")
    entry = snapshot.get("entry")
    if not isinstance(document, TextureEditorDocument) or not isinstance(entry, TextureEditorHistoryEntry):
        raise ValueError("Texture Editor checkpoint metadata is invalid.")
    layer_pixels: Dict[str, np.ndarray] = {}
    raw_blobs = snapshot.get("layer_blobs")
    if isinstance(raw_blobs, dict):
        for layer_id, blob in raw_blobs.items():
            decoded = decode_texture_editor_rgba_blob(blob)
            if decoded is not None:
                layer_pixels[str(layer_id)] = decoded
    return dataclasses.replace(document), layer_pixels, entry


def build_texture_editor_delta_history_record(
    *,
    label: str,
    before_document: TextureEditorDocument,
    after_document: TextureEditorDocument,
    before_layer_pixels: Dict[str, object],
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
        if isinstance(before_pixels, TextureEditorHistoryLayerPatch):
            lx0, ly0, width, height = before_pixels.local_bounds
            valid_after = (
                isinstance(after_pixels, np.ndarray)
                and after_pixels.shape == before_pixels.shape
                and lx0 >= 0
                and ly0 >= 0
                and lx0 + width <= after_pixels.shape[1]
                and ly0 + height <= after_pixels.shape[0]
            )
            after_patch = (
                np.ascontiguousarray(after_pixels[ly0:ly0 + height, lx0:lx0 + width])
                if valid_after
                else None
            )
            if after_patch is not None and np.array_equal(before_pixels.pixels, after_patch):
                continue
            before_blobs[layer_id] = _encode_texture_editor_captured_patch(before_pixels)
            if after_patch is None:
                after_blobs[layer_id] = None
            else:
                after_blobs[layer_id] = _encode_texture_editor_captured_patch(
                    TextureEditorHistoryLayerPatch(
                        pixels=after_patch,
                        shape=before_pixels.shape,
                        local_bounds=before_pixels.local_bounds,
                    )
                )
            continue
        if (
            isinstance(before_pixels, np.ndarray)
            and after_pixels is not None
            and _texture_editor_history_pixels_equal(
                after_document,
                layer_id,
                before_pixels,
                after_pixels,
                dirty_bounds,
            )
        ):
            continue
        before_payload = encode_texture_editor_history_layer_state(
            before_document,
            layer_id,
            before_pixels if isinstance(before_pixels, np.ndarray) else None,
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
    max_records = max(1, int(limit))
    if len(updated) > max_records:
        minimum_drop = len(updated) - max_records
        new_oldest = updated[0]
        for drop_index in range(1, minimum_drop + 1):
            new_oldest = _deferred_texture_editor_history_checkpoint(new_oldest, updated[drop_index])
        updated = [new_oldest, *updated[minimum_drop + 1:]]
    return updated, len(updated) - 1


def _deferred_texture_editor_history_checkpoint(
    base_record: Dict[str, object],
    apply_record: Dict[str, object],
) -> Dict[str, object]:
    if "checkpoint" not in base_record:
        raise ValueError("Texture Editor history cannot evict records without a retained checkpoint.")
    entry = apply_record.get("entry")
    if not isinstance(entry, TextureEditorHistoryEntry):
        raise ValueError("Texture Editor history entry is invalid.")
    checkpoint = base_record.get("checkpoint")
    if isinstance(checkpoint, _PendingTextureEditorCheckpoint):
        checkpoint.append(apply_record)
        deferred = checkpoint
    else:
        deferred = _PendingTextureEditorCheckpoint(base_record, apply_record)
    return {
        "entry": entry,
        "command": dataclasses.asdict(
            TextureEditorCommand(
                kind="checkpoint",
                label=entry.label,
                timestamp=float(entry.timestamp),
                checkpoint=True,
            )
        ),
        "checkpoint": deferred,
    }


def texture_editor_applied_history_document_state(
    document: TextureEditorDocument,
    current_layer_pixels: Dict[str, np.ndarray],
    layer_blobs: Dict[str, object],
    *,
    copy_patch_pixels: bool = True,
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
        decoded = decode_texture_editor_history_layer_state(
            new_pixels.get(layer_id),
            blob,
            copy_current=copy_patch_pixels,
        )
        if decoded is not None:
            new_pixels[layer_id] = decoded
    return new_pixels


def texture_editor_history_record_application_state(
    record: Dict[str, object],
    *,
    direction: str,
    current_layer_pixels: Dict[str, np.ndarray],
    copy_patch_pixels: bool = True,
) -> TextureEditorHistoryAppliedState:
    checkpoint = record.get("checkpoint")
    if isinstance(checkpoint, _PendingTextureEditorCheckpoint):
        base_record, apply_records = checkpoint.snapshot()
        state = texture_editor_history_record_application_state(
            base_record,
            direction="after",
            current_layer_pixels={},
            copy_patch_pixels=False,
        )
        for apply_record in apply_records:
            state = texture_editor_history_record_application_state(
                apply_record,
                direction="after",
                current_layer_pixels=state.layer_pixels,
                copy_patch_pixels=False,
            )
        return state
    if checkpoint is not None:
        document, layer_pixels, _entry = _restore_texture_editor_checkpoint(checkpoint)
        floating_blob = record.get("floating_pixels")
        floating_pixels = decode_texture_editor_rgba_blob(floating_blob)
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
        copy_patch_pixels=copy_patch_pixels,
    )
    floating_pixels = decode_texture_editor_rgba_blob(floating_blob)
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
    "TextureEditorHistoryLayerPatch",
    "TextureEditorHistoryReplayPlan",
    "TextureEditorHistoryRestoreState",
    "TextureEditorHistorySelectionState",
    "build_texture_editor_checkpoint_record",
    "build_texture_editor_delta_history_record",
    "capture_texture_editor_history_layer_patch",
    "decode_texture_editor_history_layer_state",
    "decode_texture_editor_rgba_blob",
    "encode_texture_editor_history_layer_state",
    "encode_texture_editor_rgba_blob",
    "shutdown_texture_editor_history_encoder",
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
