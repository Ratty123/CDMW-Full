"""Owned PABV and PAC volume sets: resize, move, copy and remove, byte for byte."""

import hashlib
import struct

import pytest

from cdmw.domain.mesh.collision_volumes import (
    MODEL_SOURCE, CollisionVolumeChange, CollisionVolumeCopy, CollisionVolumeEdit,
)
from cdmw.modding.collision_volume_edit import (
    HEAD_BONE_HASH, apply_pabv_volume_edit, apply_pac_volume_edit, pabv_volume_set, pac_volume_set,
    volume_rows,
)
from cdmw.modding.mesh_parser import _parse_par_sections
from cdmw.modding.pabv_parser import decode_pabv, decode_pac_embedded_volumes
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_pabv_parser import IDENTITY, container, record

PATH = "character/model/1_pc/1_phm/phm_01.pabv"
POINTS = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.))
FACES = ((0, 1, 2), (1, 3, 2))


def moved(x, y, z):
    return (*IDENTITY[:12], x, y, z, 1.)


def body():
    return container(
        record(5, (.1, .4), key=0x11111111, flags=6),
        record(4, (.2,), key=HEAD_BONE_HASH, matrix=moved(0, 1.6, 0), flags=0),
        record(0, (.1, .2, .3), key=0x22222222, flags=8),
        record(2, key=0x33333333, vertices=POINTS[:3], indices=(0, 1, 2), flags=0),
        flags=3,
    )


def edit(data, *, changes=(), copies=(), source=PATH):
    return CollisionVolumeEdit(source, hashlib.sha256(data).hexdigest(), tuple(changes), tuple(copies))


def pac_with_volumes(volumes, *, lods=3):
    """A guide-free owned PAC whose metadata carries ``volumes`` after the bounds."""
    metadata = bytearray(struct.pack("<IB", 0, lods) + bytes(8 * lods) + struct.pack("<H", 1))
    name = b"part0"
    metadata += bytes((len(name),)) + name + bytes((len(name),)) + name
    descriptor = bytearray(40 + 6 * lods)
    descriptor[0] = 1
    struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 0)
    descriptor[35:36 + lods] = bytes((lods, *range(lods)))
    geometry, indices = [bytearray() for _ in range(lods)], [bytearray() for _ in range(lods)]
    for lod in range(lods):
        struct.pack_into("<H", descriptor, 40 + 2 * lod, 4)
        struct.pack_into("<I", descriptor, 40 + 2 * lods + 4 * lod, 6)
        for x, y, _ in POINTS:
            vertex = bytearray(40)
            struct.pack_into("<3H", vertex, 0, round(x * 32767), round(y * 32767), 0)
            vertex[6:20] = bytes.fromhex("1234003400380000003c00000040")
            struct.pack_into("<2I", vertex, 20, 1 << 10 | 0xc0000000, 0x80000000)
            vertex[28:32] = bytes((128, 127, 0, 0))
            vertex[36:40] = bytes((52, 73, 255, 0xff))
            geometry[lod] += vertex
        indices[lod] += struct.pack("<6H", *(i for f in FACES for i in f))
    metadata += descriptor
    metadata += struct.pack("<H2I6f", 2, 0x11111111, 0x22222222, 0, 0, 0, 4, 1, 0)
    metadata += struct.pack("<H", len(volumes)) + b"".join(volumes)
    metadata += bytes(13)
    header = bytearray(80)
    header[:8] = b"PAR \x03\x09\0\x01"
    cursor, payloads = 80 + len(metadata), []
    for lod in reversed(range(lods)):
        struct.pack_into("<I", metadata, 5 + 4 * lod, cursor)
        struct.pack_into("<I", metadata, 5 + 4 * lods + 4 * lod, cursor + len(geometry[lod]))
        payloads.append(bytes(geometry[lod] + indices[lod]))
        cursor += len(payloads[-1])
    for slot, payload in enumerate((metadata, *payloads)):
        struct.pack_into("<2I", header, 16 + 8 * slot, 0, len(payload))
    return bytes(header + metadata) + b"".join(payloads)


def pac_edit(data, **kwargs):
    model = decode_pac_embedded_volumes(data)
    block = data[model.file_offset:model.file_end]
    return CollisionVolumeEdit(MODEL_SOURCE, hashlib.sha256(block).hexdigest(),
                               tuple(kwargs.get("changes", ())), tuple(kwargs.get("copies", ())))


PAC_VOLUMES = (record(5, (.05, .3), key=0x11111111, flags=0), record(4, (.1,), key=0x22222222, flags=1))


