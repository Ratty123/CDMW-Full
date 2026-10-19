"""Versioned, bounded geometry transport for the resident Rust Mesh Editor.

The wire retains Python float64 values until the existing Rust float32 boundary.
All array spans are admitted before decoding; the geometry fingerprint covers
typed position/index bytes, while the owning FileReference hashes the full file.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Mapping

import numpy as np

from cdmw.services.mesh_rust_contract import (
    RUST_MESH_AUTHORING_PACKAGE,
    RUST_MESH_DOCUMENT_BINARY_CAPABILITY,
)

BINARY_MESH_DOCUMENT_TYPE = RUST_MESH_DOCUMENT_BINARY_CAPABILITY
BINARY_MESH_DOCUMENT_SCHEMA = "cdmw_mesh_document_binary_v1"
BINARY_MESH_DOCUMENT_MAGIC = b"CDMWMSH1"
BINARY_MESH_DOCUMENT_HEADER = struct.Struct("<8sHHI")
BINARY_MESH_DOCUMENT_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
_MAX_VERTICES = 10_000_000
_MAX_INDICES = 60_000_000
_FLOAT32_OVERFLOW = float.fromhex("0x1.ffffffp+127")
_FINGERPRINT_PREFIX = b"cdmw_mesh_document_binary_v1\x00"
_FINGERPRINT_RE = re.compile(r"[0-9A-F]{64}\Z")
_CHANNELS = (
    ("positions", "f64_le", 3, np.dtype("<f8")),
    ("normals", "f64_le", 3, np.dtype("<f8")),
    ("uvs", "f64_le", 2, np.dtype("<f8")),
    ("indices", "u32_le", 1, np.dtype("<u4")),
    ("source_vertex_indices", "i32_le", 1, np.dtype("<i4")),
    ("shader_masks", "f64_le", 3, np.dtype("<f8")),
)
_DOCUMENT_FIELDS = {
    "schema", "format", "source_sha256", "parser", "lod_count_reported", "lods",
    "warnings", "structural_fingerprint",
}
_PART_FIELDS = {
    "name", "material", "source_range", "vertex_stride", "layout",
    *(name for name, *_ in _CHANNELS),
}
_DESCRIPTOR_FIELDS = {"dtype", "components", "count", "offset", "byte_length"}


class BinaryMeshDocumentError(ValueError):
    pass


class BinaryMeshDocumentSizeError(BinaryMeshDocumentError):
    """The encoded document exceeds the owning session's payload byte bound."""


