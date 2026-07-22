from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_d3d11_cache import (
    alignment_d3d11_cache_display_class,
    alignment_d3d11_dirty_flags_for_reason,
    alignment_d3d11_geometry_cache_key,
    alignment_d3d11_invalidate_package_cache,
    alignment_d3d11_material_cache_key,
    alignment_d3d11_model_cache_signature,
    alignment_d3d11_package_cache_get,
    alignment_d3d11_package_cache_put,
    alignment_d3d11_package_is_cached,
    alignment_d3d11_record_cache_hit_metadata,
    alignment_d3d11_record_cache_lookup_result,
    alignment_d3d11_record_package_request_metadata,
    alignment_d3d11_record_package_timing,
    alignment_d3d11_reset_package_quality,
    alignment_d3d11_store_package_cache,
)


def test_alignment_d3d11_cache_display_class_normalizes_modes() -> None:
    assert alignment_d3d11_cache_display_class("replacement_only") == "replacement_only"
    assert alignment_d3d11_cache_display_class("overlay") == "with_original"
    assert alignment_d3d11_cache_display_class("") == "with_original"


def test_vortice_texture_cache_uses_material_fingerprints_across_package_reloads() -> None:
    source = Path("tools/dotnet_mesh_editor_experiment/NetTextureSet.Incremental.cs").read_text(encoding="utf-8")

    assert 'return $"fingerprint|{fingerprint}";' in source
    assert ".GroupBy(item => item.Reference.SourceCacheKey" in source
    assert "_decodedByFingerprint.TryGetValue(reference.SourceCacheKey" in source


