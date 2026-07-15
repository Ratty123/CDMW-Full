from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.ui.archive_browser.static_replacement_native_manifest import (
    apply_native_preview_core_material_manifest,
    load_native_preview_core_material_manifest_for_alignment,
)
from cdmw.ui.archive_browser.static_replacement_preview_cache import (
    cached_static_preview_geometry,
    model_has_preview_texture_keys,
    restore_static_preview_geometry_cache_payload,
    static_preview_geometry_cache_payload,
    static_preview_prepared_cache_key,
    store_static_preview_cache_entry,
)
from cdmw.ui.archive_browser.static_replacement_static_preview_state import (
    static_preview_prepared_cache_result,
    static_preview_upload_elapsed_ms,
    static_preview_widget_mode_state,
    static_preview_widget_model_action,
)
from cdmw.ui.archive_browser.static_replacement_preview_textures import (
    accent_glow_preview_enabled,
    accent_glow_preview_intensity,
    add_preview_material_input,
    apply_material_authority_preview_native_hints,
    apply_manual_preview_texture_override_specs,
    apply_source_material_preview,
    apply_source_material_preview_for_model,
    apply_source_role_emissive_preview,
    apply_source_role_emissive_preview_for_model,
    clear_material_authority_preview_native_hints,
    clear_replacement_preview_texture_bindings,
    clear_source_role_emissive_preview,
    material_authority_preview_parameters,
    preview_glow_color_from_candidates,
    set_preview_texture_slot_path,
    source_preview_path,
    texture_set_for_mapping,
)


def test_apply_native_preview_core_material_manifest_ignores_invalid_manifest(tmp_path: Path) -> None:
    assert (
        apply_native_preview_core_material_manifest(
            object(),
            tmp_path,
            native_manifest_input_from_descriptor=lambda *_args, **_kwargs: None,
        )
        == 0
    )
    preview_model = ModelPreviewData(meshes=[ModelPreviewMesh()])
    (tmp_path / "manifest.json").write_text("{not-json", encoding="utf-8")

    assert (
        apply_native_preview_core_material_manifest(
            preview_model,
            tmp_path,
            native_manifest_input_from_descriptor=lambda *_args, **_kwargs: None,
        )
        == 0
    )


def test_load_native_preview_core_material_manifest_records_success(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    packages: list[object] = []

    def run_job(entry: object, **kwargs: object) -> object:
        assert kwargs["cache_root"] == tmp_path / "cache"
        assert kwargs["package_root"] == tmp_path / "package-root"
        return SimpleNamespace(succeeded=True, package_path=tmp_path / "package")

    applied = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text=str(tmp_path / "package-root"),
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path / "cache",
        render_settings=SimpleNamespace(),
        companion_entry=SimpleNamespace(path="companion"),
        run_preview_job=run_job,
        clear_native_package_path=lambda: packages.append("cleared"),
        set_native_package_path=packages.append,
        apply_manifest=lambda _model, package_path: 2 if package_path == tmp_path / "package" else 0,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )

    assert applied == 2
    assert packages == [tmp_path / "package"]
    assert events == [
        (
            "mesh_alignment_native_material_manifest_applied",
            {
                "path": "models/body.pam",
                "dialog_title": "Dialog",
                "batch_count": 2,
                "package_path": tmp_path / "package",
            },
        )
    ]


def test_load_native_preview_core_material_manifest_records_unavailable_and_failures(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    clears: list[str] = []

    skipped = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".txt", path="notes.txt"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: None,
        clear_native_package_path=lambda: clears.append("cleared"),
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert skipped == 0
    assert events == []

    unavailable = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: SimpleNamespace(
            succeeded=False,
            status="fallback",
            fallback_reason="unsupported",
        ),
        clear_native_package_path=lambda: clears.append("cleared"),
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert unavailable == 0
    assert clears == ["cleared"]
    assert events[-1][0] == "mesh_alignment_native_material_manifest_unavailable"
    assert events[-1][1]["reason"] == "unsupported"

    failed = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        clear_native_package_path=lambda: None,
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert failed == 0
    assert events[-1][0] == "mesh_alignment_native_material_manifest_failed"
    assert events[-1][1]["message"] == "boom"
