from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.core import research_references
from cdmw.core.research_archive_analysis import build_archive_research_snapshot
from cdmw.core.research_references import resolve_material_texture_references
from cdmw.models import ArchiveEntry


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0009/0.pamt"), Path("0009/0.paz"), offset, 1, 1, 0, 0)


def test_archive_snapshot_keeps_classification_groups_and_heatmap_behavior() -> None:
    entries = [
        _entry("character/texture/armor_d.dds", 1),
        _entry("character/texture/armor_n.dds", 2),
    ]

    snapshot = build_archive_research_snapshot(entries)

    classification_rows = snapshot["classification_rows"]
    assert len(classification_rows) == 2
    assert {row.texture_type for row in classification_rows} >= {"normal"}
    texture_groups = snapshot["texture_groups"]
    assert len(texture_groups) == 1
    assert {member.path for member in texture_groups[0].members} == {entry.path for entry in entries}
    assert {row.scope for row in snapshot["heatmap_rows"]} == {"System Area", "Folder", "Package"}


@pytest.mark.parametrize("selected_path, expected_mode", [
    ("character/texture/armor_d.dds", "inbound"),
    ("character/material/armor.xml", "outbound"),
])
def test_reference_owner_resolves_inbound_and_outbound_rows(
    selected_path: str,
    expected_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texture = _entry("character/texture/armor_d.dds", 1)
    material = _entry("character/material/armor.xml", 2)
    xml = b'<Texture Name="Armor" Filename="character/texture/armor_d.dds" GetRect="0,0,64,64" />'

    def fake_read(entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        return (xml if entry is material else b"", False, "fixture")

    monkeypatch.setattr(research_references, "read_archive_entry_data", fake_read)
    rows, stats = resolve_material_texture_references([texture, material], selected_path)

    assert stats["mode"] == expected_mode
    assert len(rows) == 1
    assert rows[0].source_path == material.path
    assert rows[0].related_path == texture.path
    assert rows[0].get_rect_raw == "0,0,64,64"
    assert (rows[0].rect_x, rows[0].rect_y) == (0, 0)
    assert rows[0].constraint_kind == "Explicit UI rect found"
