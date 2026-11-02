"""Strict PAB documents round-trip byte for byte and refuse edits they cannot keep consistent."""

import math
import struct

import pytest

from cdmw.core.archive_hkx import build_pab_preview
from cdmw.modding import skeleton_writer
from cdmw.modding.pabv_parser import decode_pab_embedded_volumes, resolve_pabv_bones
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.modding.skeleton_writer import (
    PabEditRefused,
    PabFormatError,
    append_child_bone,
    pab_bone_name_hash,
    pab_layout_summary,
    read_pab_document,
    rename_bone,
    write_pab_document,
)
from cdmw.services.pab_skeleton_edit_service import (
    PAB_APPEND_NOTES,
    PabAppendEdit,
    PabRenameEdit,
    apply_pab_edits,
)
from tests.test_pabv_parser import record

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
HEAD_HASH = 0xA23A288E  # "Bip01 Head", the interned key traced in the executable


def translated(matrix, x, y, z=0.):
    return (*matrix[:12], x, y, z, 1.)


# Root turned 90 degrees about z at (10, 20, 0); children offset along local x.
ROOT = (0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 10., 20., 0., 1.)
ROOT_INVERSE = (0., -1., 0., 0., 1., 0., 0., 0., 0., 0., 1., 0., -20., 10., 0., 1.)
HALF = math.sqrt(.5)
BONES = (
    ("Bip01", -1, ROOT, ROOT_INVERSE, ROOT, ROOT_INVERSE, (0., 0., HALF, HALF), (10., 20., 0.)),
    ("Bip01 Spine", 0, translated(ROOT, 10., 22.), translated(ROOT_INVERSE, -22., 10.),
     translated(IDENTITY, 2., 0.), translated(IDENTITY, -2., 0.), (0., 0., 0., 1.), (2., 0., 0.)),
    ("Bip01 Head", 1, translated(ROOT, 10., 25.), translated(ROOT_INVERSE, -25., 10.),
     translated(IDENTITY, 3., 0.), translated(IDENTITY, -3., 0.), (0., 0., 0., 1.), (3., 0., 0.)),
)


def pab(flags=0x17, *, bones=BONES, hashes=None, sets=None, secondary=(-1, 0, 1), core=(1, 1, 0)):
    data = bytearray(b"PAR \x01\x05" + bytes(range(10)) + struct.pack("<IH", flags, len(bones)))
    for index, (name, parent, *matrices, rotation, position) in enumerate(bones):
        encoded = name.encode("ascii")
        name_hash = hashes[index] if hashes else pab_bone_name_hash(name)
        data += struct.pack("<IB", name_hash, len(encoded)) + encoded
        data += struct.pack("<i64f3f4f3f", parent, *(v for m in matrices for v in m), 1., 1., 1.,
                            *rotation, *position)
    if flags & 0x10:
        data += struct.pack(f"<{len(bones)}i", *secondary)
    if flags & 0x2:
        data += bytes(core)
    extra = {"flags": 0} if flags & 0x4 else {}
    if sets is None:
        sets = ((record(5, (.1, .3), key=HEAD_HASH, usage=1, **extra), record(1, (.2, .4), key=1, **extra)),
                (record(5, (.1, .3), key=HEAD_HASH, usage=0, **extra),),
                (record(2, key=HEAD_HASH, usage=2, vertices=((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)),
                        indices=(0, 1, 2), **extra),)) if flags else ((),)
    for records in sets:
        data += struct.pack("<H", len(records)) + b"".join(records)
    return bytes(data)


