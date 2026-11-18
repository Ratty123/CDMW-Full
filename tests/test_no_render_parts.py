"""Parts of the game's NoRender shader are not drawn.

SkinnedMeshNoRender ships no shader. Its wrappers (the titan head's eye cover
and two sockets) declare no parameter and name no texture, so the only place a
package names them is Preview Core's wrapper list.
"""

from __future__ import annotations

from cdmw.services.mesh_rust_preview_package import _apply_preview_core_no_render_parts

SCOPE = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_titan/cd_m0001_00_titan_head_0001.pac#model_property=0"
OTHER = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_titan/cd_m0001_00_titan_body_0001.pac#model_property=0"


def _package():
    batches = [
        {"index": 0, "editor_identity": {"component_scope_id": SCOPE, "part_name": "CD_PTTM_00_Head_0001"}},
        {"index": 1, "editor_identity": {"component_scope_id": SCOPE, "part_name": "CD_PTTM_00_Head_0001_Eye_Cover"}},
        # The same submesh name in another model of the package is not that wrapper's part.
        {"index": 2, "editor_identity": {"component_scope_id": OTHER, "part_name": "CD_PTTM_00_Head_0001_Eye_Cover"}},
    ]
    graph = {"materials": [{"lod_index": 0, "material_index": index} for index in range(3)]}
    presentations = [
        {"lod_index": 0, "material_index": index, "alpha_mode": "opaque", "opacity": None, "alpha_cutoff": 0.08}
        for index in range(3)
    ]
    return batches, graph, presentations


def test_a_no_render_part_is_found_by_its_model_and_submesh_name_and_left_out() -> None:
    batches, graph, presentations = _package()
    wrappers = [
        {"component_scope_id": SCOPE, "material_name": "cd_pttm_00_head_0001", "shader_family": "SkinnedMeshSkin",
         "material_wrapper_index": 0, "parameter_count": 12},
        {"component_scope_id": SCOPE, "material_name": "cd_pttm_00_head_0001_eye_cover",
         "shader_family": "SkinnedMeshNoRender", "material_wrapper_index": 1, "parameter_count": 0},
    ]

    _apply_preview_core_no_render_parts(presentations, graph, batches, wrappers)

    untouched = {"alpha_mode": "opaque", "opacity": None, "alpha_cutoff": 0.08}
    assert {key: presentations[0][key] for key in untouched} == untouched
    assert {key: presentations[2][key] for key in untouched} == untouched
    # No coverage at all, and the part keeps its row: part indices do not move.
    assert presentations[1]["alpha_mode"] == "blend"
    assert presentations[1]["opacity"] == 0.0
    assert presentations[1]["alpha_cutoff"] == 0.0
    assert len(presentations) == 3


def test_a_package_without_a_wrapper_list_draws_every_part() -> None:
    # A package written before Preview Core stated its wrappers.
    batches, graph, presentations = _package()

    _apply_preview_core_no_render_parts(presentations, graph, batches, ())

    assert all(row["alpha_mode"] == "opaque" for row in presentations)


def test_a_model_made_only_of_no_render_parts_stays_drawn() -> None:
    # A socket opened on its own: hiding its only parts would leave an empty view.
    batches, graph, presentations = _package()
    wrappers = [
        {"component_scope_id": scope, "material_name": name.casefold(), "shader_family": "SkinnedMeshNoRender",
         "material_wrapper_index": index, "parameter_count": 0}
        for index, (scope, name) in enumerate(
            (batch["editor_identity"]["component_scope_id"], batch["editor_identity"]["part_name"]) for batch in batches)
    ]

    _apply_preview_core_no_render_parts(presentations, graph, batches, wrappers)

    assert all(row["alpha_mode"] == "opaque" and row["opacity"] is None for row in presentations)