def test_alignment_d3d11_package_is_cached_checks_ordered_cache_paths(tmp_path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    cache = OrderedDict({"abc": {"package_dir": str(package_dir)}})

    assert alignment_d3d11_package_is_cached(package_dir, cache) is True
    assert alignment_d3d11_package_is_cached(tmp_path / "other", cache) is False
    assert alignment_d3d11_package_is_cached(package_dir, {"abc": {"package_dir": str(package_dir)}}) is False


def test_alignment_d3d11_package_cache_get_validates_manifest_and_touches_lru(tmp_path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (second_dir / "manifest.json").write_text("{}", encoding="utf-8")
    cache = OrderedDict(
        (
            ("first", {"package_dir": first_dir}),
            ("second", {"package_dir": second_dir}),
        )
    )

    entry = alignment_d3d11_package_cache_get("first", cache, cleanup_package=lambda _package_dir: None)

    assert entry == {"package_dir": first_dir}
    assert tuple(cache.keys()) == ("second", "first")


def test_alignment_d3d11_package_cache_get_evicts_missing_manifest(tmp_path) -> None:
    package_dir = tmp_path / "missing"
    package_dir.mkdir()
    cache = OrderedDict({"stale": {"package_dir": package_dir}})
    cleaned: list[object] = []

    assert alignment_d3d11_package_cache_get("stale", cache, cleanup_package=cleaned.append) is None
    assert "stale" not in cache
    assert cleaned == [package_dir]


def test_alignment_d3d11_package_cache_put_records_metadata_and_lru_evictions(tmp_path) -> None:
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    cache = OrderedDict({"old": {"package_dir": old_dir}})

    updated_cache, evicted = alignment_d3d11_package_cache_put(
        "new",
        new_dir,
        cache,
        display_class="replacement_only",
        display_mode="replacement_only",
        package_quality="fast",
        prepare_ms=1.5,
        package_ms=2.5,
        created=12.0,
        limit=1,
    )

    assert updated_cache is cache
    assert tuple(updated_cache.keys()) == ("new",)
    assert updated_cache["new"]["package_dir"] == new_dir
    assert updated_cache["new"]["display_class"] == "replacement_only"
    assert updated_cache["new"]["package_quality"] == "fast"
    assert evicted == (old_dir,)


def test_alignment_d3d11_package_cache_put_creates_ordered_cache_for_invalid_state(tmp_path) -> None:
    updated_cache, evicted = alignment_d3d11_package_cache_put(
        "key",
        tmp_path / "package",
        {},
        display_class="with_original",
        display_mode="side_by_side",
        package_quality="normal",
        prepare_ms=0.0,
        package_ms=0.0,
        created=1.0,
        limit="bad",
    )

    assert isinstance(updated_cache, OrderedDict)
    assert tuple(updated_cache.keys()) == ("key",)
    assert evicted == ()


def test_alignment_d3d11_invalidate_package_cache_marks_material_dirty_without_clearing(tmp_path) -> None:
    cache = OrderedDict({"key": {"package_dir": tmp_path / "package"}})
    state = {"package_cache": cache}
    cleaned: list[tuple[object, int]] = []

    alignment_d3d11_invalidate_package_cache(
        state,
        "material",
        cleanup_package=lambda package_path, delay_ms: cleaned.append((package_path, delay_ms)),
    )

    assert tuple(cache.keys()) == ("key",)
    assert state["last_cache_event"] == "material_dirty"
    assert state["last_cache_reason"] == "material"
    assert cleaned == []


def test_alignment_d3d11_invalidate_package_cache_clears_cache_and_delays_active_cleanup(tmp_path) -> None:
    active_dir = tmp_path / "active"
    stale_dir = tmp_path / "stale"
    active_dir.mkdir()
    stale_dir.mkdir()
    cache = OrderedDict(
        (
            ("active", {"package_dir": active_dir}),
            ("stale", {"package_dir": stale_dir}),
        )
    )
    state = {
        "package_cache": cache,
        "active_package": active_dir,
        "active_package_cache_key": "active",
    }
    cleaned: list[tuple[object, int]] = []

    alignment_d3d11_invalidate_package_cache(
        state,
        "geometry",
        cleanup_package=lambda package_path, delay_ms: cleaned.append((package_path, delay_ms)),
    )

    assert cache == OrderedDict()
    assert state["active_package_cache_key"] == ""
    assert state["last_cache_event"] == "cleared"
    assert state["last_cache_reason"] == "geometry"
    assert (active_dir.resolve(), 5000) in cleaned
    assert (stale_dir.resolve(), 0) in cleaned


def test_alignment_d3d11_record_cache_metadata_helpers_normalize_state() -> None:
    state: dict[str, object] = {}

    alignment_d3d11_record_package_request_metadata(
        state,
        package_quality="fast_geometry",
        rebuild_reason=" Material ",
    )

    assert state["package_quality"] == "fast_geometry"
    assert state["last_rebuild_reason"] == "material"
    assert state["last_cache_reason"] == "material"

    quality = alignment_d3d11_record_cache_hit_metadata(
        state,
        {"prepare_ms": "1.5", "package_ms": 2, "package_quality": "archive_parity"},
        package_quality="fast_geometry",
    )

    assert quality == "archive_parity"
    assert state["prepare_ms"] == 1.5
    assert state["package_ms"] == 2.0
    assert state["package_quality"] == "archive_parity"
    assert state["last_cache_event"] == "hit"
    assert alignment_d3d11_record_cache_lookup_result(state, "") == "bypass"
    assert state["last_cache_event"] == "bypass"
    assert alignment_d3d11_record_cache_lookup_result(state, "cache") == "miss"
    assert state["last_cache_event"] == "miss"

    alignment_d3d11_record_package_timing(state, prepare_ms=3, package_ms=4.5)

    assert state["prepare_ms"] == 3.0
    assert state["package_ms"] == 4.5


def test_alignment_d3d11_store_package_cache_replaces_state_cache() -> None:
    cache = OrderedDict({"key": {"package_dir": "package"}})
    state: dict[str, object] = {}

    alignment_d3d11_store_package_cache(state, cache)

    assert state["package_cache"] is cache


def test_alignment_d3d11_reset_package_quality_sets_normal() -> None:
    state: dict[str, object] = {"package_quality": "mesh_edit_raw"}

    alignment_d3d11_reset_package_quality(state)

    assert state["package_quality"] == "normal"


def test_alignment_d3d11_dirty_flags_for_reason_maps_preview_cache_impacts() -> None:
    assert alignment_d3d11_dirty_flags_for_reason("material").affects_material() is True
    texture_uv_flags = alignment_d3d11_dirty_flags_for_reason("texture_uv")
    assert texture_uv_flags.uv is True
    assert texture_uv_flags.affects_material() is True
    assert alignment_d3d11_dirty_flags_for_reason("mode_missing_original").render_settings is True
    assert alignment_d3d11_dirty_flags_for_reason("selection").selection is True
    assert alignment_d3d11_dirty_flags_for_reason("unknown").affects_geometry() is True


def test_alignment_d3d11_model_cache_signature_tracks_material_inputs() -> None:
    parameter = SimpleNamespace(
        parameter_kind="float",
        parameter_name="roughness",
        value="0.5",
        numeric_value="0.5",
    )
    material_input = SimpleNamespace(
        parameter_name="_base",
        slot_kind="base",
        semantic_type="color",
        semantic_subtype="albedo",
        source_texture_path="source.png",
        source_dds_path="source.dds",
        preview_texture_path="preview.png",
        packed_channels=("r", "g", "b", "a"),
        material_parameters=(parameter,),
    )
    mesh = SimpleNamespace(
        material_name="Body",
        texture_name="BodyTex",
        preview_role="replacement",
        source_submesh_index=2,
        positions=(1.0, 2.0, 3.0),
        texture_coordinates=(0.0, 1.0),
        indices=(0, 1, 2),
        preview_texture_path="preview.png",
        preview_texture_dds_path="preview.dds",
        preview_normal_texture_path="normal.png",
        preview_normal_texture_dds_path="normal.dds",
        preview_material_texture_path="material.png",
        preview_material_texture_dds_path="material.dds",
        preview_height_texture_path="height.png",
        preview_height_texture_dds_path="height.dds",
        preview_texture_flip_vertical=False,
        preview_texture_tint=(1.0, 1.0, 1.0),
        preview_texture_brightness=1.0,
        preview_texture_uv_scale=(1.0, 1.0),
        preview_vertex_color_mean=(1.0, 1.0, 1.0),
        preview_vertex_alpha_mean=1.0,
        preview_vertex_alpha_min=1.0,
        preview_vertex_color_count=3,
        preview_double_sided=True,
        preview_material_texture_inputs=(material_input,),
        preview_native_material_overrides={},
    )
    model = SimpleNamespace(
        path="model.mesh",
        format="mesh",
        mesh_count=1,
        vertex_count=3,
        face_count=1,
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
        meshes=(mesh,),
    )

    signature = alignment_d3d11_model_cache_signature(
        model,
        file_signature=lambda value: (str(value), len(str(value)), 0),
        sample_sequence=lambda values: tuple(values),
    )
    parameter.numeric_value = "0.75"

    changed_signature = alignment_d3d11_model_cache_signature(
        model,
        file_signature=lambda value: (str(value), len(str(value)), 0),
        sample_sequence=lambda values: tuple(values),
    )

    assert signature != changed_signature

    override_signature = changed_signature
    mesh.preview_native_material_overrides = {"native_material_hints": {"roughness": 0.8}}
    native_override_signature = alignment_d3d11_model_cache_signature(
        model,
        file_signature=lambda value: (str(value), len(str(value)), 0),
        sample_sequence=lambda values: tuple(values),
    )

    assert override_signature != native_override_signature


def test_alignment_d3d11_geometry_cache_key_tracks_clone_mode_and_geometry() -> None:
    mesh = SimpleNamespace(
        source_submesh_index=2,
        positions=(1.0, 2.0, 3.0),
        normals=(0.0, 1.0, 0.0),
        texture_coordinates=(0.0, 1.0),
        indices=(0, 1, 2),
        preview_double_sided=False,
    )
    model = SimpleNamespace(
        path="model.mesh",
        format="mesh",
        mesh_count=1,
        vertex_count=3,
        face_count=1,
        normalization_center=(0.0, 0.0, 0.0),
        normalization_scale=1.0,
        meshes=(mesh,),
    )
    digest = lambda values: (len(tuple(values or ())), repr(tuple(values or ())))

    base_key = alignment_d3d11_geometry_cache_key(
        model,
        display_mode="side_by_side",
        modify_original_clone_mode=False,
        sequence_digest=digest,
    )
    clone_key = alignment_d3d11_geometry_cache_key(
        model,
        display_mode="side_by_side",
        modify_original_clone_mode=True,
        sequence_digest=digest,
    )
    mesh.positions = (9.0, 2.0, 3.0)
    moved_key = alignment_d3d11_geometry_cache_key(
        model,
        display_mode="side_by_side",
        modify_original_clone_mode=False,
        sequence_digest=digest,
    )

    assert base_key != clone_key
    assert base_key != moved_key


def test_alignment_d3d11_material_cache_key_tracks_quality_and_authority_payload() -> None:
    settings = SimpleNamespace(
        use_textures_by_default=True,
        high_quality_by_default=True,
        preview_texture_max_dimension=2048,
        low_quality_texture_max_dimension=512,
        disable_all_support_maps=False,
        disable_normal_map=False,
        disable_material_map=False,
        disable_height_map=False,
        flip_texture_v=False,
        visible_texture_mode="all",
        alpha_handling_mode="blend",
    )
    model = SimpleNamespace(meshes=(SimpleNamespace(preview_native_material_overrides={}),))
    signature = lambda value: (str(value), len(str(value)), 0)

    normal_key = alignment_d3d11_material_cache_key(
        model,
        settings,
        package_quality="normal",
        donor_material_plan_payload=(),
        material_authority_preview_signature="a",
        file_signature=signature,
    )
    fast_key = alignment_d3d11_material_cache_key(
        model,
        settings,
        package_quality="fast",
        donor_material_plan_payload=(),
        material_authority_preview_signature="a",
        file_signature=signature,
    )
    authority_key = alignment_d3d11_material_cache_key(
        model,
        settings,
        package_quality="normal",
        donor_material_plan_payload=(("Body", "donor.xml"),),
        material_authority_preview_signature="b",
        file_signature=signature,
    )
    model.meshes[0].preview_native_material_overrides = {"native_material_hints": {"roughness": 0.8}}
    native_override_key = alignment_d3d11_material_cache_key(
        model,
        settings,
        package_quality="normal",
        donor_material_plan_payload=(),
        material_authority_preview_signature="a",
        file_signature=signature,
    )

    assert normal_key != fast_key
    assert normal_key != authority_key
    assert normal_key != native_override_key
