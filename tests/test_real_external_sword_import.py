from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.modding.static_mesh_build import build_static_replacement_preview_mesh
from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_state_payload
from cdmw.services.mesh_workflow_service import import_scene_mesh_with_report
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_setup_helpers import (
    static_replacement_prompt_mesh_bounds,
)
from cdmw.ui.archive_browser.static_replacement_preview_mapping import preview_model_in_original_frame
from cdmw.ui.archive_browser.static_replacement_preview_frame import original_frame_grid_y
from cdmw.ui.archive_browser.static_replacement_preview_models import combine_alignment_preview_models
from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
    StaticReplacementPromptPreflightRequest,
    prepare_static_replacement_prompt_preflight,
)


pytestmark = pytest.mark.real_game

_SWORD_PATH = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0016.pac"


def _source_paths() -> tuple[Path, Path]:
    game_root = Path(os.environ.get("CDMW_GAME_ROOT", r"C:\games\Steam\steamapps\common\Crimson Desert"))
    model_path = Path(
        os.environ.get(
            "CDMW_EXTERNAL_MODEL_PATH",
            r"E:\ModelCatalogue\downloads\wolf_gravestone_sword_free (1).zip",
        )
    )
    return game_root, model_path


def _dimensions(bounds: tuple[tuple[float, float, float], tuple[float, float, float]]) -> tuple[float, float, float]:
    return tuple(bounds[1][axis] - bounds[0][axis] for axis in range(3))  # type: ignore[return-value]


def test_real_wolf_gravestone_import_is_grounded_and_uses_original_overlay_frame() -> None:
    game_root, model_path = _source_paths()
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file() or not model_path.is_file():
        pytest.skip("Real sword PAC or Wolf Gravestone model archive is unavailable.")

    entries = parse_archive_pamt(pamt_path)
    entry = next((item for item in entries if item.path.replace("\\", "/").casefold() == _SWORD_PATH.casefold()), None)
    assert entry is not None
    archive_stamps_before = {
        Path(path): (Path(path).stat().st_size, Path(path).stat().st_mtime_ns)
        for path in (entry.pamt_path, entry.paz_file)
    }
    payload, _decompressed, _note = read_archive_entry_data(entry)
    original_mesh = MeshService().load_mesh_bytes(payload, entry.path)
    scene_result = import_scene_mesh_with_report(model_path)

    by_path: dict[str, list[object]] = defaultdict(list)
    by_basename: dict[str, list[object]] = defaultdict(list)
    by_extension: dict[str, list[object]] = defaultdict(list)
    for candidate in entries:
        key = candidate.path.replace("\\", "/").strip("/").casefold()
        by_path[key].append(candidate)
        by_basename[key.rsplit("/", 1)[-1]].append(candidate)
        by_extension[candidate.extension.casefold()].append(candidate)
    preflight = prepare_static_replacement_prompt_preflight(
        StaticReplacementPromptPreflightRequest(
            request_id=1,
            entry=entry,
            obj_path=model_path,
            supplemental_files=(),
            scene_import_result=scene_result,
            original_mesh=original_mesh,
            archive_entries_by_normalized_path=by_path,
            archive_entries_by_basename=by_basename,
            archive_entries_by_extension=by_extension,
        )
    )
    transformed = build_static_replacement_preview_mesh(
        preflight.original_mesh,
        preflight.replacement_mesh,
        StaticMeshReplacementOptions(submesh_mappings=list(preflight.suggested_mappings)),
    )
    original_bounds = static_replacement_prompt_mesh_bounds(preflight.original_mesh)
    transformed_bounds = static_replacement_prompt_mesh_bounds(transformed)
    assert original_bounds is not None and transformed_bounds is not None
    original_dimensions = _dimensions(original_bounds)
    transformed_dimensions = _dimensions(transformed_bounds)

    assert abs(transformed_bounds[0][1]) <= 1e-6
    assert transformed_dimensions[1] < min(transformed_dimensions[0], transformed_dimensions[2])
    assert max(transformed_dimensions) == pytest.approx(max(original_dimensions), rel=0.05)

    original_preview = preflight.original_preview_model
    replacement_preview = preview_model_in_original_frame(
        transformed,
        normalization_center=original_preview.normalization_center,
        normalization_scale=original_preview.normalization_scale,
    )
    overlay = combine_alignment_preview_models(original_preview, replacement_preview)
    assert overlay is not None
    assert overlay.normalization_center == original_preview.normalization_center
    assert overlay.normalization_scale == original_preview.normalization_scale
    assert overlay.preview_frame_kind == "original_pac_frame"
    assert overlay.preview_grid_mode == "original_frame"
    expected_grid_y = original_frame_grid_y(
        original_preview.normalization_center,
        original_preview.normalization_scale,
    )
    assert replacement_preview.preview_grid_y == pytest.approx(expected_grid_y)
    assert overlay.preview_grid_y == pytest.approx(expected_grid_y)

    texture_paths = tuple(str(path) for path in scene_result.discovered_texture_files)
    assert len(texture_paths) >= 3
    assert not any("checker" in path.casefold() for path in texture_paths)
    assert {path.resolve() for path in preflight.texture_files} == {
        path.resolve() for path in scene_result.discovered_texture_files
    }
    lambert_textures = preflight.texture_sets["lambert1"].slots
    assert lambert_textures["base"].source_path.name == "lambert1_baseColor.png"
    assert lambert_textures["material"].source_path.name == "lambert1_metallicRoughness.png"
    assert lambert_textures["normal"].source_path.name == "lambert1_normal.png"
    resident_materials = mesh_dotnet_material_state_payload(
        preflight.replacement_mesh,
        session_id="real-wolf-sword",
        edit_revision=0,
        generation=0,
    )
    bindings = {str(row["material"]): row for row in resident_materials["submeshes"]}
    lambert = bindings["lambert1"]
    assert lambert["channels"]["roughness"] == lambert["channels"]["metallic"]
    assert "specular" not in lambert["channels"]
    assert lambert["channel_components"] == {"roughness": "g", "metallic": "b"}
    assert bindings["Gem_outside"]["parameters"]["tint_color"] == [1.0, 0.0, 0.0]
    assert bindings["Gem_outside"]["parameters"]["roughness"] == 0.0
    assert bindings["Gem_outside"]["parameters"]["metalness"] == 1.0
    assert bindings["Gem_inside"]["parameters"]["tint_color"] == pytest.approx([0.0, 1.0, 0.7911])
    assert bindings["Gem_inside"]["parameters"]["emissive_intensity"] == 10.0
    assert archive_stamps_before == {
        path: (path.stat().st_size, path.stat().st_mtime_ns) for path in archive_stamps_before
    }
