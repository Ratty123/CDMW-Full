"""Gates for grafting a component element from one prefab into another."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.prefab_binary import KIND_COLLECTION, KIND_OBJECT, KIND_POINTER, KIND_STRING, decode_prefab_binary  # noqa: E402
from cdmw.core.prefab_binary_edit import PrefabEditError  # noqa: E402
from cdmw.core.prefab_component_graft import (  # noqa: E402
    encode_prefab_type,
    encode_transform,
    find_component_elements,
    graft_prefab_component,
)


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


def _type(name: str, *members: bytes) -> bytes:
    return _text(name) + struct.pack("<H", len(members)) + b"".join(members)


def _pointer_header(mask: int, type_index: int) -> bytes:
    return struct.pack("<H", 1) + bytes((mask, type_index, 0, 0))


class _Blob:
    """Writes blob bytes with self-relative pointers, the way the shipped files are laid out."""

    def __init__(self, base: int) -> None:
        self.base = base
        self.out = bytearray()

    @property
    def here(self) -> int:
        return self.base + len(self.out)

    def pointer(self, owner: bytes = b"\xff" * 8) -> int:
        self.out += owner
        self.out += struct.pack("<I", self.here + 4)
        return self.here  # pointee start

    def length_field(self, pointee_start: int) -> None:
        self.out += struct.pack("<I", self.here - pointee_start)


def build_prefab(*, component: str, member_kind: str, value: str, with_transform: bool = False, owner: bytes = b"\x00" * 8, pointee_type: str = "Path", preamble: bytes = b"") -> bytes:
    """A root SceneObject whose `_components` holds one element of `component`.

    `member_kind` is "string" (a `staticstringA` member, the `_shrinkTag` shape),
    "pointer" (a `ReflectObjectPtr` member with the leading presence byte and a pointee
    holding a `_path`: the SkinnedMeshComponent's `_skinnedMeshFile` shape) or "object"
    (a `ReflectObject` member: the EffectComponent's `_effectFileName` shape, whose
    pointee is followed by a byte). `with_transform` puts a 40-byte `Transform` member
    first. Every element ends with its name-length field, as the shipped files do.
    """

    members = []
    if with_transform:
        members.append(_member("_offsetTransform", "Transform", 0, 40))
    if member_kind == "string":
        members.append(_member("_label", "staticstringA", KIND_STRING, 1))
    elif member_kind == "pointer":
        members.append(_member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8))
    else:
        members.append(_member("_ref", "ReflectObject", KIND_OBJECT, 8))
    types = bytearray()
    types += _type("SceneObject", _member("_components", "ReflectObjectPtr", KIND_COLLECTION, 0))
    types += _type(component, *members)
    type_count = 2
    if member_kind != "string":
        types += _type(pointee_type, _member("_path", "NormalizedPathA", KIND_STRING, 1))
        type_count += 1

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", type_count) + types
    pool = struct.pack("<I", 0)
    base = len(header) + len(pool) + 28

    blob = _Blob(base)
    blob.out += struct.pack("<H", 2) + (0b1).to_bytes(6, "little")   # root: _components selected
    blob.out += b"\x00" + struct.pack("<I", 1)                        # collection: kind, count
    blob.out += preamble                                              # an object list's preamble, if any
    mask = 0b11 if with_transform else 0b1
    blob.out += _pointer_header(mask, 1)                              # element header: mask, type 1
    name_start = blob.pointer(owner)
    blob.out += struct.pack("<HHH", 0, 1, 0) + _text(f"{component}_0")
    if with_transform:
        blob.out += struct.pack("<10f", 0.7, 0.7, 0.7, 0.0, 0.0, 0.7071, 0.7071, 0.0, 0.0, 0.0)
    if member_kind == "string":
        blob.out += _text(value)
    else:
        if member_kind == "pointer":
            blob.out += b"\x01"                                          # the pointer's presence byte
        blob.out += _pointer_header(0b1, 2)                           # pointee header: _path selected, type 2
        pointee = blob.pointer()
        blob.out += struct.pack("<I", 0) + _text(value)
        blob.length_field(pointee)
        if member_kind == "object":
            blob.out += b"\x01"
    blob.length_field(name_start)
    blob.out += b"\x01"                                               # terminator
    data_header = struct.pack("<III", 1, base + len(blob.out), 0) + struct.pack("<Q", 0xFFFFFFFFFFFFFFFF) + struct.pack("<II", base, len(blob.out))
    return bytes(header + pool + data_header + blob.out)


class GraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = build_prefab(component="Mesh", member_kind="string", value="a/mesh.pac")
        self.donor = build_prefab(component="Glow", member_kind="object", value="fx_a.level.effect")
        for data in (self.target, self.donor):
            doc = decode_prefab_binary(data)
            self.assertTrue(doc.walk_complete, doc.walk_note)

    def test_the_synthetic_shapes_decode_like_the_shipped_ones(self) -> None:
        donor = decode_prefab_binary(self.donor)
        self.assertEqual([t.type_name for t in donor.types], ["SceneObject", "Glow", "Path"])
        self.assertEqual([(o.component_type, o.name, o.member_names, [r.text for r in o.resources]) for o in donor.objects], [("Glow", "Glow_0", ("_ref",), ["fx_a.level.effect"])])
        self.assertEqual(find_component_elements(donor, "Glow"), ((0, 0),))
        self.assertEqual(find_component_elements(donor, "Mesh"), ())
        for item in donor.types:
            self.assertEqual(self.donor[item.offset: item.offset + len(encode_prefab_type(item))], encode_prefab_type(item))

    def test_graft_appends_types_remaps_indices_and_reads_back(self) -> None:
        result = graft_prefab_component(self.target, self.donor, component_type="Glow")
        self.assertEqual(result.types_added, ("Glow", "Path"))
        self.assertEqual(result.resources, ("fx_a.level.effect",))
        after = decode_prefab_binary(result.data)
        self.assertTrue(after.walk_complete, after.walk_note)
        self.assertEqual([t.type_name for t in after.types], ["SceneObject", "Mesh", "Glow", "Path"])
        self.assertEqual([(o.component_type, o.name, o.type_source) for o in after.objects], [("Mesh", "Mesh_0", "stated"), ("Glow", "Glow_0", "stated")])
        self.assertEqual([r.text for r in after.objects[1].resources], ["fx_a.level.effect"])
        self.assertEqual([c.count for c in after.collections], [2])
        # the grafted element's headers name the target's indices (Glow 2, Path 3), not the donor's (1, 2)
        element = result.data[result.element_offset: result.element_offset + result.element_length]
        self.assertEqual(element[:6], struct.pack("<H", 1) + bytes((0b1, 2, 0, 0)))
        self.assertIn(struct.pack("<H", 1) + bytes((0b1, 3, 0, 0)), element)
        self.assertEqual(struct.unpack_from("<I", result.data, after.blob_offset - 24)[0], len(result.data))
        # the target's own object is untouched
        before = decode_prefab_binary(self.target)
        self.assertEqual([r.text for r in after.objects[0].texts], [r.text for r in before.objects[0].texts])

    def test_path_replacement_and_transform_overwrite(self) -> None:
        with self.assertRaisesRegex(PrefabEditError, "no 40-byte _offsetTransform"):
            graft_prefab_component(self.target, self.donor, component_type="Glow", offset_transform=encode_transform())
        placed = build_prefab(component="Glow", member_kind="object", value="fx_a.level.effect", with_transform=True)
        result = graft_prefab_component(self.target, placed, component_type="Glow", offset_transform=encode_transform(), path_replacements={"fx_a.level.effect": "fx_b.level.effect"})
        after = decode_prefab_binary(result.data)
        self.assertTrue(after.walk_complete, after.walk_note)
        transform = next(n for n in after.objects[1].numbers if n.name == "_offsetTransform")
        self.assertEqual(transform.raw, encode_transform(), "identity in place of the donor's 0.7 scale and 90-degree turn")
        self.assertEqual([r.text for r in after.objects[1].resources], ["fx_b.level.effect"])
        result = graft_prefab_component(self.target, self.donor, component_type="Glow", path_replacements={"fx_a.level.effect": "fx_fire_much_longer_name.level.effect"})
        after = decode_prefab_binary(result.data)
        self.assertTrue(after.walk_complete, after.walk_note)
        self.assertEqual([r.text for r in after.objects[1].resources], ["fx_fire_much_longer_name.level.effect"])
        self.assertEqual(result.resources, ("fx_fire_much_longer_name.level.effect",))
        self.assertEqual(len(encode_transform()), 40)
        self.assertEqual(encode_transform((2.0, 2.0, 2.0))[:12], struct.pack("<3f", 2.0, 2.0, 2.0))
        with self.assertRaisesRegex(PrefabEditError, "scale\\(3\\)"):
            encode_transform((1.0,))

    def test_a_pointer_shaped_target_takes_the_graft_and_still_repaths(self) -> None:
        from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length

        target = build_prefab(component="SkinnedMeshComponent", member_kind="pointer", value="character/model/a/mesh_0109.pac", pointee_type="ResourceReferencePath_SkinnedMesh")
        doc = decode_prefab_binary(target)
        self.assertTrue(doc.walk_complete, doc.walk_note)
        self.assertEqual([r.text for r in doc.resource_strings()], ["character/model/a/mesh_0109.pac"])
        repathed = rewrite_prefab_paths_any_length(target, {"character/model/a/mesh_0109.pac": "character/model/a/mesh_9109_longer.pac"}).data
        result = graft_prefab_component(repathed, self.donor, component_type="Glow")
        after = decode_prefab_binary(result.data)
        self.assertTrue(after.walk_complete, after.walk_note)
        self.assertEqual([r.text for r in after.resource_strings()], ["character/model/a/mesh_9109_longer.pac", "fx_a.level.effect"])
        self.assertEqual([o.component_type for o in after.objects], ["SkinnedMeshComponent", "Glow"])

    def test_grafting_twice_and_refusals(self) -> None:
        once = graft_prefab_component(self.target, self.donor, component_type="Glow")
        twice = graft_prefab_component(once.data, self.donor, component_type="Glow")
        self.assertEqual(twice.types_added, (), "the types are already declared the second time")
        after = decode_prefab_binary(twice.data)
        self.assertTrue(after.walk_complete, after.walk_note)
        self.assertEqual([o.component_type for o in after.objects], ["Mesh", "Glow", "Glow"])
        self.assertEqual([c.count for c in after.collections], [3])
        with self.assertRaisesRegex(PrefabEditError, "none at index 1"):
            graft_prefab_component(self.target, self.donor, component_type="Glow", donor_index=1)
        with self.assertRaisesRegex(PrefabEditError, "0 Nope element"):
            graft_prefab_component(self.target, self.donor, component_type="Nope")
        with self.assertRaisesRegex(PrefabEditError, "none at index 3"):
            graft_prefab_component(self.target, self.donor, component_type="Glow", target_collection=3)


@pytest.mark.real_game
class VanillaGraftTests(unittest.TestCase):
    def test_the_spears_effect_grafts_onto_the_swords(self) -> None:
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.prefab_binary import walk_is_determined
        from tools.placement_studio import corpus

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        spear_path = "character/bin__/prefab/1_pc/01_phm/weapon/10_thrownweapon/cd_phm_10_thrownspear_0001.prefab"
        swords = {}
        spear = None
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path == spear_path:
                spear = read_archive_entry_data(entry)[0]
            elif path.startswith("character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/cd_phm_01_sword_") and path.endswith(".prefab") and len(swords) < 40:
                swords[path] = read_archive_entry_data(entry)[0]
        if spear is None or not swords:
            self.skipTest("prefabs not found")
        donor = decode_prefab_binary(spear)
        self.assertTrue(donor.walk_complete, "the mask width fix is what completes the spear's walk")
        self.assertEqual(find_component_elements(donor, "EffectComponent"), ((0, 1),))
        grafted = refused = 0
        for path, data in sorted(swords.items()):
            doc = decode_prefab_binary(data)
            if not doc.walk_complete or not walk_is_determined(data):
                refused += 1
                continue
            result = graft_prefab_component(data, spear, path_replacements={"pafx_kliff_titan_lightning_spear_loop_001a.level.effect": "fx_cc_firesweapon_a__fire1.level.effect"}, offset_transform=encode_transform())
            after = decode_prefab_binary(result.data)
            self.assertTrue(after.walk_complete, path)
            self.assertTrue(walk_is_determined(result.data), path)
            effect = [o for o in after.objects if o.component_type == "EffectComponent"]
            self.assertEqual(len(effect), 1, path)
            self.assertEqual([r.text for r in effect[0].resources], ["fx_cc_firesweapon_a__fire1.level.effect"], path)
            self.assertEqual(effect[0].member_names, ("_offsetTransform", "_effectFileName", "_immediatelyKill", "_effectTarget"), path)
            self.assertEqual(result.types_added, ("EffectDataReferencePath", "EffectComponent", "SceneObjectSocketReference"), path)
            grafted += 1
        self.assertGreater(grafted, 20)
        self.assertLess(refused, len(swords) // 4, "most sword prefabs decode completely and determined")


if __name__ == "__main__":
    unittest.main()


def _types_with_member_counts(*counts: int):
    from cdmw.core.prefab_binary import PrefabMember, PrefabType

    return tuple(
        PrefabType(f"Type{index}", tuple(PrefabMember(f"_m{n}", "u8", 0, 1, 0, 0) for n in range(count)), 0)
        for index, count in enumerate(counts)
    )


def _header_then_pointer(prefix: bytes, width: int, mask: int, type_index: int) -> tuple[bytes, int]:
    """``prefix``, an element header of ``width`` mask bytes, the owner, and a self-relative pointer."""

    out = bytearray(prefix)
    start = len(out)
    out += struct.pack("<H", width) + mask.to_bytes(width, "little") + struct.pack("<H", type_index) + b"\x00"
    out += b"\xff" * 8
    out += struct.pack("<I", len(out) + 4)
    out += bytes(32)
    return bytes(out), start


@pytest.mark.parametrize(("width", "members", "mask"), [(0, 0, 0), (6, 43, 1 << 42 | 1), (13, 103, 1 << 102)])
def test_the_element_header_search_reads_zero_and_wide_masks(width: int, members: int, mask: int) -> None:
    """A memberless type writes no mask bytes, a SplineDecalComponent six and ScenePostProcessing
    thirteen; only widths 1 to 4 used to be searched for (2026-11-22)."""

    from cdmw.core.prefab_component_graft import _element_header_start, _pointer_header_index_offset

    types = _types_with_member_counts(1, members)
    data, start = _header_then_pointer(b"\x11\x22\x33", width, mask, 1)
    assert _element_header_start(data, types, 0, len(data)) == start
    site = start + 2 + width + 3 + 8
    assert _pointer_header_index_offset(data, site, types) == start + 2 + width


def test_a_wide_width_whose_stated_type_does_not_need_it_is_not_a_header() -> None:
    from cdmw.core.prefab_component_graft import _element_header_start

    types = _types_with_member_counts(1, 3)  # three members need one mask byte, not six
    data, _start = _header_then_pointer(b"", 6, 0b101, 1)
    with pytest.raises(PrefabEditError, match="no element header"):
        _element_header_start(data, types, 0, len(data))


def test_a_length_field_read_as_a_width_4_header_gives_way_to_the_real_one() -> None:
    """``65 04 00 00 01 00 07 03 00``: the previous element's closing length field reads as width 4
    ending at the same owner as the real width-1 header three bytes on."""

    from cdmw.core.prefab_component_graft import _element_header_start

    types = _types_with_member_counts(1, 1, 1, 3)
    data, start = _header_then_pointer(b"\x65\x04\x00\x00", 1, 0b111, 3)
    assert data[:10] == bytes.fromhex("65040000010007030000")
    assert _element_header_start(data, types, 0, len(data)) == start == 4


def test_a_graft_into_a_list_whose_preamble_lists_keys_is_refused() -> None:
    """Appending an element leaves the keys out of step with the list, as a resize would."""

    donor = build_prefab(component="Glow", member_kind="object", value="fx_a.level.effect")
    keyed = build_prefab(component="Mesh", member_kind="string", value="a/mesh.pac",
                         preamble=bytes(9) + struct.pack("<I", 2) + bytes(16))
    assert decode_prefab_binary(keyed).walk_complete
    with pytest.raises(PrefabEditError, match="2 preamble key"):
        graft_prefab_component(keyed, donor, component_type="Glow")
    empty = build_prefab(component="Mesh", member_kind="string", value="a/mesh.pac", preamble=bytes(13))
    assert graft_prefab_component(empty, donor, component_type="Glow").data
