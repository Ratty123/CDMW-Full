"""Guards for mesh companion-path prediction.

The engine resolves a mesh's material and physics by path convention, not by
anything the prefab stores, so retargeting a mesh silently swaps those too.
These check the prediction, which was measured against the shipped archives:
100% of .pac under /model/ have the physics companion, 99.1% the material one.
"""

from __future__ import annotations

import pytest

from cdmw.domain.archives.prefab_companions import companion_extensions, companion_paths

MESH = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac"


def test_predicts_material_and_physics_siblings() -> None:
    found = {item.role: item.path for item in companion_paths(MESH)}
    assert found == {
        "Material": "character/modelproperty/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac_xml",
        "Physics": "character/bin__/meshphysics/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.hkx",
    }


def test_each_companion_says_what_it_controls() -> None:
    for item in companion_paths(MESH):
        assert item.detail, f"{item.role} has no explanation"


@pytest.mark.parametrize(
    "path",
    [
        "character/texture/a.dds",  # not a mesh
        "character/other/a.pac",  # not under /model/
        "",
    ],
)
def test_says_nothing_where_the_convention_does_not_apply(path: str) -> None:
    assert companion_paths(path) == ()


def test_backslashes_and_leading_slashes_are_tolerated() -> None:
    windows_style = "\\" + MESH.replace("/", "\\")
    assert [item.path for item in companion_paths(windows_style)] == [
        item.path for item in companion_paths(MESH)
    ]


def test_companion_extensions_cover_the_predicted_paths() -> None:
    extensions = companion_extensions()
    for item in companion_paths(MESH):
        assert any(item.path.endswith(ext) for ext in extensions)
