from __future__ import annotations

import json
import struct
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_native_uv import native_mesh_auto_uv_report
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_importer import import_scene_mesh_with_report


def _write_missing_uv_source(root: Path, suffix: str, *, incomplete_uv: bool = False) -> Path:
    if suffix == ".obj":
        path = root / "triangle.obj"
        path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        return path
    if suffix == ".dae":
        path = root / "triangle.dae"
        path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <library_geometries><geometry id="geo"><mesh>
    <source id="positions"><float_array id="positions-array" count="9">0 0 0 1 0 0 0 1 0</float_array><technique_common><accessor source="#positions-array" count="3" stride="3"/></technique_common></source>
    <vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
    <triangles count="1"><input semantic="VERTEX" source="#vertices" offset="0"/><p>0 1 2</p></triangles>
  </mesh></geometry></library_geometries>
</COLLADA>
""",
            encoding="utf-8",
        )
        return path

    positions = struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    uvs = struct.pack("<4f", 0.0, 0.0, 1.0, 0.0) if incomplete_uv else b""
    indices = struct.pack("<3H", 0, 1, 2)
    payload = positions + uvs + indices
    buffer_views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}]
    attributes = {"POSITION": 0}
    if uvs:
        buffer_views.append({"buffer": 0, "byteOffset": len(positions), "byteLength": len(uvs)})
        accessors.append({"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC2"})
        attributes["TEXCOORD_0"] = 1
    buffer_views.append({"buffer": 0, "byteOffset": len(positions) + len(uvs), "byteLength": len(indices)})
    accessors.append({"bufferView": len(buffer_views) - 1, "componentType": 5123, "count": 3, "type": "SCALAR"})
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "triangle.bin", "byteLength": len(payload)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [{"primitives": [{"attributes": attributes, "indices": len(accessors) - 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if suffix == ".glb":
        document["buffers"][0].pop("uri")
        json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
        json_chunk += b" " * ((-len(json_chunk)) % 4)
        bin_chunk = payload + (b"\0" * ((-len(payload)) % 4))
        path = root / "triangle.glb"
        path.write_bytes(
            struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_chunk) + 8 + len(bin_chunk))
            + struct.pack("<II", len(json_chunk), 0x4E4F534A)
            + json_chunk
            + struct.pack("<II", len(bin_chunk), 0x004E4942)
            + bin_chunk
        )
        return path
    (root / "triangle.bin").write_bytes(payload)
    path = root / "triangle.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize("suffix", [".obj", ".dae", ".gltf", ".glb"])
def test_external_missing_uv_import_generates_complete_uvs(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = _write_missing_uv_source(tmp_path, suffix)

    def apply_auto_uv(mesh, indices, **kwargs):
        assert indices == {0}
        assert kwargs["allow_topology_change"] is True
        submesh = mesh.submeshes[0]
        submesh.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        return {0: range(3)}

    with patch("cdmw.modding.scene_import_uv.apply_native_mesh_auto_uv", side_effect=apply_auto_uv):
        result = import_scene_mesh_with_report(source, include_external_audit=False)

    submesh = result.mesh.submeshes[0]
    assert len(submesh.uvs) == len(submesh.vertices) == result.mesh.total_vertices
    assert len(submesh.normals) == len(submesh.vertices)
    assert result.mesh.total_faces == len(submesh.faces) == 1
    assert result.mesh.has_uvs is True
    assert "bundled xatlas auto-unwrap" in " ".join(result.diagnostics)
    assert "Review required" in " ".join(result.diagnostics)
    assert "inspect the generated islands and seams before export" in " ".join(result.diagnostics)


@pytest.mark.parametrize("suffix", [".obj", ".dae", ".gltf", ".glb"])
def test_external_missing_uv_import_blocks_when_native_unwrap_fails(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = _write_missing_uv_source(tmp_path, suffix)

    with (
        patch("cdmw.modding.scene_import_uv.apply_native_mesh_auto_uv", return_value=None),
        pytest.raises(ValueError, match="missing or incomplete UVs") as exc_info,
    ):
        import_scene_mesh_with_report(source, include_external_audit=False)

    message = str(exc_info.value)
    assert "bundled xatlas auto-unwrap was unavailable or failed" in message
    assert "export OBJ/DAE/GLB/glTF with a complete TEXCOORD_0/UV channel" in message


def test_external_uv_generation_preserves_cancellation(tmp_path: Path) -> None:
    source = _write_missing_uv_source(tmp_path, ".obj")
    stop_event = threading.Event()

    def cancel_during_unwrap(_mesh, _indices, **kwargs):
        assert kwargs["stop_event"] is stop_event
        stop_event.set()
        return None

    with (
        patch("cdmw.modding.scene_import_uv.apply_native_mesh_auto_uv", side_effect=cancel_during_unwrap),
        pytest.raises(RunCancelled, match="cancelled during UV generation"),
    ):
        import_scene_mesh_with_report(source, include_external_audit=False, stop_event=stop_event)


def test_external_incomplete_uv_length_triggers_generation(tmp_path: Path) -> None:
    source = _write_missing_uv_source(tmp_path, ".gltf", incomplete_uv=True)

    def complete_uvs(mesh, _indices, **_kwargs):
        submesh = mesh.submeshes[0]
        assert submesh.uvs == []
        submesh.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        return {0: range(3)}

    with patch("cdmw.modding.scene_import_uv.apply_native_mesh_auto_uv", side_effect=complete_uvs):
        result = import_scene_mesh_with_report(source, include_external_audit=False)

    assert len(result.mesh.submeshes[0].uvs) == len(result.mesh.submeshes[0].vertices)
    assert "Review required" in " ".join(result.diagnostics)


def test_native_auto_uv_forwards_and_preserves_cancellation() -> None:
    stop_event = threading.Event()
    mesh = ParsedMesh(
        submeshes=[
            SubMesh(
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
            )
        ]
    )

    with (
        patch("cdmw.modding.mesh_native_uv.find_native_mesh_core_binary", return_value=Path("cdmw-mesh-core.exe")),
        patch("cdmw.modding.mesh_native_uv._ensure_native_mesh_session_submesh", return_value=None),
        patch("cdmw.modding.mesh_native_uv._run_native_mesh_core_job", side_effect=RunCancelled("cancelled")) as run_job,
        pytest.raises(RunCancelled, match="cancelled"),
    ):
        native_mesh_auto_uv_report(mesh, {0}, stop_event=stop_event)

    assert run_job.call_args.kwargs["stop_event"] is stop_event


def test_external_uv_generation_blocks_lost_vertex_channel(tmp_path: Path) -> None:
    source = _write_missing_uv_source(tmp_path, ".obj")

    def drop_normals(mesh, _indices, **_kwargs):
        submesh = mesh.submeshes[0]
        submesh.uvs = [(0.0, 0.0)] * len(submesh.vertices)
        submesh.normals = []
        return {0: range(len(submesh.vertices))}

    with (
        patch("cdmw.modding.scene_import_uv.apply_native_mesh_auto_uv", side_effect=drop_normals),
        pytest.raises(ValueError, match="could not preserve vertex-aligned channels"),
    ):
        import_scene_mesh_with_report(source, include_external_audit=False)
