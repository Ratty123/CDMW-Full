"""Cloth paint on an imported model reaches the built PAC as template-guide bindings."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
from cdmw.services.new_item_cloth_paint import (
    apply_import_cloth_paint, import_cloth_paint_samples, mesh_has_cloth_paint, part_cloth_paint,
)
from tests.test_pac_cloth_paint import cloth_template

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def imported(vertices, paint):
    part = SubMesh(name="dress", material="cloth", vertices=list(vertices),
                   faces=[(0, 1, 2), (1, 3, 2)][:max(1, len(vertices) - 2)])
    part.cloth_paint = list(paint)
    return ParsedMesh(format="obj", submeshes=[part])


def test_paint_is_read_only_when_it_fits_the_vertices():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (0., 1., 2.))
    assert part_cloth_paint(mesh.submeshes[0]) == [0., 1., 1.]
    mesh.submeshes[0].cloth_paint = [1.]
    assert part_cloth_paint(mesh.submeshes[0]) == [] and not mesh_has_cloth_paint(mesh)


def test_samples_follow_the_placement_matrix_and_unpainted_parts_count_as_bones():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (1., 1., 1.))
    other = SubMesh(name="belt", vertices=[(5., 5., 5.)], faces=[])
    mesh.submeshes.append(other)
    moved = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 10., 0., 0., 1.)
    samples = import_cloth_paint_samples(mesh, moved)
    assert samples.positions[1] == (11., 0., 0.) and samples.positions[-1] == (15., 5., 5.)
    assert samples.values == (1., 1., 1., 0.)


def test_paint_survives_copies_and_transforms():
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), (0., .5, 1.))
    target = SubMesh(name="copy")
    copy_extra_submesh_attrs(mesh.submeshes[0], target)
    assert target.cloth_paint == [0., .5, 1.]
    moved = _copy_submesh_with_transform(mesh.submeshes[0], IDENTITY)
    assert moved.cloth_paint == [0., .5, 1.]


def test_service_rewrites_the_built_pac_and_reports_it():
    data = cloth_template()
    dress = pac_cloth_lods(data)[0].submeshes[1]
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert apply_import_cloth_paint(result, imported(dress.vertices, [1.] * len(dress.vertices)), IDENTITY)
    for offset in dress.source_vertex_offsets:
        assert decode_pac_cloth_binding(result.rebuilt_data, offset)[0] == 0
    assert "Cloth paint:" in result.summary_lines[-1] and "test in game" in result.summary_lines[-1]
    untouched = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert not apply_import_cloth_paint(untouched, imported(dress.vertices, [0.] * len(dress.vertices)), IDENTITY)
    assert untouched.rebuilt_data == data and not untouched.summary_lines


def test_misplaced_paint_is_refused_instead_of_painting_the_wrong_vertices():
    data = cloth_template()
    dress = pac_cloth_lods(data)[0].submeshes[1]
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    far = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 50., 0., 0., 1.)
    with pytest.raises(ValueError, match="does not line up with"):
        apply_import_cloth_paint(result, imported(dress.vertices, [1.] * len(dress.vertices)), far)
    assert result.rebuilt_data == data


def test_real_static_build_with_the_new_item_placement_lines_up_with_the_hook_matrix():
    # The New Item hook places samples with ModelPlacement.matrix(); the builder places
    # geometry with ModelPlacement.build_transform(). Run the real geometry build.
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.modding.static_mesh_build import build_static_mesh_replacement
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions, StaticSubmeshMapping
    from cdmw.ui.new_item.model_import import ModelPlacement

    raw = cloth_template()
    original = parse_pac(raw, "cloth.pac")
    template = pac_cloth_lods(raw)[0].submeshes[1]
    origin = (0., 0., 0.)
    placement = ModelPlacement(offset=(.25, 0., .5), rotation=(0., 0., 90.))
    inverse = _inverse_rows(placement.matrix(origin=origin))
    vertices = [_row(point, inverse) for point in template.vertices]
    mesh = imported(vertices, [1.] * len(vertices))
    mesh.submeshes[0].uvs = [(0., 0.)] * len(vertices)
    options = StaticMeshReplacementOptions(
        complete_external_swap=True,
        transform=placement.build_transform(origin=origin),
        submesh_mappings=[StaticSubmeshMapping(index, part.name, [0] if index == 1 else [], index)
                          for index, part in enumerate(original.submeshes)],
    )
    output, report = build_static_mesh_replacement(raw, original, mesh, options)
    assert not report.errors
    result = SimpleNamespace(rebuilt_data=output, summary_lines=[])
    assert apply_import_cloth_paint(result, mesh, placement.matrix(origin=origin))
    bound = [decode_pac_cloth_binding(result.rebuilt_data, offset)
             for level in pac_cloth_lods(result.rebuilt_data) for offset in level.submeshes[1].source_vertex_offsets]
    assert bound and all(binding is not None and binding[0] == 0 for binding in bound)


def _row(point, m):
    x, y, z = point
    return (x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14])


def _inverse_rows(m):
    import numpy as np
    return tuple(float(v) for v in np.linalg.inv(np.asarray(m, dtype=float).reshape(4, 4)).reshape(16))


def test_mesh_editor_sets_cloth_paint_on_the_selection_with_undo_and_redo():
    from cdmw.domain.mesh.editing import MeshEditSelection
    from cdmw.services.mesh_service import MeshService

    service = MeshService()
    mesh = imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.)), ())
    sid = service.open_edit_session(mesh).session_id
    try:
        session = service._session(sid)
        session.selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 3)})
        assert service.set_selected_vertex_cloth_paint(sid, .75) == 2
        assert session.working_mesh.submeshes[0].cloth_paint == [0., .75, 0., .75]
        assert service.set_selected_vertex_cloth_paint(sid, .75) == 0  # no-op leaves history alone
        service.undo(sid)
        assert part_cloth_paint(service._session(sid).working_mesh.submeshes[0]) in ([], [0.] * 4)
        service.redo(sid)
        assert service._session(sid).working_mesh.submeshes[0].cloth_paint == [0., .75, 0., .75]
        with pytest.raises(ValueError, match="between 0 and 1"):
            service.set_selected_vertex_cloth_paint(sid, 2)
    finally:
        service.close_edit_session(sid)
