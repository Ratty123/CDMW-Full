"""Small explicit facial bindings and ambiguous PAC metadata."""

import struct
from types import SimpleNamespace

from cdmw.modding.mesh_parser import resolve_pac_bone_palette


def _data(*palettes):
    return b"\0" * 16 + b"".join(
        struct.pack("<H" + "I" * len(palette), len(palette), *palette) + b"\0" * 16
        for palette in palettes
    )


def _skeleton(*hashes):
    return SimpleNamespace(bones=[SimpleNamespace(name_hash=value) for value in hashes])


def test_single_explicit_eye_bone_resolves_against_selected_skeleton():
    assert resolve_pac_bone_palette(_data((0xB3123456,)), _skeleton(0xA1234567, 0xB3123456)) == (1,)


def test_short_table_with_unmatched_hash_is_rejected():
    assert resolve_pac_bone_palette(_data((0xB3123456,)), _skeleton(0xA1234567)) == ()


def test_conflicting_equal_length_tables_are_rejected():
    assert resolve_pac_bone_palette(_data((0xB3123456,), (0xA1234567,)),
                                    _skeleton(0xA1234567, 0xB3123456)) == ()


def test_duplicate_table_is_unambiguous_and_longest_complete_table_wins():
    skeleton = _skeleton(0xA1234567, 0xB3123456)
    assert resolve_pac_bone_palette(_data((0xB3123456,), (0xB3123456,)), skeleton) == (1,)
    assert resolve_pac_bone_palette(_data((0xB3123456,), (0xA1234567,),
                                         (0xB3123456, 0xA1234567)), skeleton) == (1, 0)
