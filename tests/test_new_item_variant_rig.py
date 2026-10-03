"""Plan validation distinguishes socket attachments from character skinning."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.services.new_item_variants import validate_variant_rig


MODEL = "character/model/1_pc/1_phm/weapon/1_onehandweapon/test.pac"
PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/01_onehandweapon/test_r.prefab"


def _pac(*, weighted_accessory=False, attachment_slot=0, extra_accessory=False):
    from tests.test_pac_skin_extra_influences import _record
    from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original
    from cdmw.modding.pac_cloth import pac_cloth_lods

    data, _ = _minimal_two_part_pac_original()
    result = bytearray(data)
    parts = ((index, part) for level in pac_cloth_lods(data) for index, part in enumerate(level.submeshes))
    for part_index, part in parts:
        for vertex_index, offset in enumerate(part.source_vertex_offsets):
            weighted = weighted_accessory and part_index == 1 and vertex_index == 0
            record = _record(
                palette=(0, 43, 0, 0, 0, 0) if weighted else (attachment_slot, 0, 0, 0, 0, 0),
                weights=(128, 127, 0, 0, 0, 0, 40, 60) if weighted and extra_accessory
                else (128, 127, 0, 0, 0, 0, 0, 0) if weighted else (255, 0, 0, 0, 0, 0, 0, 0),
                extra=(20.0, 19.0) if weighted and extra_accessory else (0.0, 1.0),
                gate=0 if weighted and extra_accessory else 63,
            )
            for start, end in ((12, 16), (20, 36), (39, 40)):
                result[offset + start:offset + end] = record[start:end]
            result[offset + 38] = 255
    return bytes(result)


def _snapshot(*, prefab_model=MODEL, attached="RHand_Socket", pivot="Basic_ChildSocket", extra_accessory=False):
    from tests.test_archive_relationships import ArchiveRelationshipTests

    prefab = ArchiveRelationshipTests()._minimal_prefab_profile_payload(
        attached=attached,
        pivot=pivot,
        part="CD_MainWeapon_Sword_R",
        model=prefab_model,
        socket_file="character/descriptors/socketbonedata/test.sockets.xml",
    )
    files = {MODEL: _pac(weighted_accessory=True, extra_accessory=extra_accessory), PREFAB: prefab}
    return _snapshot_files(files)


def _snapshot_files(files):
    from tests.test_release_inspired_improvements import _entry

    entries = {path: _entry(path) for path in files}
    by_path = {path.casefold(): (entry,) for path, entry in entries.items()}
    by_name = {}
    for entry in entries.values():
        by_name.setdefault(entry.basename.casefold(), []).append(entry)
    return SimpleNamespace(entries=files, payload=files.__getitem__, entry=entries.__getitem__,
                           archive_index_maps=lambda: (by_path, by_name))


def test_rigid_weapon_import_uses_its_exact_prefab_attachment():
    snapshot = _snapshot()
    assert validate_variant_rig(snapshot, MODEL, _pac(), prefab_path=PREFAB) == "rigid prefab attachment"
