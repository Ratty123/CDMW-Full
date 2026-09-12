import struct
from dataclasses import replace

import pytest

from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_replacement_import import initial_replacement_state, prepare_import, compose_import, commit_replacement, set_part_inclusion
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_editor_replacement import source_obj


def static_fixture(extension, levels=1):
    table, record_size = (0x410, 0x218) if extension == "pam" else (0x50, 0x210)
    geometry = table + 2 * record_size * levels
    stride = 20 if levels > 1 else 12
    level_size = 6 * stride + 12
    data = bytearray(geometry + level_size * levels)
    if extension == "pam":
        data[:4] = b"PAR "
        struct.pack_into("<I", data, 0x3c, geometry)
        struct.pack_into("<I", data, 0x10, 2)
        struct.pack_into("<6f", data, 0x14, 0, 0, 0, 1, 1, 1)
    else:
        struct.pack_into("<II", data, 0, levels, geometry)
        struct.pack_into("<6f", data, 0x10, 0, 0, 0, 1, 1, 1)
    for index in range(2):
        record = table + index * record_size
        struct.pack_into("<IIII", data, record, 3, 3, index * 3, index * 3)
        name = f"target{index}".encode()
        texture = name + b".dds"
        data[record + 16:record + 16 + len(texture)] = texture
        data[record + 0x110:record + 0x110 + len(name)] = name
        for vertex, xyz in enumerate(((0, 0, index * 65535), (65535, 0, 0), (0, 65535, 0))):
            offset = geometry + (index * 3 + vertex) * stride
            data[offset:offset + stride] = b"\xff" * stride
            struct.pack_into("<4H2e", data, offset, *xyz, 65535, .5, .5)
    struct.pack_into("<6H", data, geometry + 6 * stride, 0, 1, 2, 2, 1, 0)
    for level in range(1, levels):
        start = table + level * 2 * record_size
        data[start:start + 2 * record_size] = data[table:table + 2 * record_size]
        data[geometry + level * level_size:geometry + (level + 1) * level_size] = data[geometry:geometry + level_size]
    return bytes(data)


@pytest.mark.parametrize("extension", ["pam", "pamlod"])
def test_static_formats_replacement_and_all_exclusion_roundtrip(tmp_path, extension):
    original = static_fixture(extension)
    mesh = parse_mesh(original, f"object/two.{extension}")
    assert len(mesh.submeshes) == 2
    mesh.lod_levels = []  # The editor's asset-to-LOD0 handoff uses one editable level.
    mesh._cdmw_original_data = original
    service = MeshService()
    view = service.open_edit_session(mesh)
    try:
        snapshot = service.capture_export_snapshot(view.session_id)
        key = initial_replacement_state(snapshot).parts[0].part_id
        pending = prepare_import(snapshot, source_obj(tmp_path), target_part_ids=(key,))
        candidate, state = compose_import(pending, (key,))
        commit_replacement(service, snapshot, candidate, state, label="Replace")
        bundle = prepare_replacement_output(service.capture_export_snapshot(view.session_id))
        parsed = parse_mesh(bundle.data, mesh.path)
        assert len(parsed.submeshes) == 2
        for actual, expected in zip(parsed.submeshes[0].vertices, candidate.submeshes[0].vertices):
            assert actual == pytest.approx(expected, abs=.001)
        for actual, expected in zip(parsed.submeshes[1].vertices, mesh.submeshes[1].vertices):
            assert actual == pytest.approx(expected, abs=.001)
        snapshot = service.capture_export_snapshot(view.session_id)
        set_part_inclusion(service, snapshot, [part.part_id for part in state.parts], False)
        hidden = parse_mesh(prepare_replacement_output(service.capture_export_snapshot(view.session_id)).data, mesh.path)
        assert len(hidden.submeshes) == 2
        assert all(len(part.faces) == 1 for part in hidden.submeshes)
    finally:
        service.close_edit_session(view.session_id)


def test_pam_includes_required_paired_lod_and_preserves_untouched_part(tmp_path):
    original = static_fixture("pam")
    mesh = parse_mesh(original, "object/two.pam")
    mesh._cdmw_original_data = original
    service = MeshService()
    view = service.open_edit_session(mesh)
    try:
        snapshot = service.capture_export_snapshot(view.session_id)
        paired = ReplacementFile("object/two.pamlod", static_fixture("pamlod"))
        key = initial_replacement_state(snapshot).parts[0].part_id
        pending = prepare_import(snapshot, source_obj(tmp_path), target_part_ids=(key,), dependencies=(paired,))
        candidate, state = compose_import(pending, (key,))
        bundle = prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=state))
        assert len(bundle.companion_files) == 1
        lod = parse_mesh(bundle.companion_files[0].data, paired.path)
        original_lod = parse_mesh(paired.data, paired.path)
        for actual, expected in zip(lod.submeshes[1].vertices, original_lod.submeshes[1].vertices):
            assert actual == pytest.approx(expected, abs=.001)
        invalid = replace(state, dependencies=(replace(paired, data=b"invalid"),))
        with pytest.raises(ValueError, match="Required companion"):
            prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=invalid))
    finally:
        service.close_edit_session(view.session_id)


@pytest.mark.parametrize("extension", ["pam", "pamlod"])
def test_exclusion_retains_tiny_placeholder_in_lower_lods(tmp_path, extension):
    original = static_fixture(extension, levels=2 if extension == "pamlod" else 1)
    mesh = parse_mesh(original, f"object/two.{extension}")
    mesh._cdmw_original_data = original
    mesh.lod_levels = []
    service = MeshService()
    view = service.open_edit_session(mesh)
    try:
        snapshot = service.capture_export_snapshot(view.session_id)
        paired = ReplacementFile("object/two.pamlod", static_fixture("pamlod", levels=2))
        state = initial_replacement_state(snapshot, dependencies=(paired,) if extension == "pam" else ())
        state = replace(state, parts=tuple(replace(part, included=False) for part in state.parts))
        from cdmw.services.mesh_replacement_import import mesh_with_part_ids
        candidate = mesh_with_part_ids(snapshot, state)
        bundle = prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=state))
        data = bundle.data if extension == "pamlod" else bundle.companion_files[0].data
        result = parse_mesh(data, "object/two.pamlod")
        assert len(result.lod_levels) == 2
        for level in result.lod_levels:
            assert len(level) == 2
            for part in level:
                assert part.faces
                assert max(max(v[axis] for v in part.vertices) - min(v[axis] for v in part.vertices) for axis in range(3)) < .002
    finally:
        service.close_edit_session(view.session_id)