def _object(value: object, keys: set[str], label: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BinaryMeshDocumentError(f"Binary mesh {label} fields do not match version 1")
    return value


def _uint(value: object, maximum: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise BinaryMeshDocumentError(f"Binary mesh {label} is outside its integer range")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise BinaryMeshDocumentError(f"Binary mesh {label} must be text")
    return value


def _validate_metadata(metadata: object, data_length: int, expected_count: int | None) -> None:
    document = _object(metadata, _DOCUMENT_FIELDS, "document")
    if document["schema"] != BINARY_MESH_DOCUMENT_SCHEMA:
        raise BinaryMeshDocumentError("Binary mesh document schema is unsupported")
    if _string(document["format"], "format") not in {"pac", "pam", "pamlod", "preview"}:
        raise BinaryMeshDocumentError("Binary mesh document format is unsupported")
    for name in ("source_sha256", "parser", "structural_fingerprint"):
        _string(document[name], name)
    if _FINGERPRINT_RE.fullmatch(document["structural_fingerprint"]) is None:
        raise BinaryMeshDocumentError("Binary mesh structural fingerprint is invalid")
    _uint(document["lod_count_reported"], 0xFFFFFFFF, "reported LOD count")
    warnings = document["warnings"]
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise BinaryMeshDocumentError("Binary mesh warnings must be a text list")
    lods = document["lods"]
    if not isinstance(lods, list) or not lods or len(lods) > 0xFFFFFFFF:
        raise BinaryMeshDocumentError("Binary mesh document must contain LODs")
    cursor = 0
    part_count = 0
    for lod in lods:
        lod = _object(lod, {"level", "submeshes"}, "LOD")
        _uint(lod["level"], 0xFFFFFFFF, "LOD level")
        parts = lod["submeshes"]
        if not isinstance(parts, list) or len(parts) > 0xFFFFFFFF:
            raise BinaryMeshDocumentError("Binary mesh submeshes must be a list")
        part_count += len(parts)
        for part in parts:
            part = _object(part, _PART_FIELDS, "part")
            for name in ("name", "material", "layout"):
                _string(part[name], name)
            source_range = _object(part["source_range"], {"offset", "length"}, "source range")
            for name in ("offset", "length"):
                _uint(source_range[name], 0xFFFFFFFFFFFFFFFF, f"source {name}")
            _uint(part["vertex_stride"], 0xFFFFFFFF, "vertex stride")
            for name, scalar_type, components, dtype in _CHANNELS:
                descriptor = _object(part[name], _DESCRIPTOR_FIELDS, f"{name} descriptor")
                if descriptor["dtype"] != scalar_type or type(descriptor["components"]) is not int or descriptor["components"] != components:
                    raise BinaryMeshDocumentError(f"Binary mesh {name} scalar type or width does not match")
                count = _uint(descriptor["count"], 0xFFFFFFFFFFFFFFFF, f"{name} count")
                offset = _uint(descriptor["offset"], 0xFFFFFFFFFFFFFFFF, f"{name} offset")
                length = _uint(descriptor["byte_length"], 0xFFFFFFFFFFFFFFFF, f"{name} length")
                # Compare against the remaining bounded file before creating a
                # NumPy view or allocating a decoded native/Python array.
                if (offset != cursor or length != count * components * dtype.itemsize
                        or length > data_length - cursor):
                    raise BinaryMeshDocumentError(f"Binary mesh {name} byte span is invalid")
                cursor += length
            positions = part["positions"]["count"]
            indices = part["indices"]["count"]
            # Keep a fully deleted Part's slot for source/material identity and
            # Undo/Redo. This is authoring state, not export admission.
            empty_authoring_part = document["parser"] == RUST_MESH_AUTHORING_PACKAGE and all(
                part[name]["count"] == 0 for name, *_ in _CHANNELS
            )
            if not empty_authoring_part and not 1 <= positions <= _MAX_VERTICES:
                raise BinaryMeshDocumentError("Binary mesh vertex count is outside the native limit")
            if not empty_authoring_part and (not 3 <= indices <= _MAX_INDICES or indices % 3):
                raise BinaryMeshDocumentError("Binary mesh triangle count is outside the native limit")
            if part["shader_masks"]["count"] not in (0, positions):
                raise BinaryMeshDocumentError("Binary mesh shader mask count does not match vertices")
    if not part_count or expected_count is not None and part_count != expected_count:
        raise BinaryMeshDocumentError("Binary mesh element count does not match")
    if cursor != data_length:
        raise BinaryMeshDocumentError("Binary mesh contains unreferenced trailing bytes")


def _typed_fingerprint(metadata: Mapping, data: memoryview) -> str:
    fingerprint = hashlib.sha256(_FINGERPRINT_PREFIX)
    fingerprint.update(struct.pack("<I", len(metadata["lods"])))
    for lod in metadata["lods"]:
        fingerprint.update(struct.pack("<II", lod["level"], len(lod["submeshes"])))
        for part in lod["submeshes"]:
            fingerprint.update(struct.pack("<QQ", part["positions"]["count"], part["indices"]["count"]))
            for name in ("positions", "indices"):
                descriptor = part[name]
                start = descriptor["offset"]
                fingerprint.update(data[start:start + descriptor["byte_length"]])
    return fingerprint.hexdigest().upper()


def _validate_values(name: str, values: np.ndarray, vertex_count: int) -> None:
    if values.dtype.kind == "f":
        if (not np.isfinite(values).all() or np.any(values >= _FLOAT32_OVERFLOW)
                or np.any(values <= -_FLOAT32_OVERFLOW)):
            raise BinaryMeshDocumentError(f"Binary mesh {name} contains a non-finite native value")
        if name == "shader_masks":
            # Preserve the existing Rust admission rule after f64 -> f32,
            # including values that round to 0 or 1 at that boundary.
            native = values.astype(np.float32)
            if np.any(native < 0) or np.any(native > 1):
                raise BinaryMeshDocumentError("Binary mesh shader masks are outside the native range")
    elif name == "indices" and len(values) and int(values.max()) >= vertex_count:
        raise BinaryMeshDocumentError("Binary mesh triangle references an invalid vertex")


def _encode_channel(source: object, name: str, dtype: np.dtype, components: int, count: int) -> np.ndarray:
    try:
        if dtype.kind in "iu":
            if isinstance(source, range):
                values = np.arange(source.start, source.stop, source.step, dtype=np.int64)
            else:
                values = np.asarray(source)
            if values.ndim != 1 or values.dtype.kind not in "iu":
                # Empty list inference yields float64; it still represents the
                # valid empty optional source-map channel.
                if count == 0 and values.size == 0:
                    values = np.empty(0, dtype=dtype)
                else:
                    raise BinaryMeshDocumentError(f"Binary mesh {name} requires integer values")
            bounds = np.iinfo(dtype)
            if values.size and (int(values.min()) < bounds.min or int(values.max()) > bounds.max):
                raise BinaryMeshDocumentError(f"Binary mesh {name} value is outside its integer range")
            values = np.ascontiguousarray(values, dtype=dtype)
        else:
            if name == "shader_masks" and count:
                raw = np.asarray(source)
                if (raw.dtype.kind not in "iuf" or not isinstance(source, np.ndarray)
                        and any(isinstance(value, (bool, np.bool_)) for row in source for value in row)):
                    raise BinaryMeshDocumentError("Binary mesh shader masks require numeric values")
            values = np.ascontiguousarray(source, dtype=dtype)
            if count == 0 and values.size == 0:
                values = values.reshape(0, components)
        expected_shape = (count,) if components == 1 else (count, components)
        if values.shape != expected_shape:
            raise BinaryMeshDocumentError(f"Binary mesh {name} row width does not match")
        return values
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, BinaryMeshDocumentError):
            raise
        raise BinaryMeshDocumentError(f"Binary mesh {name} values are invalid") from exc


def encode_mesh_document(document: Mapping, *, max_payload_bytes: int = _MAX_PAYLOAD_BYTES) -> bytes:
    """Encode document metadata and borrowed numeric rows without JSON arrays."""
    metadata = {name: document[name] for name in _DOCUMENT_FIELDS - {"schema", "lods", "structural_fingerprint"}}
    metadata.update(schema=BINARY_MESH_DOCUMENT_SCHEMA, lods=[], structural_fingerprint="0" * 64)
    channels = []
    cursor = 0
    for source_lod in document["lods"]:
        lod = {"level": source_lod["level"], "submeshes": []}
        metadata["lods"].append(lod)
        for source_part in source_lod["submeshes"]:
            part = {name: source_part[name] for name in ("name", "material", "source_range", "vertex_stride", "layout")}
            lod["submeshes"].append(part)
            for name, scalar_type, components, dtype in _CHANNELS:
                source = source_part.get(name, ()) if name == "shader_masks" else source_part[name]
                count = len(source)
                length = count * components * dtype.itemsize
                part[name] = dict(dtype=scalar_type, components=components, count=count, offset=cursor, byte_length=length)
                cursor += length
                if cursor > max_payload_bytes:
                    raise BinaryMeshDocumentSizeError("Mesh payload exceeds the 512 MiB session limit")
                channels.append((part, name, source, dtype, components, count))
    _validate_metadata(metadata, cursor, expected_count=None)
    metadata_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(metadata_bytes) > BINARY_MESH_DOCUMENT_MAX_METADATA_BYTES:
        raise BinaryMeshDocumentError("Binary mesh metadata exceeds the 16 MiB limit")
    data_start = BINARY_MESH_DOCUMENT_HEADER.size + len(metadata_bytes)
    if data_start + cursor > max_payload_bytes:
        raise BinaryMeshDocumentSizeError("Mesh payload exceeds the 512 MiB session limit")
    result = bytearray(data_start + cursor)
    data = memoryview(result)[data_start:]
    for part, name, source, dtype, components, count in channels:
        values = _encode_channel(source, name, dtype, components, count)
        _validate_values(name, values, part["positions"]["count"])
        descriptor = part[name]
        start = descriptor["offset"]
        if descriptor["byte_length"]:
            data[start:start + descriptor["byte_length"]] = memoryview(values).cast("B")
    metadata["structural_fingerprint"] = _typed_fingerprint(metadata, data)
    final_metadata = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(final_metadata) != len(metadata_bytes):
        raise BinaryMeshDocumentError("Binary mesh metadata changed size while preparing")
    result[:BINARY_MESH_DOCUMENT_HEADER.size] = BINARY_MESH_DOCUMENT_HEADER.pack(BINARY_MESH_DOCUMENT_MAGIC, 1, 0, len(final_metadata))
    result[BINARY_MESH_DOCUMENT_HEADER.size:data_start] = final_metadata
    return bytes(result)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BinaryMeshDocumentError("Binary mesh metadata contains a duplicate field")
        value[key] = item
    return value


def decode_mesh_document(data: bytes, *, expected_count: int | None = None, max_payload_bytes: int = _MAX_PAYLOAD_BYTES) -> dict:
    """Read version 1 with the same geometry admission limits as Rust JSON."""
    if len(data) > max_payload_bytes or len(data) < BINARY_MESH_DOCUMENT_HEADER.size:
        raise BinaryMeshDocumentError("Binary mesh payload size is invalid")
    magic, version, flags, metadata_length = BINARY_MESH_DOCUMENT_HEADER.unpack_from(data)
    if magic != BINARY_MESH_DOCUMENT_MAGIC or version != 1 or flags != 0:
        raise BinaryMeshDocumentError("Binary mesh header or version is unsupported")
    if not 1 <= metadata_length <= BINARY_MESH_DOCUMENT_MAX_METADATA_BYTES:
        raise BinaryMeshDocumentError("Binary mesh metadata size is invalid")
    data_start = BINARY_MESH_DOCUMENT_HEADER.size + metadata_length
    if data_start > len(data):
        raise BinaryMeshDocumentError("Binary mesh metadata is truncated")
    try:
        metadata = json.loads(data[BINARY_MESH_DOCUMENT_HEADER.size:data_start].decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BinaryMeshDocumentError("Binary mesh metadata is not valid UTF-8 JSON") from exc
    _validate_metadata(metadata, len(data) - data_start, expected_count)
    raw = memoryview(data)[data_start:]
    if _typed_fingerprint(metadata, raw) != metadata["structural_fingerprint"]:
        raise BinaryMeshDocumentError("Binary mesh structural fingerprint does not match")
    decoded_channels = []
    for lod in metadata["lods"]:
        for part in lod["submeshes"]:
            for name, _, components, dtype in _CHANNELS:
                descriptor = part[name]
                values = np.frombuffer(raw, dtype=dtype, count=descriptor["count"] * components, offset=descriptor["offset"])
                if components != 1:
                    values = values.reshape(descriptor["count"], components)
                _validate_values(name, values, part["positions"]["count"])
                decoded_channels.append((part, name, values))
    for part, name, values in decoded_channels:
        part[name] = values.tolist()
    metadata.pop("schema")
    return metadata
