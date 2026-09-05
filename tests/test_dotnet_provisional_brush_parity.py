from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import tempfile


from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "bin"
    / "Release"
    / "net10.0-windows"
    / "cdmw-mesh-dotnet-editor.dll"
)


def _report() -> dict[str, object]:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-provisional-brush-parity-") as temp_dir:
        report = Path(temp_dir) / "parity.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-provisional-brush-parity",
                "--provisional-brush-parity-report",
                str(report),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return json.loads(report.read_text(encoding="utf-8"))


def _mesh(case: dict[str, object]) -> ParsedMesh:
    vertices = [tuple(float(value) for value in row) for row in case["vertices_before"]]
    normals = [tuple(float(value) for value in row) for row in case["normals"]]
    faces = [tuple(int(value) for value in row) for row in case["faces"]]
    submesh = SubMesh(
        name="parity_grid",
        material="parity",
        texture="",
        vertices=vertices,
        normals=normals,
        uvs=[(0.0, 0.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )
    return ParsedMesh(
        path="provisional-parity.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=len(faces),
        has_uvs=True,
    )


def _native_vertices(session_id: str, temp_dir: Path) -> list[tuple[float, float, float]]:
    output = temp_dir / f"{session_id}.vertices.bin"
    report = mesh_native_core.export_native_mesh_editor_session_snapshot(
        session_id,
        [{"index": 0, "vertices_output_path": str(output)}],
        timeout_seconds=5.0,
    )
    assert report is not None
    return [tuple(values) for values in struct.iter_unpack("=ddd", output.read_bytes())]
