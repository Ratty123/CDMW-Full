"""Exercise runtime branches whose dependencies were lost during extraction."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote_from_bytes

import numpy as np
import pytest


@pytest.mark.parametrize("enabled", [False, True])
def test_texture_preflight_reports_ready_mod_profiles(tmp_path, enabled):
    from cdmw.core.texture_pipeline.preflight import build_preflight_report_lines
    from cdmw.core.texture_pipeline.runtime_config import normalize_config_for_planning
    from cdmw.models import AppConfig

    config = AppConfig(
        original_dds_root=str(tmp_path),
        png_root=str(tmp_path / "png"),
        output_root=str(tmp_path / "output"),
        enable_chainner=False,
        upscale_backend="none",
        enable_mod_ready_loose_export=enabled,
        mod_ready_export_root=str(tmp_path / "packages"),
        mod_ready_package_title="Review fixture",
        mod_ready_manager_profiles=("dmm", "jmm"),
    )
    lines = build_preflight_report_lines(normalize_config_for_planning(config), [])
    assert f"- Ready mod package export: {'enabled' if enabled else 'disabled'}" in lines
    outputs = [line for line in lines if line.startswith("- Mod package output:")]
    assert bool(outputs) is enabled
    if enabled:
        assert str(tmp_path / "packages") in outputs[0]
        assert ", " in outputs[0]
    assert not (tmp_path / "packages").exists()


@pytest.mark.parametrize("refresh", [False, True])
def test_classification_focus_reaches_selected_paths_and_refresh(refresh):
    from cdmw.ui.research.classification_review_controller import focus_classification_review_for_paths

    view = SimpleNamespace(
        unknown_name_filter_edit=Mock(),
        unknown_package_filter_edit=Mock(),
        unknown_show_classified_checkbox=Mock(),
        unknown_resolver_status_label=Mock(),
        tab_widget=Mock(),
        archive_tab=object(),
        archive_insights_tabs=Mock(),
        classification_review_tab=object(),
        research_payload={"loaded": True},
        refresh_research=Mock(),
        _refresh_unknown_resolver_view=Mock(),
    )
    focus_classification_review_for_paths(
        view, ["character/body.dds"], include_classified=True, refresh_if_needed=refresh,
    )
    assert "character/body.dds" in view.pending_classification_review_focus_keys
    assert view._classification_review_focus_uses_full_archive
    view.unknown_resolver_status_label.setText.assert_called_once()
    view.tab_widget.setCurrentWidget.assert_called_once_with(view.archive_tab)
    view.archive_insights_tabs.setCurrentWidget.assert_called_once_with(view.classification_review_tab)
    view.unknown_name_filter_edit.blockSignals.assert_any_call(False)
    assert view.refresh_research.called is refresh
    assert view._refresh_unknown_resolver_view.called is not refresh


def test_crop_outside_all_layers_creates_transparent_base_without_mutating_source():
    from cdmw.core.texture_editor_raster_ops import crop_texture_editor_document_to_bounds
    from cdmw.models import TextureEditorDocument, TextureEditorLayer

    layer = TextureEditorLayer("small", "Small layer", "small.png")
    document = TextureEditorDocument("Canvas", 8, 8, layers=(layer,), active_layer_id=layer.layer_id)
    pixels = {layer.layer_id: np.full((2, 2, 4), 255, dtype=np.uint8)}
    cropped, cropped_pixels = crop_texture_editor_document_to_bounds(document, pixels, (4, 4, 2, 2))
    assert (cropped.width, cropped.height) == (2, 2)
    assert len(cropped.layers) == 1
    assert cropped.active_layer_id == cropped.layers[0].layer_id
    assert cropped.active_layer_id != layer.layer_id
    np.testing.assert_array_equal(cropped_pixels[cropped.active_layer_id], np.zeros((2, 2, 4), dtype=np.uint8))
    assert (document.width, document.height, document.layers) == (8, 8, (layer,))
    assert np.all(pixels[layer.layer_id] == 255)


def test_percent_encoded_gltf_buffer_preserves_binary_bytes_and_imports(tmp_path):
    import json

    from cdmw.modding.scene_gltf_import import _decode_data_uri_with_mime, _load_gltf_payload
    from cdmw.modding.scene_importer import import_scene_mesh
    from tests.test_scene_importer_gltf import _triangle_payload

    binary = b"\x00\x80\xff+\xc3\xa5"
    assert _decode_data_uri_with_mime("data:application/octet-stream," + quote_from_bytes(binary)) == (
        "application/octet-stream", binary,
    )
    buffer, document = _triangle_payload()
    document["buffers"][0]["uri"] = "data:application/octet-stream," + quote_from_bytes(buffer)
    source = tmp_path / "triangle.gltf"
    source.write_text(json.dumps(document), encoding="utf-8")
    assert _load_gltf_payload(source).buffers[0] == buffer
    mesh = import_scene_mesh(source)
    assert len(mesh.submeshes) == 1
    assert len(mesh.submeshes[0].vertices) == 3
    assert len(mesh.submeshes[0].faces) == 1


@pytest.mark.parametrize("extension", [".prefab", ".meshinfo"])
def test_mesh_companion_summary_decodes_real_reference_fixture(tmp_path, extension):
    from cdmw.core.archive_mesh_import_supplemental import _summarize_crimson_companion_supplemental_files

    path = "character/model/test_a.pac".encode("utf-8")
    payload = b"\xff\xff\x04\x00" + len(path).to_bytes(4, "little") + path
    companion = tmp_path / ("test_a" + extension)
    companion.write_bytes(payload)
    lines = _summarize_crimson_companion_supplemental_files([companion])
    assert lines[0] == "Crimson companion metadata:"
    assert companion.name in lines[1]
    assert "model=1" in lines[1]
    assert "policy=" in lines[1]
    assert companion.read_bytes() == payload


@pytest.mark.parametrize("target_path,needs_injection", [
    ("character/texture/body_o.dds", False),
    ("character/texture/cd_common_default_white.dds", True),
    ("(injected _overlayColorTexture)", False),
])
def test_base_color_mapping_distinguishes_existing_and_shared_textures(target_path, needs_injection):
    from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot, TextureSlotMapping
    from cdmw.modding.material_texture_payloads import _needs_missing_base_color_parameter_payloads

    source = Path("source.png")
    texture_set = ReplacementTextureSet("source", slots={"base": ReplacementTextureSlot("source", "base", source)})
    existing = TextureSlotMapping("body", target_path, "base", "source", source, target_path)
    assert _needs_missing_base_color_parameter_payloads(
        texture_sets={"source": texture_set},
        target_to_source_material={"body": "source"},
        existing_slot_mappings=[existing],
        original_sidecars=[(None, "<Material/>")],
    ) is needs_injection


def test_missing_base_color_injection_returns_payload_mapping_and_parameter(tmp_path, monkeypatch):
    from cdmw.modding import material_texture_payloads as payloads
    from cdmw.modding.material_replacer import (
        ReplacementTextureSet, ReplacementTextureSlot, TextureReplacementReport,
    )

    source = tmp_path / "source.png"
    texture_set = ReplacementTextureSet("source", slots={"base": ReplacementTextureSlot("source", "base", source)})
    entry = SimpleNamespace(path="character/texture/body_o.dds")
    reference = SimpleNamespace(
        resolved_archive_path=entry.path, resolved_entry=entry,
        sidecar_parameter_name="_overlayColorTexture", material_name="body",
    )
    report = TextureReplacementReport()
    monkeypatch.setattr(payloads, "_build_texture_payload", lambda *args, **kwargs: b"generated DDS")
    generated, injections = payloads._build_missing_base_color_parameter_payloads(
        obj_mesh=None, texture_sets={"source": texture_set}, original_texture_refs=[reference],
        target_to_source_material={"body": "source"}, existing_slot_mappings=[],
        read_original_texture_bytes=lambda _entry: b"", original_texture_source_path=lambda _entry: source,
        report=report, on_log=None, texture_output_size_mode="original",
    )
    assert len(generated) == len(injections) == len(report.slot_mappings) == 1
    assert generated[0].payload_data == b"generated DDS"
    assert generated[0].target_path == entry.path
    assert report.slot_mappings[0].output_texture_path == entry.path
    assert injections[0].texture_path == entry.path
    assert injections[0].parameter_name == "_overlayColorTexture"
    assert not report.errors
