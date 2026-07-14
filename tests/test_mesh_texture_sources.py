from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_texture_sources import resolve_mesh_texture_source


def _entry(root: Path, virtual_path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(
        path=virtual_path,
        pamt_path=root / "0.pamt",
        paz_file=root / "0.paz",
        offset=offset,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def test_material_slot_suffix_resolves_lower_priority_archive_dds(tmp_path: Path) -> None:
    target = _entry(tmp_path, "character/model/hair.pac", 0)
    fallback = _entry(tmp_path, "character/texture/cd_phm_00_hair_base_0013.dds", 1)
    extracted = tmp_path / "hair.dds"
    extracted.write_bytes(b"dds")

    result = resolve_mesh_texture_source(
        "CD_PHM_00_Hair_Base_0013_01",
        target_entry=target,
        entries_by_basename={"cd_phm_00_hair_base_0013.dds": [fallback]},
        ensure_source=lambda _entry, **_kwargs: (extracted, "test-cache"),
    )

    assert result.ok
    assert result.archive_entry == fallback


def test_exact_archive_dds_wins_over_material_slot_suffix_fallback(tmp_path: Path) -> None:
    target = _entry(tmp_path, "character/model/hair.pac", 0)
    exact = _entry(tmp_path, "character/texture/cd_phm_00_hair_base_0013_01.dds", 1)
    fallback = _entry(tmp_path, "character/texture/cd_phm_00_hair_base_0013.dds", 2)
    extracted = tmp_path / "hair.dds"
    extracted.write_bytes(b"dds")

    result = resolve_mesh_texture_source(
        "CD_PHM_00_Hair_Base_0013_01",
        target_entry=target,
        entries_by_basename={
            "cd_phm_00_hair_base_0013_01.dds": [exact],
            "cd_phm_00_hair_base_0013.dds": [fallback],
        },
        ensure_source=lambda entry, **_kwargs: (extracted, entry.path),
    )

    assert result.ok
    assert result.archive_entry == exact
