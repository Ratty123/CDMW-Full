"""Guards for the archive path index behind existence checks and the picker."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cdmw.core.prefab_asset_catalog import (
    clear_cache,
    collect_asset_paths,
    extension_for,
    path_is_known,
)


@dataclass(frozen=True)
class _Entry:
    path: str


def _scan(_root):
    return [
        _Entry("character/model/1_pc/a.pac"),
        _Entry("character/model/1_pc/b.pac"),
        _Entry("character/descriptors/a.sockets.xml"),
        _Entry("character/texture/a.dds"),
        _Entry(""),
    ]


@pytest.fixture(autouse=True)
def _clean():
    clear_cache()
    yield
    clear_cache()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/b.pac", ".pac"),
        # A double extension has to be treated as one unit or every socket file
        # is filed under ".xml" alongside unrelated data.
        ("a/b.sockets.xml", ".sockets.xml"),
        ("a/b", ""),
    ],
)
def test_extension_grouping(path: str, expected: str) -> None:
    assert extension_for(path) == expected


def test_collects_only_the_requested_kinds() -> None:
    index = collect_asset_paths("root", [".pac"], scan=_scan)
    assert index == {".pac": ("character/model/1_pc/a.pac", "character/model/1_pc/b.pac")}


def test_double_extensions_are_collected_separately() -> None:
    index = collect_asset_paths("root", [".sockets.xml"], scan=_scan)
    assert index[".sockets.xml"] == ("character/descriptors/a.sockets.xml",)


def test_second_call_is_served_from_cache() -> None:
    calls = []

    def counting_scan(root):
        calls.append(root)
        return _scan(root)

    collect_asset_paths("root", [".pac"], scan=counting_scan)
    collect_asset_paths("root", [".pac"], scan=counting_scan)
    assert len(calls) == 1


def test_existence_is_three_valued() -> None:
    """Unknown must not read as missing, or every unindexed kind looks broken."""
    index = collect_asset_paths("root", [".pac"], scan=_scan)
    assert path_is_known(index, "character/model/1_pc/a.pac") is True
    assert path_is_known(index, "character/model/1_pc/typo.pac") is False
    assert path_is_known(index, "character/texture/a.dds") is None
    assert path_is_known(index, "") is None


def test_lookup_ignores_separator_and_case_differences() -> None:
    index = collect_asset_paths("root", [".pac"], scan=_scan)
    assert path_is_known(index, r"CHARACTER\MODEL\1_pc\A.PAC") is True
    assert path_is_known(index, "/character/model/1_pc/a.pac") is True
