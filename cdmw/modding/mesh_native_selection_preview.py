from __future__ import annotations

from array import array
import ctypes
import dataclasses
from importlib import import_module
import json
import math
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult
from cdmw.modding.mesh_native_core_constants import (
    Face,
    NATIVE_MESH_CORE_BACKEND_ID,
    NATIVE_MESH_CORE_BINARY_NAME,
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    Vec2,
    Vec3,
    _NATIVE_MATERIAL_REPORT_ATTRS,
    _NATIVE_MESH_EDITOR_NORMAL_OPERATIONS,
    _NATIVE_MESH_SESSION_TOKEN_ATTR,
    _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS,
    _TRANSIENT_NATIVE_SUBMESH_ATTRS,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import RunCancelled


def _proxy(name: str):
    def call(*args, **kwargs):
        return getattr(import_module("cdmw.modding.mesh_native_core"), name)(*args, **kwargs)

    return call

_edge_list = _proxy("_edge_list")
_index = _proxy("_index")
_int_list = _proxy("_int_list")
_native_binary_descriptor = _proxy("_native_binary_descriptor")


def _native_selection_preview_group(value: Mapping[str, object], source_submesh_index: int) -> dict[str, object] | None:
    source_vertex_indices = _int_list(value.get("source_vertex_indices"))
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    source_vertex_count = len(source_vertex_indices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    if source_vertex_count <= 0:
        return None
    group: dict[str, object] = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": source_submesh_index,
    }
    if source_vertex_indices:
        group["source_vertex_indices"] = source_vertex_indices
    source_vertices_binary = _native_binary_descriptor(
        raw_source_vertices_binary,
        expected_count=source_vertex_count,
        components=1,
        kind="i32",
    )
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)

    source_edges = _edge_list(value.get("source_edges"))
    raw_source_edges_binary = value.get("source_edges_binary")
    source_edge_count = len(source_edges)
    if source_edge_count == 0 and isinstance(raw_source_edges_binary, Mapping):
        source_edge_count = _index(raw_source_edges_binary.get("count")) or 0
    if source_edges:
        group["source_edges"] = [[left, right] for left, right in source_edges]
    source_edges_binary = _native_binary_descriptor(
        raw_source_edges_binary,
        expected_count=source_edge_count,
        components=2,
        kind="i32",
    )
    if source_edges_binary is not None:
        group["source_edges_binary"] = source_edges_binary

    source_face_indices = _int_list(value.get("source_face_indices"))
    raw_source_faces_binary = value.get("source_face_indices_binary")
    source_face_count = len(source_face_indices)
    source_face_start = _index(value.get("source_face_start"))
    source_face_range_count = _index(value.get("source_face_count"))
    has_source_face_range = (
        source_face_start is not None
        and source_face_start >= 0
        and source_face_range_count is not None
        and source_face_range_count > 0
    )
    if source_face_count == 0 and isinstance(raw_source_faces_binary, Mapping):
        source_face_count = _index(raw_source_faces_binary.get("count")) or 0
    if source_face_count == 0 and has_source_face_range:
        source_face_count = int(source_face_range_count or 0)
    if source_face_indices:
        group["source_face_indices"] = source_face_indices
    source_faces_binary = _native_binary_descriptor(
        raw_source_faces_binary,
        expected_count=source_face_count,
        components=1,
        kind="i32",
    )
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
    elif has_source_face_range:
        group["source_face_start"] = int(source_face_start or 0)
        group["source_face_count"] = int(source_face_range_count or 0)
    return group