def close(left, right, tolerance=1e-5):
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def multiply(left, right):
    return tuple(sum(left[r * 4 + k] * right[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4))


@pytest.mark.parametrize("flags", [0x00, 0x05, 0x07, 0x15, 0x17, 0x1F])
def test_every_shipped_variant_reads_every_byte_and_writes_it_back(flags):
    data = pab(flags)
    document = read_pab_document(data, "owned.pab")
    assert write_pab_document(document) == data
    assert len(document.volume_sets) == (3 if flags else 1)
    assert (document.secondary_parents is None) == (not flags & 0x10)
    assert (document.core_flags is None) == (not flags & 0x2)
    assert pab_layout_summary(data)[0].endswith("writes back byte for byte")


def test_bone_hash_is_the_case_sensitive_pa_checksum():
    assert pab_bone_name_hash("Bip01 Head") == HEAD_HASH
    assert pab_bone_name_hash("bip01 head") != HEAD_HASH


@pytest.mark.parametrize("fault", ["version", "flag bit", "trailing", "truncated array", "name", "nan"])
def test_strict_reader_names_the_first_unexplained_byte(fault):
    data = bytearray(pab())
    if fault == "version":
        data[5] = 6
    elif fault == "flag bit":
        data[16] |= 0x20
    elif fault == "trailing":
        data += b"\x00"
    elif fault == "truncated array":
        data = pab(0x10, sets=())
    elif fault == "name":
        data[27] = 0xE9  # first character of "Bip01"
    elif fault == "nan":
        struct.pack_into("<f", data, 32 + 4, math.nan)
    with pytest.raises(PabFormatError):
        read_pab_document(bytes(data))
    assert pab_layout_summary(bytes(data))[0].startswith("Exact layout: not decoded")


def test_appended_child_keeps_existing_bytes_indices_and_volume_bindings():
    data = pab()
    source = read_pab_document(data)
    edited = append_child_bone(source, "Bip01 Head", "Cape_00", position=(0., -.5, 0.),
                               rotation=(0., 0., HALF, HALF), scale=(1., 2., 1.))
    output = write_pab_document(edited)
    bones_end = parse_pab(data).tail_offset
    assert output[22:bones_end] == data[22:bones_end]
    assert struct.unpack_from("<H", output, 20)[0] == 4
    cape = edited.bones[3]
    assert (cape.parent_index, cape.name_hash) == (2, pab_bone_name_hash("Cape_00"))
    assert edited.secondary_parents == (-1, 0, 1, 2)
    assert edited.core_flags == bytes((1, 1, 0, 0))
    head = source.bones[2]
    assert close(multiply(cape.local_bind_matrix, head.bind_matrix), cape.bind_matrix)
    assert close(multiply(cape.bind_matrix, cape.inv_bind_matrix), IDENTITY)
    assert close(multiply(cape.local_bind_matrix, cape.inv_local_bind_matrix), IDENTITY)
    # 90 degrees about z, y doubled: local x row = (0, 1, 0), y row = (-2, 0, 0).
    assert close(cape.local_bind_matrix, (0., 1., 0., 0., -2., 0., 0., 0., 0., 0., 1., 0., 0., -.5, 0., 1.))
    rig = parse_pab(output)
    assert rig.parser_mode == "fixed" and not rig.parse_warning and len(rig.bones) == 4
    before, after = decode_pab_embedded_volumes(parse_pab(data)), decode_pab_embedded_volumes(rig)
    for old, new in zip((before.primary, before.rendering, before.physics),
                        (after.primary, after.rendering, after.physics), strict=True):
        assert resolve_pabv_bones(new, rig) == resolve_pabv_bones(old, parse_pab(data))
    reread = read_pab_document(output)
    assert reread.bones == edited.bones and write_pab_document(reread) == output


@pytest.mark.parametrize("fault", [
    "duplicate name", "hash collision", "non-ascii", "rotation", "scale", "core under plain parent",
    "secondary after self", "bone limit", "volume key becomes index", "unknown parent",
])
def test_append_refuses_edits_that_would_break_the_rig(fault, monkeypatch):
    document = read_pab_document(pab())
    kwargs = {}
    name, parent = "Cape_00", "Bip01 Head"
    if fault == "duplicate name":
        name = "Bip01 Spine"
    elif fault == "hash collision":
        document = read_pab_document(pab(hashes=(pab_bone_name_hash("Bip01"), pab_bone_name_hash("Cape_00"),
                                                 HEAD_HASH)))
    elif fault == "non-ascii":
        name = "Capeé"
    elif fault == "rotation":
        kwargs["rotation"] = (0., 0., 0., 2.)
    elif fault == "scale":
        kwargs["scale"] = (1., 0., 1.)
    elif fault == "core under plain parent":
        kwargs["core_flag"] = 1
    elif fault == "secondary after self":
        kwargs["secondary_parent"] = 3
    elif fault == "bone limit":
        monkeypatch.setattr(skeleton_writer, "PAB_MAX_BONES", 3)
    elif fault == "volume key becomes index":
        document = read_pab_document(pab(sets=((record(5, key=3, flags=0),), (), ())))
    elif fault == "unknown parent":
        parent = "Tail_00"
    with pytest.raises(PabEditRefused):
        append_child_bone(document, parent, name, **kwargs)


def test_rename_recomputes_the_hash_and_the_volume_keys_that_use_it():
    document = read_pab_document(pab())
    renamed = rename_bone(document, "Bip01 Head", "Bip01 Head_Renamed")
    new_hash = pab_bone_name_hash("Bip01 Head_Renamed")
    assert renamed.bones[2].name_hash == new_hash
    keys = [[volume.bone_key for volume in item.volumes] for item in renamed.volume_sets]
    assert keys == [[new_hash, 1], [new_hash], [new_hash]]  # key 1 is an index and stays
    rig = parse_pab(write_pab_document(renamed))
    volumes = decode_pab_embedded_volumes(rig)
    assert resolve_pabv_bones(volumes.primary, rig) == (2, 1)
    with pytest.raises(PabEditRefused, match="outside this skeleton"):
        rename_bone(document, "Bip01 Head", "Head2", protected_hashes={HEAD_HASH})
    foreign = read_pab_document(pab(hashes=(1 << 20, pab_bone_name_hash("Bip01 Spine"), HEAD_HASH)))
    with pytest.raises(PabEditRefused, match="PA checksum"):
        rename_bone(foreign, "Bip01", "Root")


def test_service_appends_and_renames_only_added_bones():
    data = pab()
    outcome = apply_pab_edits(data, (
        PabAppendEdit("Bip01 Spine", "Cape_00", position=(0., -.2, 0.)),
        PabAppendEdit("Cape_00", "Cape_01", position=(0., -.3, 0.)),
        PabRenameEdit("Cape_01", "Cape_End"),
    ))
    assert (outcome.source_bone_count, outcome.bone_count) == (3, 5)
    assert outcome.appended == ("Cape_00", "Cape_End")
    assert outcome.notes == PAB_APPEND_NOTES
    rig = parse_pab(outcome.data)
    assert [bone.name for bone in rig.bones[3:]] == ["Cape_00", "Cape_End"]
    assert rig.bones[4].parent_index == 3
    with pytest.raises(PabEditRefused, match="source skeleton"):
        apply_pab_edits(data, (PabRenameEdit("Bip01 Head", "Head"),))
    assert apply_pab_edits(data, ()).data == data


def test_an_appended_bone_can_enter_a_pac_palette():
    from cdmw.modding.pac_palette_extension import extend_pac_palette, palette_layout
    from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac

    bones = tuple((f"bone{i}", -1, IDENTITY, IDENTITY, IDENTITY, IDENTITY, (0., 0., 0., 1.), (0., 0., 0.))
                  for i in range(len(PALETTE)))
    data = pab(0x17, bones=bones, hashes=PALETTE, secondary=(-1,) * len(PALETTE), core=(1,) * len(PALETTE),
               sets=((), (), ()))
    rig = parse_pab(apply_pab_edits(data, (PabAppendEdit("bone0", "Cape_00"),)).data)
    output, _contract = extend_pac_palette(guide_free_pac(), rig, ("Cape_00",))
    assert palette_layout(output)[3] == PALETTE + (pab_bone_name_hash("Cape_00"),)


def test_archive_browser_preview_reports_the_exact_layout():
    detail = build_pab_preview(pab(), "owned.pab").detail_lines
    assert "Exact layout: flags 0x17, 3 volume set(s); writes back byte for byte" in detail
    assert "Secondary parents: 0 of 3 differ from the hierarchy parent" in detail
    assert "Core bones: 2 of 3" in detail
    assert "Volumes per set: 2, 1, 1" in detail
