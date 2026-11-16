"""Relationship entry keys resolve each .pamt path once, not once per entry.

The review measured 192 ms on the UI thread selecting one model in Browse:
a realpath per edge in ``_dedupe_edges``. The key must stay the same.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.core import archive_relationships
from cdmw.domain.archives.relationships import ArchiveRelationEdge
from cdmw.models import ArchiveEntry


def _entry(pamt_path: Path, path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path, pamt_path=pamt_path, paz_file=pamt_path.with_suffix(".paz"),
        offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0,
    )


def test_dedupe_resolves_each_pamt_path_once(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_relationships, "_RESOLVED_PAMT_PATHS", {}, raising=False)
    pamt = tmp_path / "0009" / "0.pamt"
    pamt.parent.mkdir()
    pamt.write_bytes(b"")
    calls = []
    real_resolve = Path.resolve

    def counting_resolve(self, *args, **kwargs):
        calls.append(str(self))
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)
    edges = [
        ArchiveRelationEdge(source_path="a.pac", related_path=f"t/{index}.dds",
                            related_entry=_entry(pamt, f"t/{index}.dds"), relation_kind="texture")
        for index in range(200)
    ]
    edges.append(edges[0])  # a duplicate is still dropped
    result = archive_relationships._dedupe_edges(edges)
    assert len(result) == 200
    assert calls == [str(pamt)]


def test_entry_key_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_relationships, "_RESOLVED_PAMT_PATHS", {}, raising=False)
    pamt = tmp_path / "0009" / "0.pamt"
    entry = _entry(pamt, "Character\\Model\\A.pac")
    expected = f"{pamt.resolve()}::character/model/a.pac"
    assert archive_relationships._entry_key(entry) == expected
    assert archive_relationships._entry_key(entry) == expected