def test_resize_and_move_rewrite_only_those_floats():
    data = body()
    result = apply_pabv_volume_edit(data, PATH, edit(data, changes=[
        CollisionVolumeChange(0, parameters=(.05, .3)), CollisionVolumeChange(1, position=(0., 1.5, .1))]))
    before, after = decode_pabv(data).volumes, decode_pabv(result).volumes
    assert len(result) == len(data)
    assert after[0].parameters == pytest.approx((.05, .3)) and after[0].local_matrix == before[0].local_matrix
    assert after[1].local_matrix[12:15] == pytest.approx((0., 1.5, .1)) and after[1].parameters == before[1].parameters
    assert after[1].local_matrix[:12] == before[1].local_matrix[:12]
    for old, new in zip(before, after):
        assert (new.bone_key, new.usage, new.serialized_shape, new.flags) == (old.bone_key, old.usage, old.serialized_shape, old.flags)
    changed = [i for i, (a, b) in enumerate(zip(data, result)) if a != b]
    span0, span1 = before[0].file_offset, before[1].file_offset
    assert all(span0 + 70 <= i < span0 + 78 or span1 + 52 <= i < span1 + 64 for i in changed)
    assert after[2:] == before[2:]


def test_copy_duplicates_bone_flags_and_orientation_and_remove_drops_record():
    data = body()
    result = apply_pabv_volume_edit(data, PATH, edit(data, changes=[CollisionVolumeChange(2, removed=True)],
                                                  copies=[CollisionVolumeCopy(0, (.08, .5), (0., .2, 0.))]))
    before, after = decode_pabv(data).volumes, decode_pabv(result).volumes
    assert [v.bone_key for v in after] == [0x11111111, HEAD_BONE_HASH, 0x33333333, 0x11111111]
    copy = after[-1]
    assert (copy.flags, copy.usage, copy.serialized_shape) == (6, before[0].usage, 5)
    assert copy.parameters == pytest.approx((.08, .5)) and copy.local_matrix[12:15] == pytest.approx((0., .2, 0.))
    assert after[3].file_end == len(result) and decode_pabv(result).flags == 3


def test_mesh_volumes_move_but_do_not_resize():
    data = body()
    moved_mesh = apply_pabv_volume_edit(data, PATH, edit(data, changes=[CollisionVolumeChange(3, position=(1., 2., 3.))]))
    mesh = decode_pabv(moved_mesh).volumes[3]
    assert mesh.vertices == POINTS[:3] and mesh.local_matrix[12:15] == (1., 2., 3.)
    with pytest.raises(ValueError, match="mesh; it can be moved but not resized"):
        apply_pabv_volume_edit(data, PATH, edit(data, changes=[CollisionVolumeChange(3, parameters=(1.,))]))


@pytest.mark.parametrize("change, message", [
    (CollisionVolumeChange(0, parameters=(.1,)), "takes 2 size value"),
    (CollisionVolumeChange(1, parameters=(.1, .2)), "takes 1 size value"),
    (CollisionVolumeChange(9, position=(0., 0., 0.)), "does not exist"),
    (CollisionVolumeChange(1, removed=True), "Keep a Bip01 Head volume"),
])
def test_invalid_edits_are_refused(change, message):
    data = body()
    with pytest.raises(ValueError, match=message):
        apply_pabv_volume_edit(data, PATH, edit(data, changes=[change]))


def test_stale_or_foreign_edits_are_refused():
    data = body()
    stale = edit(data, changes=[CollisionVolumeChange(0, parameters=(.1, .2))])
    with pytest.raises(ValueError, match="changed since it was edited"):
        apply_pabv_volume_edit(data[:-4] + struct.pack("<I", 9), PATH, stale)
    with pytest.raises(ValueError, match="belong to another source"):
        apply_pabv_volume_edit(data, "character/other.pabv", stale)


def test_last_volume_cannot_be_removed_and_limit_is_enforced():
    data = container(record(5, (.1, .4), flags=0), flags=2)
    with pytest.raises(ValueError, match="at least one"):
        apply_pabv_volume_edit(data, PATH, edit(data, changes=[CollisionVolumeChange(0, removed=True)]))
    with pytest.raises(ValueError, match="at most 128"):
        apply_pabv_volume_edit(data, PATH, edit(data, copies=[CollisionVolumeCopy(0)] * 128))


@pytest.mark.parametrize("values", [
    {"parameters": (0.,)}, {"parameters": (-1.,)}, {"parameters": (float("nan"),)},
    {"parameters": (1., 2., 3., 4.)}, {"position": (0., 0.)}, {"position": (0., 0., 1e9)},
])
def test_rule_validation(values):
    with pytest.raises(ValueError):
        CollisionVolumeChange(0, **values)


