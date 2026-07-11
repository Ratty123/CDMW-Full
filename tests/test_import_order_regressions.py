from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_clean_import(script: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_research_analysis_imports_before_and_after_facade() -> None:
    _run_clean_import(
        "import cdmw.core.research_texture_analysis as owner; "
        "import cdmw.core.research as facade; "
        "assert facade.detect_texture_atlases is owner.detect_texture_atlases"
    )
    _run_clean_import(
        "import cdmw.core.research as facade; "
        "from cdmw.core.research import detect_texture_atlases; "
        "import cdmw.core.research_texture_analysis as owner; "
        "assert detect_texture_atlases is owner.detect_texture_atlases"
    )


def test_research_dtos_keep_identity_for_every_import_order() -> None:
    _run_clean_import(
        "import cdmw.domain.research.contracts as owner; "
        "import cdmw.core.research as facade; "
        "assert facade.ResearchNote is owner.ResearchNote; "
        "assert facade.MaterialTextureReferenceRow is owner.MaterialTextureReferenceRow; "
        "assert facade.MipAnalysisRow is owner.MipAnalysisRow"
    )
    _run_clean_import(
        "import cdmw.core.research as facade; "
        "from cdmw.core.research import ResearchNote, TextureSetGroup; "
        "import cdmw.domain.research.contracts as owner; "
        "assert ResearchNote is owner.ResearchNote; "
        "assert TextureSetGroup is owner.TextureSetGroup; "
        "assert facade.TextureBudgetRow is owner.TextureBudgetRow"
    )


def test_texture_editor_owners_import_before_and_after_facade() -> None:
    for module_name in (
        "texture_editor_project_io",
        "texture_editor_raster_ops",
        "texture_editor_layer_ops",
    ):
        _run_clean_import(f"import cdmw.core.{module_name}; import cdmw.core.texture_editor")
    _run_clean_import(
        "from cdmw.core.texture_editor import flatten_texture_editor_layers; "
        "from cdmw.core.texture_editor_raster_ops import flatten_texture_editor_layers as owner; "
        "assert flatten_texture_editor_layers is owner"
    )
    _run_clean_import(
        "from cdmw.domain.textures import editor_brush, editor_composite, editor_layers; "
        "import cdmw.core.texture_editor as facade; "
        "import cdmw.core.texture_editor_raster_ops as raster; "
        "import cdmw.core.texture_editor_layer_ops as layers; "
        "assert facade.apply_texture_editor_stroke is editor_brush.apply_texture_editor_stroke; "
        "assert raster.flatten_texture_editor_layers is editor_composite.flatten_texture_editor_layers; "
        "assert layers.add_texture_editor_layer is editor_layers.add_texture_editor_layer"
    )
    _run_clean_import(
        "import cdmw.core.texture_editor as facade; "
        "from cdmw.core.texture_editor import apply_texture_editor_stroke, add_texture_editor_layer; "
        "from cdmw.domain.textures import editor_brush, editor_layers; "
        "assert apply_texture_editor_stroke is editor_brush.apply_texture_editor_stroke; "
        "assert add_texture_editor_layer is editor_layers.add_texture_editor_layer"
    )
    _run_clean_import(
        "from cdmw.services.texture_editor_service import TextureEditorService; "
        "from cdmw.core import texture_editor_project_io, texture_editor_raster_ops; "
        "assert TextureEditorService.load_project is texture_editor_project_io.load_texture_editor_project; "
        "assert TextureEditorService.save_project is texture_editor_project_io.save_texture_editor_project; "
        "assert TextureEditorService.export_flattened_png is texture_editor_raster_ops.export_texture_editor_flattened_png"
    )


def test_package_domain_owners_keep_core_compatibility_identity() -> None:
    _run_clean_import(
        "import cdmw.domain.packages.export_policy as policy; "
        "import cdmw.domain.packages.layout as layout; "
        "import cdmw.domain.packages.retrofit as retrofit; "
        "import cdmw.core.mod_package as package; "
        "import cdmw.core.mod_package_retrofit as retrofit_facade; "
        "assert package.ModPackageExportOptions is policy.ModPackageExportOptions; "
        "assert package.mod_package_export_options_for_manager is policy.mod_package_export_options_for_manager; "
        "assert package.resolve_mod_package_root is layout.resolve_mod_package_root; "
        "assert retrofit_facade.RetrofittableModPackage is retrofit.RetrofittableModPackage; "
        "assert retrofit_facade.RetrofitPathRepairSummary is retrofit.RetrofitPathRepairSummary"
    )
    _run_clean_import(
        "import cdmw.core.mod_package as package; "
        "import cdmw.core.mod_package_retrofit as retrofit_facade; "
        "import cdmw.domain.packages.export_policy as policy; "
        "import cdmw.domain.packages.layout as layout; "
        "import cdmw.domain.packages.retrofit as retrofit; "
        "assert package.ModPackageExportOptions is policy.ModPackageExportOptions; "
        "assert package.mod_package_expanded_export_options is policy.mod_package_expanded_export_options; "
        "assert package.normalize_mod_package_payload_path is layout.normalize_mod_package_payload_path; "
        "assert retrofit_facade.ModPackageRetrofitResult is retrofit.ModPackageRetrofitResult; "
        "assert retrofit_facade.RetrofitPayloadMapping is retrofit.RetrofitPayloadMapping"
    )


def test_library_domain_owners_keep_core_compatibility_identity() -> None:
    _run_clean_import(
        "import sys; "
        "import cdmw.services.item_icon_service; "
        "import cdmw.services.model_library_service; "
        "import cdmw.services.service_container; "
        "assert 'cdmw.core.item_icon' not in sys.modules; "
        "assert 'cdmw.core.model_catalogue' not in sys.modules"
    )
    _run_clean_import(
        "import cdmw.domain.library.item_icons as icons; "
        "import cdmw.domain.library.models as models; "
        "import cdmw.core.item_icon as icon_facade; "
        "import cdmw.core.model_catalogue as model_facade; "
        "assert icon_facade.ItemIconLibraryRecord is icons.ItemIconLibraryRecord; "
        "assert icon_facade.ItemIconOverrideSpec is icons.ItemIconOverrideSpec; "
        "assert icon_facade.normalize_item_icon_background_mode is icons.normalize_item_icon_background_mode; "
        "assert model_facade.LocalModelFile is models.LocalModelFile; "
        "assert model_facade.MirrorDownloadCandidate is models.MirrorDownloadCandidate; "
        "assert model_facade.normalize_mirror_base_url is models.normalize_mirror_base_url; "
        "assert model_facade.mirror_download_candidates is models.mirror_download_candidates"
    )
    _run_clean_import(
        "import cdmw.core.item_icon as icon_facade; "
        "import cdmw.core.model_catalogue as model_facade; "
        "import cdmw.domain.library.item_icons as icons; "
        "import cdmw.domain.library.models as models; "
        "assert icon_facade.ItemIconBuildResult is icons.ItemIconBuildResult; "
        "assert icon_facade.ItemIconTemplateInfo is icons.ItemIconTemplateInfo; "
        "assert model_facade.MirrorDownloadResult is models.MirrorDownloadResult; "
        "assert model_facade.normalize_mirror_model_record is models.normalize_mirror_model_record; "
        "assert model_facade.is_importable_model_path is models.is_importable_model_path"
    )


def test_material_exports_keep_owner_identity_for_every_import_order() -> None:
    _run_clean_import(
        "import cdmw.modding.material_source_driven as owner; "
        "import cdmw.modding.material_replacer as facade; "
        "assert facade._source_driven_slots is owner._source_driven_slots"
    )
    _run_clean_import(
        "import cdmw.modding.material_texture_routing as owner; "
        "import cdmw.modding.material_replacer as facade; "
        "assert facade.group_replacement_texture_sets is owner.group_replacement_texture_sets"
    )
    _run_clean_import(
        "import cdmw.modding.material_replacer as facade; "
        "import cdmw.modding.material_source_driven as source; "
        "import cdmw.modding.material_texture_routing as routing; "
        "assert facade._source_driven_slots is source._source_driven_slots; "
        "assert facade.group_replacement_texture_sets is routing.group_replacement_texture_sets"
    )
