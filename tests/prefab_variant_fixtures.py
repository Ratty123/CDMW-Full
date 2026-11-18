"""Item prefabs that pick a material variant, as the game's own files declare them.

Each prefab maps to ``(model path, _modelPropertyIndex)`` rows, read from the
shipped archive (material coverage census, 18 Nov 2026). ``None`` is an object
without the field, which the game draws at variant 0.

``install`` stands in for the archive read and the prefab decoder, so a test
gets the decoded objects the app's prefab reader sees for these files.
"""
from __future__ import annotations

from types import SimpleNamespace

from cdmw.models import ArchiveEntry

HONOR_GUARD_PREFAB = "character/bin__/prefab/1_pc/01_phm/armor/9_upperbody/cd_phm_00_ub_00_0376.prefab"
HONOR_GUARD_UB = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0376.pac"
HONOR_GUARD_LB = "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_0002.pac"
HONOR_GUARD_BELT = "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_belt_00_0001.pac"

FOOT_SET_PREFAB = "character/bin__/prefab/1_pc/01_phm/armor/12_foot/cd_phm_00_foot_set_0069.prefab"
FOOT_0165 = "character/model/1_pc/1_phm/armor/12_foot/cd_phm_00_foot_0165.pac"
FOOT_BELT_0125 = "character/model/1_pc/1_phm/armor/12_foot/cd_phm_00_foot_belt_0125.pac"

HEL_SET_PREFAB = "character/bin__/prefab/1_pc/01_phm/armor/13_hel/cd_phm_00_hel_set_0018.prefab"
HEL_0060 = "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0060.pac"
HEL_0014 = "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0014.pac"

# One gauntlet PAC, eleven items: its own-name prefab and the _indexNN ones.
HAND_0003 = "character/model/1_pc/1_phm/armor/11_hand/cd_phm_00_hand_0003.pac"
HAND_0003_PREFAB = "character/bin__/prefab/1_pc/01_phm/armor/11_hand/cd_phm_00_hand_0003.prefab"
HAND_0003_INDEX01 = "character/bin__/prefab/1_pc/01_phm/armor/11_hand/cd_phm_00_hand_0003_index01.prefab"
HAND_0003_INDEX02 = "character/bin__/prefab/1_pc/01_phm/armor/11_hand/cd_phm_00_hand_0003_index02.prefab"

PREFABS = {
    HONOR_GUARD_PREFAB: ((HONOR_GUARD_UB, None), (HONOR_GUARD_LB, 32), (HONOR_GUARD_BELT, 1)),
    FOOT_SET_PREFAB: ((FOOT_0165, 5), (FOOT_BELT_0125, 1)),
    HEL_SET_PREFAB: ((HEL_0060, 1), (HEL_0014, None)),
    HAND_0003_PREFAB: ((HAND_0003, None),),
    HAND_0003_INDEX01: ((HAND_0003, 1),),
    HAND_0003_INDEX02: ((HAND_0003, 2),),
}


def entry(path: str, *, offset: int = 0) -> ArchiveEntry:
    return ArchiveEntry(path=path, pamt_path="0009/0.pamt", paz_file="0009/0.paz", offset=offset,
                        comp_size=64, orig_size=64, flags=0, paz_index=0)


def _document(rows):
    objects = []
    for model, index in rows:
        numbers = () if index is None else (
            SimpleNamespace(name="_modelPropertyIndex", raw=int(index).to_bytes(4, "little")),)
        objects.append(SimpleNamespace(values=(("_skinnedMeshFile", SimpleNamespace(text=model)),),
                                       numbers=numbers))
    return SimpleNamespace(objects=tuple(objects))


def install(monkeypatch, prefabs=PREFABS, files=None):
    """Read each prefab as its census rows, and each other file from ``files`` (path -> bytes)."""
    import cdmw.core.archive_extraction as extraction
    import cdmw.core.prefab_binary as prefab_binary

    files = dict(files or {})

    def read(candidate, **_kwargs):
        path = str(candidate.path)
        if path in prefabs:
            return path.encode("utf-8"), False, ""
        if path in files:
            return files[path], False, ""
        raise KeyError(path)

    def decode(data):
        return _document(prefabs[bytes(data).decode("utf-8")])

    monkeypatch.setattr(extraction, "read_archive_entry_data", read)
    monkeypatch.setattr(prefab_binary, "decode_prefab_binary", decode)
