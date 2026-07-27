"""The wearables index survives a round trip through its on-disk cache.

Building it parses every package table, which takes about four seconds and includes one
1.2-second call the UI thread cannot paint through. The cache is what stops that landing on
every launch, so what matters here is that what comes back is usable — in particular that
the archive entries are reconstructed well enough to still be readable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.placement_studio import armour


class _Entry:
    """Stand-in with the same field names as the real `ArchiveEntry`."""

    def __init__(self, path: str, pamt_path: Path, offset: int) -> None:
        self.path = path
        self.pamt_path = pamt_path
        self.paz_file = pamt_path.with_suffix(".paz")
        self.offset = offset
        self.comp_size = 10
        self.orig_size = 20
        self.flags = 0
        self.paz_index = 1
        self.prepared_path = None
        self.prepared_sha256 = None
        self.prepared_note = None
        self.content_analysis_json_path = None
        self.content_analysis_text_path = None
        self.content_analysis_version = None


_FIELDS = (
    "path", "pamt_path", "paz_file", "offset", "comp_size", "orig_size", "flags",
    "paz_index", "prepared_path", "prepared_sha256", "prepared_note",
    "content_analysis_json_path", "content_analysis_text_path", "content_analysis_version",
)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the cache at a temp directory and swap in the stand-in entry type."""

    monkeypatch.setattr(armour, "_cache_file", lambda _root: tmp_path / "wearables.json")
    monkeypatch.setattr(armour, "_cache_signature", lambda _root: [["pkg", 1, 2]])
    monkeypatch.setattr(armour, "_entry_fields", lambda: _FIELDS)
    monkeypatch.setattr(armour, "_entry_from_json", _from_json)
    return tmp_path


def _from_json(raw: dict) -> _Entry:
    entry = _Entry(raw["path"], Path(raw["pamt_path"]), raw["offset"])
    entry.paz_file = Path(raw["paz_file"])
    return entry


def _sample():
    entry = _Entry("character/model/1_pc/1_phm/armor/13_hel/hat.pac", Path("C:/g/0009.pamt"), 64)
    index = armour.ArmourIndex(
        [armour.ArmourPiece(path=entry.path, slot="13_hel", model="1_phm", source=entry)]
    )
    sock = _Entry("character/descriptors/socketbonedata/1_pc/1_phm/weapon/a.sockets.xml",
                  Path("C:/g/0000.pamt"), 128)
    mesh = _Entry("character/model/1_pc/1_phm/weapon/1_sword/blade.pac", Path("C:/g/0000.pamt"), 256)
    return index, {sock.path: sock}, {mesh.path: mesh}


def test_cache_round_trips_the_index(wired):
    armour._write_index_cache("root", _sample())

    index, sockets, meshes = armour._read_index_cache("root")

    assert len(index) == 1
    piece = index.pieces("1_phm", "13_hel")[0]
    assert piece.name == "hat"
    # The entry has to come back complete, or reading the piece fails inside the extractor.
    assert piece.source.offset == 64
    assert piece.source.pamt_path == Path("C:/g/0009.pamt")
    assert list(sockets) == ["character/descriptors/socketbonedata/1_pc/1_phm/weapon/a.sockets.xml"]
    assert list(meshes)[0].endswith("blade.pac")


def test_a_game_update_invalidates_the_cache(wired, monkeypatch):
    armour._write_index_cache("root", _sample())
    # A patched package changes its table's size and mtime, which is what the signature tracks.
    monkeypatch.setattr(armour, "_cache_signature", lambda _root: [["pkg", 999, 2]])

    assert armour._read_index_cache("root") is None


def test_a_corrupt_cache_is_ignored_rather_than_raising(wired):
    (wired / "wearables.json").write_text("{ not json", encoding="utf-8")

    assert armour._read_index_cache("root") is None


def test_a_cache_from_an_older_layout_is_ignored(wired):
    armour._write_index_cache("root", _sample())
    path = wired / "wearables.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = armour._CACHE_VERSION - 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert armour._read_index_cache("root") is None


def test_a_cancelled_scan_is_not_cached(wired, monkeypatch):
    """Half a scan must never be written, or the cancellation becomes permanent."""

    monkeypatch.setattr(
        armour, "_scan_wearables", lambda _root, should_stop=None: (armour.ArmourIndex(), {}, {})
    )

    armour.index_wearables("root", should_stop=lambda: True)

    assert not (wired / "wearables.json").exists()
