"""Owned single-root weapons: collider geometry, output, history and inputs."""

from contextlib import ExitStack
from dataclasses import replace
import math
import struct
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import _parse_par_sections, parse_pac
from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides
from cdmw.modding.pac_weapon_collisions import create_weapon_colliders, preview_weapon_colliders, weapon_collision_layout
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac
from tests.test_mesh_jiggle_decoded_preview import decoded
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_cloth_influence import shadow_output
from tests.test_mesh_jiggle_decoded_preview import rig_session
from tests.test_mesh_cloth_decoded_preview import collision_session
from tests.test_mesh_jiggle import jiggle_session


def weapon_fixture(*, parts=2):
    source = guide_free_pac(parts=parts)
    old = decode_pac_embedded_volumes(source)
    palette = old.file_offset - 24 - 2 - 4*len(old.bone_palette)
    bounds = old.file_offset - 24
    identity = tuple(float(i//4 == i%4) for i in range(16))
    name = b"B_Weapon_0001"
    bone = (struct.pack("<IB", PALETTE[0], len(name)) + name + struct.pack("<i", -1)
            + struct.pack("<64f3f4f3f", *(identity*4), 1, 1, 1, 0, 0, 0, 1, 0, 0, 0))
    block = struct.pack("<I", 1) + bone + b"\x01" + struct.pack("<HI", 1, PALETTE[0])
    result = bytearray(source[:palette] + block + source[bounds:])
    delta = len(result) - len(source)
    struct.pack_into("<I", result, 80, 0x41)
    struct.pack_into("<2I", result, 16, 0, _parse_par_sections(source)[0]["size"] + delta)
    for i in range(8):
        offset = 85 + 4*i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", source, offset)[0] + delta)
    for level in pac_cloth_lods(result):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                struct.pack_into("<2I", result, offset+20, 0, 0)
                result[offset+28:offset+34] = bytes((255, 0, 0, 0, 0, 0))
    return bytes(result)


def test_embedded_weapon_bones_locate_empty_and_generated_collision_sets():
    source = weapon_fixture()
    decoded = decode_pac_embedded_volumes(source)
    assert decoded.bone_palette == (PALETTE[0],)
    assert decoded.model_bones[0].name == "B_Weapon_0001"
    assert decoded.volumes == ()
    output = create_weapon_colliders(source)
    volumes = decode_pac_embedded_volumes(output)
    assert [v.flags for v in volumes.volumes] == [0, 1, 0, 1]
    assert all(v.bone_key == PALETTE[0] and v.usage == 1 and v.shape_type == 5 for v in volumes.volumes)
    assert create_weapon_colliders(output) == output
    before, after = _parse_par_sections(source), _parse_par_sections(output)
    assert all(source[a["offset"]:a["offset"]+a["size"]] == output[b["offset"]:b["offset"]+b["size"]]
               for a, b in zip(before[1:], after[1:]))
    assert source[decoded.file_end:80+before[0]["size"]] == output[volumes.file_end:80+after[0]["size"]]


def test_weapon_reference_geometry_and_contacts_follow_placement_without_changing_cloak(collision_session, tmp_path):
    from cdmw.services.mesh_rust_authoring import read_owned_payload_reference

    _, session, host = collision_session
    source = weapon_fixture()
    weapon = tmp_path / "sword.pac"
    weapon.write_bytes(source)
    output = shadow_output(host)
    history = (len(session.undo_stack), len(session.redo_stack))

    command(host, "cloth_collision_input", {"role": "weapon", "path": str(weapon)})
    before = read_owned_payload_reference(host.root, decoded(host)["file"])
    mesh = before["weapon_reference"]
    assert mesh["positions"] and mesh["indices"]
    assert max(mesh["indices"]) < len(mesh["positions"])
    assert mesh["collider_count"] == len(before["cloth"]["weapon_colliders"])
    assert mesh["placement"] == {"offset": [0., 0., 0.], "rotation": [0., 0., 0.]}
    assert not host.state_payload()["weapon_collisions"]["available"]
    command(host, "cloth_collision_input", {"weapon_placement": {
        "offset": [1., 2., 3.], "rotation": [0., 0., 90.]}})
    placed = read_owned_payload_reference(host.root, decoded(host)["file"])
    assert placed["weapon_reference"]["placement"] == {"offset": [1., 2., 3.], "rotation": [0., 0., 90.]}
    for a, b in zip(mesh["positions"], placed["weapon_reference"]["positions"]):
        assert b == pytest.approx([1. - a[1], 2. + a[0], 3. + a[2]])
    for a, b in zip(before["cloth"]["weapon_colliders"], placed["cloth"]["weapon_colliders"]):
        for key in ("center1", "center2"):
            assert b[key] == pytest.approx([1. - a[key][1], 2. + a[key][0], 3. + a[key][2]])
    host.jiggle_source_cache = None
    assert read_owned_payload_reference(host.root, decoded(host)["file"])["weapon_reference"] == placed["weapon_reference"]
    command(host, "cloth_collision_input", {"clear": True})
    assert read_owned_payload_reference(host.root, decoded(host)["file"])["weapon_reference"] is None
    assert shadow_output(host) == output
    assert (len(session.undo_stack), len(session.redo_stack)) == history
    assert weapon.read_bytes() == source
