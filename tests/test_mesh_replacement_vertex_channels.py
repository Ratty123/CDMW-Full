"""Replacement must retain or reject authored vertex channels, never erase them."""

import copy
import struct

import pytest

from cdmw.core.mesh_native import _write_pac_full_rebuild_tables, _write_pac_patch_tables
from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.mesh_pac_builder import _build_pac_full_rebuild, _build_pac_in_place
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_mesh_cloth_influence import apply_rule, shadow_output
from tests.test_mesh_cloth_sequences import all_cloth_fixture
from tests.test_mesh_editor_replacement_sequences import source_variants
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


def _write_uv_case(route, edited, source, tmp_path):
    original = parse_pac(source, edited.path)
    if route == "python_in_place":
        return _build_pac_in_place(original, edited, source)
    if route == "python_full":
        return _build_pac_full_rebuild(original, edited, source)
    if route == "native_in_place":
        return _write_pac_patch_tables(edited, tmp_path)
    return _write_pac_full_rebuild_tables(edited, source, tmp_path)


@pytest.mark.parametrize("route", ["python_in_place", "python_full", "native_in_place", "native_full"])
@pytest.mark.parametrize("uv", [(70000., .5), (.5, -70000.), (float("nan"), 0.), (0., float("inf"))])
def test_pac_uv_writers_reject_overflow_and_nonfinite_values(tmp_path, route, uv):
    source = all_cloth_fixture()
    edited = parse_pac(source, "owned.pac")
    edited.submeshes[0].uvs[0] = uv
    with pytest.raises(ValueError, match="PAC UV for submesh 0 vertex 0.*finite half-float"):
        _write_uv_case(route, edited, source, tmp_path)


@pytest.mark.parametrize("route", ["python_in_place", "python_full", "native_in_place", "native_full"])
@pytest.mark.parametrize("uv", [(65504., -65504.), (.007812, 1.9999)])
def test_pac_uv_writers_accept_finite_edges_and_preserve_rounding(tmp_path, route, uv):
    source = all_cloth_fixture()
    edited = parse_pac(source, "owned.pac")
    edited.submeshes[0].uvs[0] = uv
    before = copy.deepcopy(edited)
    result = _write_uv_case(route, edited, source, tmp_path)
    assert edited == before
    if isinstance(result, bytes):
        assert parse_pac(result).submeshes[0].uvs[0] == struct.unpack("<2e", struct.pack("<2e", *uv))
    else:
        path = tmp_path / ("pac_vertices.tsv" if route == "native_in_place" else "pac_full_vertices.tsv")
        fields = path.read_text().splitlines()[0].split("\t")
        start = 5 if route == "native_in_place" else 7
        assert tuple(map(float, fields[start:start + 2])) == uv


@pytest.mark.parametrize("uv", ["70000 0", "0 -70000"])
def test_import_rejects_unrepresentable_pac_uv_without_erasing_history(tmp_path, monkeypatch, uv):
    source = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "host")
    try:
        apply_rule(host, tmp_path, PacClothRule())
        key = host.state_payload()["cloth"]["parts"][0]["id"]
        path = source_variants(tmp_path / "sources")[0]
        command(host, "replacement_choose", {"scope": "entire", "source_path": str(path)})
        command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        before = shadow_output(host)
        apply_rule(host, tmp_path, PacClothRule(.5))
        redo_output = shadow_output(host)
        command(host, "undo")
        view = host.shadow_service.session_view(host.shadow_session_id)
        path.write_text(path.read_text().replace("vt 1 0", f"vt {uv}"))
        command(host, "replacement_choose", {"scope": "entire", "source_path": str(path)})
        with pytest.raises(ValueError, match="PAC.*UV|UV.*PAC"):
            command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        after = host.shadow_service.session_view(host.shadow_session_id)
        assert after.revision == view.revision
        assert (after.undo_count, after.redo_count) == (view.undo_count, view.redo_count)
        assert shadow_output(host) == before
        command(host, "redo")
        assert shadow_output(host) == redo_output
        assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).original_data == source
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def test_uv_and_normal_edits_keep_imported_cloth_weights_and_packed_colour_bytes(tmp_path, monkeypatch):
    source = bytearray(all_cloth_fixture())
    for lod, level in enumerate(pac_cloth_lods(source)):
        for vertex, offset in enumerate(level.submeshes[0].source_vertex_offsets):
            source[offset + 36:offset + 39] = bytes((35 + vertex, 116 + lod, 198))
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "host")
    try:
        apply_rule(host, tmp_path, PacClothRule(.5))
        key = host.state_payload()["cloth"]["parts"][0]["id"]
        path = source_variants(tmp_path / "sources")[3]
        command(host, "replacement_choose", {"scope": "entire", "source_path": str(path)})
        command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        imported = shadow_output(host)
        selection = {"vertices_by_submesh": {"0": [1]}, "source_indices": []}
        command(host, "mesh_action", {"action": "uv_transform", "selection": selection,
                                      "params": {"offset": [.125, -.25]}})
        uv_output = shadow_output(host)
        assert parse_pac(uv_output).submeshes[0].normals == parse_pac(imported).submeshes[0].normals
        command(host, "mesh_action", {"action": "flip_normals", "selection": {
            "vertices_by_submesh": {}, "source_indices": [0]}, "params": {}})
        edited = shadow_output(host)
        for before, after in zip(pac_cloth_lods(imported), pac_cloth_lods(edited), strict=True):
            original_part, edited_part = before.submeshes[0], after.submeshes[0]
            # Rebuilding flipped faces can reorder their vertices. Compare the
            # complete records by their distinct, unchanged positions.
            original_indices = {point: index for index, point in enumerate(original_part.vertices)}
            assert set(edited_part.vertices) == set(original_indices)
            order = [original_indices[point] for point in edited_part.vertices]
            assert [tuple(order[index] for index in face) for face in edited_part.faces] == [
                (a, c, b)
                for a, b, c in original_part.faces
            ]
            for index, new in enumerate(edited_part.source_vertex_offsets):
                vertex = order[index]
                old = original_part.source_vertex_offsets[vertex]
                assert edited[new + 12:new + 16] == imported[old + 12:old + 16]
                assert edited[new + 20:new + 40] == imported[old + 20:old + 40]
                expected_uv = tuple(value + delta for value, delta in zip(original_part.uvs[vertex], (.125, -.25))) if vertex == 1 else original_part.uvs[vertex]
                assert edited_part.uvs[index] == pytest.approx(expected_uv, abs=.001)
                expected_normal = tuple(-v for v in original_part.normals[vertex])
                assert edited_part.normals[index] == pytest.approx(expected_normal, abs=.004)
        command(host, "undo")
        assert shadow_output(host) == uv_output
        command(host, "redo")
        assert shadow_output(host) == edited
        host.finish(_request(host, "finish_request", 48))
        snapshot = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(snapshot)[0].data == edited
        assert snapshot.original_data == source
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)
