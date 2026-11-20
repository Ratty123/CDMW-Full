"""Static models (PAM, PAMLOD) through Export, Open Package, Vertex Parameters and Finish."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_native_availability import native_mesh_core_available
from cdmw.modding.mesh_parser import parse_pam, parse_pamlod
from tests.static_mesh_fixtures import shipped_pamlod, two_part_pam
from tests.test_static_mesh_archive_decode import pamlod_payload

_CASES = {
    "pam": ("object/stone.pam", two_part_pam, parse_pam),
    "pamlod": ("object/stone.pamlod", shipped_pamlod, parse_pamlod),
    "pamlod_flat_records": ("object/stone.pamlod", lambda: pamlod_payload(materials=2)[1], parse_pamlod),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_static_parts_carry_their_parse_order_source_map(case):
    path, payload, parser = _CASES[case]
    mesh = parser(payload(), path)
    for level in [mesh.submeshes, *(mesh.lod_levels or [])]:
        for part in level:
            assert part.source_vertex_map == list(range(len(part.vertices)))
            assert len(part.source_vertex_offsets) == len(part.vertices)


needs_native = pytest.mark.skipif(not native_mesh_core_available(), reason="needs the native mesh core")


def _open(tmp_path: Path, case: str):
    from cdmw.services import mesh_rust_authoring as authoring
    from cdmw.services.mesh_service import MeshService
    from tests.test_mesh_rust_authoring import _Settings

    path, payload, _parser = _CASES[case]
    source = tmp_path / "src" / Path(path).name
    source.parent.mkdir(parents=True)
    source.write_bytes(payload())
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    mesh = service.load_mesh_file(source, run_roundtrip=True)
    view = service.open_edit_session(mesh, session_id="static-return", mode="edit")
    controller = SimpleNamespace(mesh_service=service, active_session_id=view.session_id)
    authoring.prime_rust_mesh_preview_context(
        controller, None, material_package_path=None, unavailable_reason="",
        target_entry=None, entries_by_basename=None, physics_profile_context=None,
    )
    session = authoring.RustMeshAuthoringSession.create(
        controller, tmp_path / "session", process_generation=7, theme={"density": "compact", "scale": 1.0},
    )
    return service, session


def _run(session, request_id, command, **arguments):
    from tests.test_mesh_rust_authoring import _request

    request = _request(session, "command_request", request_id)
    request.update(command=command, arguments=arguments)
    return session.run_command(request)


def _finish_and_rebuild(service, session, request_id):
    from tests.test_mesh_rust_authoring import _request

    assert session.finish(_request(session, "finish_request", request_id))["status"] == "accepted"
    snapshot = service.capture_export_snapshot("static-return")
    assert service.validate_export_snapshot(snapshot).ok
    return service.rebuild_result_from_snapshot(snapshot)


@needs_native
@pytest.mark.parametrize("format_name", ["obj", "glb"])
@pytest.mark.parametrize("case", ["pam", "pamlod", "pamlod_flat_records"])
@pytest.mark.parametrize("move", [False, True])
def test_export_then_open_package_then_finish(tmp_path, case, format_name, move):
    from tests.test_mesh_rust_authoring import _move_exported_vertex

    path, payload, parser = _CASES[case]
    service, session = _open(tmp_path, case)
    try:
        target = tmp_path / "export" / f"edited.{format_name}"
        _run(session, 1, "export_mesh", path=str(target), format=format_name)
        if move:
            _move_exported_vertex(target, format_name, delta=0.1)
        _run(session, 2, "import_editable_package", path=str(target))
        rebuilt, _report = _finish_and_rebuild(service, session, 3)
    finally:
        session.cancel()
    original, result = parser(payload(), path), parser(rebuilt.data, path)
    assert [[len(part.vertices) for part in level] for level in (result.lod_levels or [result.submeshes])] == [
        [len(part.vertices) for part in level] for level in (original.lod_levels or [original.submeshes])
    ]
    moved = result.submeshes[0].vertices[0][0] - original.submeshes[0].vertices[0][0]
    assert moved == pytest.approx(0.1 if move else 0.0, abs=1e-3)


@needs_native
@pytest.mark.parametrize("case", ["pam", "pamlod"])
def test_vertex_parameters_edit_static_positions_and_uvs(tmp_path, case):
    from cdmw.services.mesh_vertex_parameters import inspection_token

    path, payload, parser = _CASES[case]
    service, session = _open(tmp_path, case)
    try:
        selection = {"vertices_by_submesh": {"0": [0, 1, 2]}, "edges_by_submesh": {},
                     "faces_by_submesh": {}, "source_indices": []}
        _run(session, 1, "select", selection=selection)
        _run(session, 2, "vertex_edit", token=inspection_token(session), edits={
            "position": {"mode": "offset", "values": [0.01, 0.0, 0.0]},
            "uv0": {"mode": "offset", "values": [0.05, 0.0]},
        })
        rebuilt, report = _finish_and_rebuild(service, session, 3)
    finally:
        session.cancel()
    assert {"positions", "uv0"} <= set(report.changed_channels)
    original, result = parser(payload(), path).submeshes[0], parser(rebuilt.data, path).submeshes[0]
    assert result.vertices[1][0] - original.vertices[1][0] == pytest.approx(0.01, abs=1e-3)
    assert result.uvs[1][0] - original.uvs[1][0] == pytest.approx(0.05, abs=1e-3)