def test_rule_round_trips_and_rejects_bad_sources():
    data = body()
    value = edit(data, changes=[CollisionVolumeChange(0, parameters=(.1, .2)), CollisionVolumeChange(2, removed=True)],
                 copies=[CollisionVolumeCopy(1, position=(0., 1., 0.))])
    assert CollisionVolumeEdit.from_dict(value.to_dict()) == value
    for source in ("C:/x.pabv", "../x.pabv", "/x.pabv", "x.pac", "a\\b.pabv"):
        with pytest.raises(ValueError):
            CollisionVolumeEdit(source, "0" * 64, (CollisionVolumeChange(0, removed=True),))
    with pytest.raises(ValueError, match="once, in order"):
        CollisionVolumeEdit(PATH, "0" * 64, (CollisionVolumeChange(1, removed=True), CollisionVolumeChange(0, removed=True)))


@pytest.mark.parametrize("lods", [2, 3, 4])
def test_pac_set_grows_and_shrinks_with_relocated_geometry(lods):
    data = pac_with_volumes(PAC_VOLUMES, lods=lods)
    before_lods = pac_cloth_lods(data)
    grown = apply_pac_volume_edit(data, pac_edit(data, changes=[CollisionVolumeChange(0, parameters=(.04, .25))],
                                                   copies=[CollisionVolumeCopy(1, (.12,), (0., .5, 0.))]))
    assert len(grown) == len(data) + len(PAC_VOLUMES[1])
    after = decode_pac_embedded_volumes(grown)
    assert [v.bone_key for v in after.volumes] == [0x11111111, 0x22222222, 0x22222222]
    assert after.volumes[2].flags == 1 and after.volumes[0].parameters == pytest.approx((.04, .25))
    for old, new in zip(before_lods, pac_cloth_lods(grown)):
        assert [p.vertices for p in old.submeshes] == [p.vertices for p in new.submeshes]
        assert [p.faces for p in old.submeshes] == [p.faces for p in new.submeshes]
    assert [s["size"] for s in _parse_par_sections(grown)[1:]] == [s["size"] for s in _parse_par_sections(data)[1:]]
    shrunk = apply_pac_volume_edit(grown, pac_edit(grown, changes=[CollisionVolumeChange(1, removed=True),
                                                                   CollisionVolumeChange(2, removed=True)]))
    assert len(shrunk) == len(data) - len(PAC_VOLUMES[1])
    assert [v.bone_key for v in decode_pac_embedded_volumes(shrunk).volumes] == [0x11111111]
    for old, new in zip(before_lods, pac_cloth_lods(shrunk)):
        assert [p.vertices for p in old.submeshes] == [p.vertices for p in new.submeshes]


def test_pac_edit_keeps_bytes_outside_the_set():
    data = pac_with_volumes(PAC_VOLUMES)
    result = apply_pac_volume_edit(data, pac_edit(data, changes=[CollisionVolumeChange(1, position=(0., 2., 0.))]))
    assert len(result) == len(data)
    model = decode_pac_embedded_volumes(data)
    changed = [i for i, (a, b) in enumerate(zip(data, result)) if a != b]
    span = model.volumes[1].file_offset
    assert changed and all(span + 52 <= i < span + 64 for i in changed)


def test_pac_edit_refuses_undecoded_trailers_and_stale_sets():
    data = pac_with_volumes(PAC_VOLUMES)
    value = pac_edit(data, changes=[CollisionVolumeChange(0, parameters=(.1, .2))])
    other = apply_pac_volume_edit(data, pac_edit(data, changes=[CollisionVolumeChange(1, position=(0., 2., 0.))]))
    with pytest.raises(ValueError, match="changed since it was edited"):
        apply_pac_volume_edit(other, value)
    with pytest.raises(ValueError):
        apply_pac_volume_edit(data, CollisionVolumeEdit(PATH, value.source_sha256, value.changes))


def test_pac_without_volumes_can_add_none_and_rows_describe_each_volume():
    data = pac_with_volumes(PAC_VOLUMES)
    rows = volume_rows(pac_volume_set(data), bone_names={0x11111111: "Bip01 Spine"})
    assert [(r["shape"], r["bone"], r["resizable"]) for r in rows] == [("capsule", "Bip01 Spine", True), ("sphere", "", True)]
    assert rows[0]["parameters"] == pytest.approx([.05, .3]) and rows[1]["flags"] == 1
    rows = volume_rows(pabv_volume_set(body(), PATH))
    assert [r["shape"] for r in rows] == ["capsule", "sphere", "box", "mesh"] and not rows[3]["resizable"]
    assert rows[1]["position"] == pytest.approx([0., 1.6, 0.])
