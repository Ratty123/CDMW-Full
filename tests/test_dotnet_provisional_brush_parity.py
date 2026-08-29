from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import tempfile
from uuid import uuid4

import pytest

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


@pytest.mark.parametrize("tool", ("smooth", "inflate", "pinch"))
def test_provisional_brush_matches_native_transaction(tool: str, tmp_path: Path) -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")
    report = _report()
    case = next(item for item in report["cases"] if item["tool"] == tool)
    session_id = f"provisional-parity-{tool}-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(
        _mesh(case),
        session_id,
        timeout_seconds=5.0,
    ) is not None
    native_before_end: list[tuple[float, float, float]] | None = None
    try:
        selection = tuple(int(value) for value in case["selected_vertex_indices"])
        assert mesh_native_core.select_native_mesh_editor_session(
            session_id,
            {"vertices_by_submesh": {0: selection}},
            timeout_seconds=5.0,
        ) is not None
        for event in case["events"]:
            payload = dict(event["payload"])
            phase = str(event["event"]).removeprefix("stroke_")
            if phase == "end":
                native_before_end = _native_vertices(
                    session_id,
                    tmp_path,
                )
            payload["operation"] = "brush"
            result = mesh_native_core.apply_native_mesh_editor_session(
                session_id,
                payload,
                stroke_phase=phase,
                stroke_id=str(payload["stroke_id"]),
                timeout_seconds=10.0,
            )
            assert result is not None, (tool, phase)
        native = _native_vertices(session_id, tmp_path)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    provisional = [tuple(float(value) for value in row) for row in case["vertices_after"]]
    assert len(native) == len(provisional)
    maximum_error = max(
        abs(native_value - provisional_value)
        for native_vertex, provisional_vertex in zip(native, provisional)
        for native_value, provisional_value in zip(native_vertex, provisional_vertex)
    )
    before_end_error = max(
        abs(native_value - provisional_value)
        for native_vertex, provisional_vertex in zip(native_before_end or (), provisional)
        for native_value, provisional_value in zip(native_vertex, provisional_vertex)
    )
    terminal_delta = max(
        abs(native_value - before_end_value)
        for native_vertex, before_end_vertex in zip(native, native_before_end or ())
        for native_value, before_end_value in zip(native_vertex, before_end_vertex)
    )
    tolerance = float(report["position_tolerance"][tool])
    assert maximum_error <= tolerance, {
        "maximum_error": maximum_error,
        "before_end_error": before_end_error,
        "tolerance": tolerance,
    }
    assert terminal_delta <= 1.0e-12


def test_provisional_grab_echo_weights_with_the_active_falloff_profile() -> None:
    """The grab echo uses the native-profile port and the live falloff option."""

    strokes = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.ProvisionalStrokes.cs"
    ).read_text(encoding="utf-8")
    assert "BrushFalloffProfile.Weight(distance, Math.Max(radius, 0.001f), falloff)" in strokes
    assert "FalloffOption(options)" in strokes
    assert "BrushFalloffWeight(" not in strokes
    falloff_option = strokes.split("private static string FalloffOption", 1)[1]
    falloff_option = falloff_option.split("private static bool BoolOption", 1)[0]
    assert "BrushFalloffProfile.Smooth" in falloff_option
    assert ': "smooth"' not in falloff_option
