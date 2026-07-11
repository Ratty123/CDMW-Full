from __future__ import annotations

import json

import struct

import tempfile

import unittest

import zlib

from pathlib import Path

from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MeshEditSelection

from cdmw.domain.mesh.skeleton import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
)

from cdmw.modding.skeleton_parser import Bone, Skeleton

from cdmw.services.asset_authoring_service import (
    ASSET_AUTHORING_MESH_HEALTH_SCHEMA,
    ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA,
    ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
    ASSET_AUTHORING_UV_REPORT_SCHEMA,
)

from cdmw.services.mesh_texture_sources import MeshTextureSourceResolution

from cdmw.modding.mesh_native_core import (
    clear_native_mesh_core_fallback_counts,
    native_mesh_core_available,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
    record_native_mesh_core_fallback,
)

from cdmw.rendering.native_d3d11_host import find_native_d3d11_host

from cdmw.ui.mesh_editor.native_preview_payloads import (
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_to_native_preview,
)

from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS

from cdmw.ui.mesh_editor.native_preview_runtime import (
    mesh_editor_native_preview_command,
    mesh_editor_write_native_preview_package,
)

from cdmw.models import ArchiveEntry

from tools.mesh_editor_dev_harness import (
    _build_two_part_synthetic_mesh,
    _coverage_command,
    _papr_constraint_metadata_summary,
    _png_capture_summary,
    _real_archive_papr_read_status,
    _real_game_mesh_evidence,
    _resolve_real_archive_mesh_textures,
    _sample_real_archive_paa_playback,
    _selection_edges_from_group,
    _selection_faces_from_group,
    _sequence_event_marker_overlap,
    _sequence_lane_pair_summary,
    _sequence_path_record_context,
    _sequence_reference_overlap,
    _sequence_timeline_field_overlap,
    _sequence_timeline_field_semantic_aliases,
    build_native_benchmark_mesh,
    build_synthetic_mesh,
    run_scenario,
)

from tools.mesh_harness.scenario_registry import scenario_metadata, scenario_names

from tools.mesh_harness.sparse_update_soak import (
    SPARSE_SOAK_UPDATE_COUNT,
    SPARSE_SOAK_VERTEX_COUNT,
    build_sparse_update_soak_mesh,
)

def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)

def _write_rgb_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
)

def _i32_descriptor_values(group: dict[str, object], json_key: str, binary_key: str) -> list[int]:
    raw_json = group.get(json_key)
    raw_descriptor = group.get(binary_key)
    if isinstance(raw_json, list) and (raw_json or not isinstance(raw_descriptor, dict)):
        return [int(value) for value in raw_json]
    if "vertex" in json_key:
        start_key, count_key = "source_vertex_start", "source_vertex_count"
    elif "face" in json_key:
        start_key, count_key = "source_face_start", "source_face_count"
    else:
        start_key, count_key = "", ""
    try:
        raw_start = group.get(start_key, -1)
        raw_count = group.get(count_key, 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        start, count = -1, 0
    if start >= 0 and count > 0:
        return list(range(start, start + count))
    if not isinstance(raw_descriptor, dict) or not str(raw_descriptor.get("path") or "").strip():
        return []
    path = Path(str(raw_descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 4:
        return []
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))

def _f64_descriptor_values(group: dict[str, object], json_key: str, binary_key: str) -> list[float]:
    raw_json = group.get(json_key)
    if isinstance(raw_json, list):
        return [float(value) for value in raw_json]
    raw_descriptor = group.get(binary_key)
    if not isinstance(raw_descriptor, dict):
        return []
    path = Path(str(raw_descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 8:
        return []
    return list(struct.unpack("<" + "d" * (len(data) // 8), data))

def _edge_descriptor_values(group: dict[str, object]) -> list[list[int]]:
    raw_json = group.get("source_edges")
    if isinstance(raw_json, list):
        return [[int(edge[0]), int(edge[1])] for edge in raw_json if isinstance(edge, list) and len(edge) >= 2]
    values = _i32_descriptor_values(group, "source_edges", "source_edges_binary")
    return [[values[index], values[index + 1]] for index in range(0, len(values) - 1, 2)]


def _mesh_core_source() -> str:
    root = Path("native/cdmw_mesh_core/src")
    paths = [root / "main.cpp", *sorted((root / "owners").glob("*.cpp"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)

if __name__ == "__main__":
    unittest.main()
