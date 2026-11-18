"""Parts of the game's Ghost shader draw as blended shells, not solid grey.

The shader reads no texture colour (SkinnedMeshGhost, permutation
3fe935f0e737c889): coverage is a Fresnel power times a sphere mask times
`_ghostOpacity`, drawn by a dithered discard. The preview blends the part at
one coverage instead.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from cdmw.services.mesh_rust_preview_package import (
    _apply_preview_core_ghost_shells,
    ghost_shell_presentation,
)

SCOPE = "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0451.pac#model_property=0"
# The monocle lens of cd_phm_00_hel_00_0451: its icon shows the ring and a clear lens.
MONOCLE = {
    "_ghostNoiseIntensity": "0.200001",
    "_ghostMaskRadius": "4.400000",
    "_ghostMaskHardness": "1.360000",
    "_ghostFresnelAlpha": "0.300001",
    "_ghostOpacity": "0.592000",
    "_ghostMetallic": "1.000000",
    "AlphaTest": "",
}
MONOCLE_CENTRE = (-0.033, 1.713, -0.166)


def test_the_monocle_lens_is_nearly_clear() -> None:
    shell = ghost_shell_presentation(MONOCLE, MONOCLE_CENTRE)

    assert shell["alpha_mode"] == "blend"
    # distance to the default mask position (0, -3, 0) is 4.72; (4.72 - 4.4) / 1.36 = 0.23;
    # the mean of |N.V|^0.3 over a facing sphere is 2 / 2.3; times opacity 0.592.
    assert shell["opacity"] == pytest.approx(0.2345 * (2 / 2.3) * 0.592, abs=0.005)
    assert shell["metalness"] == 1.0
    assert shell["roughness"] == 1.0
    # No _ghostColor on the wrapper: the family's default 0xFF88A4A7.
    assert shell["colour"] == pytest.approx([0x88 / 255, 0xA4 / 255, 0xA7 / 255])


def test_ghost_coverage_follows_the_fresnel_sign_the_mask_and_the_opacity() -> None:
    far = (0.0, 10.0, 0.0)  # well outside the default mask sphere
    assert ghost_shell_presentation({"_ghostFresnelAlpha": "0", "_ghostOpacity": "0.9"}, far)["opacity"] == pytest.approx(0.9)
    # Positive: the rim clears, the mean stays high. Negative: the middle clears.
    assert ghost_shell_presentation({"_ghostFresnelAlpha": "2"}, far)["opacity"] == pytest.approx(0.5)
    assert ghost_shell_presentation({"_ghostFresnelAlpha": "-2"}, far)["opacity"] == pytest.approx(2 / 12)
    # Inside the mask sphere nothing is drawn.
    assert ghost_shell_presentation({"_ghostMaskRadius": "50"}, far)["opacity"] == 0.0
    # The authored colour is read as #rrggbbaa; a value the reader cannot use keeps the default.
    assert ghost_shell_presentation({"_ghostColor": "#7f499cff"}, far)["colour"] == pytest.approx([0x7F / 255, 0x49 / 255, 0x9C / 255])
    assert ghost_shell_presentation({"_ghostOpacity": "nonsense"}, far)["opacity"] == pytest.approx(2 / (1.1 * 2.1))


def test_a_ghost_batch_is_found_by_its_model_and_submesh_name(tmp_path: Path) -> None:
    # Two triangles around the monocle's centre, normalised as Preview Core writes them.
    centre, scale = (0.0, 1.78, -0.057), 5.385
    geometry = tmp_path / "geometry"
    geometry.mkdir()
    record = struct.pack("<3f", *((MONOCLE_CENTRE[axis] - centre[axis]) * scale for axis in range(3))) + bytes(80)
    (geometry / "batch_001.bin").write_bytes(record * 6)
    batches = [
        {"index": 0, "vertex_file": "geometry/batch_000.bin", "vertex_count": 3, "editor_identity": {
            "component_scope_id": SCOPE, "part_name": "CD_PHM_00_Hel_00_0451"}},
        {"index": 1, "vertex_file": "geometry/batch_001.bin", "vertex_count": 6, "editor_identity": {
            "component_scope_id": SCOPE, "part_name": "CD_PHM_00_Acc_00_0451_01"}},
    ]
    parameters = [
        {"component_scope_id": SCOPE, "material_name": "cd_phm_00_acc_00_0451_01", "shader_family": "SkinnedMeshGhost",
         "parameter_name": name, "value": value}
        for name, value in MONOCLE.items()
    ] + [
        {"component_scope_id": SCOPE, "material_name": "cd_phm_00_hel_00_0451", "shader_family": "SkinnedMeshStandard_Ver2",
         "parameter_name": "_dyeingGlobalOpacity", "value": "16777215"},
    ]
    graph = {"materials": [
        {"lod_index": 0, "material_index": 0, "base_color": [0.62, 0.62, 0.62]},
        {"lod_index": 0, "material_index": 1, "base_color": [0.62, 0.62, 0.62]},
    ]}
    presentations = [
        {"lod_index": 0, "material_index": index, "alpha_mode": "opaque", "opacity": None, "alpha_cutoff": 0.0,
         "roughness": 0.45, "metalness": 0.0}
        for index in (0, 1)
    ]

    _apply_preview_core_ghost_shells(presentations, graph, batches, parameters, tmp_path, centre, scale)

    assert presentations[0] == {"lod_index": 0, "material_index": 0, "alpha_mode": "opaque", "opacity": None,
                                "alpha_cutoff": 0.0, "roughness": 0.45, "metalness": 0.0}
    assert graph["materials"][0]["base_color"] == [0.62, 0.62, 0.62]
    lens = presentations[1]
    assert lens["alpha_mode"] == "blend"
    assert lens["opacity"] == pytest.approx(0.12, abs=0.01)
    assert lens["metalness"] == 1.0
    assert graph["materials"][1]["base_color"] == pytest.approx([0x88 / 255, 0xA4 / 255, 0xA7 / 255])
