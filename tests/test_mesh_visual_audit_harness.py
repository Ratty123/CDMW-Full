from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from tools.mesh_harness.visual_audit_corpus import (
    VISUAL_AUDIT_VIEWS,
    VisualAuditAssetSpec,
    _remove_visual_audit_overlays,
    default_visual_audit_specs,
    validate_visual_audit_specs,
)
from tools.mesh_harness.visual_audit_report import build_visual_audit_composites


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def test_default_visual_audit_corpus_has_required_real_pac_coverage() -> None:
    specs = default_visual_audit_specs()

    assert len(specs) == 30
    assert len({spec.asset_id for spec in specs}) == 30
    assert len({spec.virtual_path.casefold() for spec in specs}) == 30
    assert all(spec.virtual_path.casefold().endswith(".pac") for spec in specs)
    assert [view["name"] for view in VISUAL_AUDIT_VIEWS] == [
        "front",
        "three-quarter-front",
        "side",
        "back",
        "slightly-above",
        "slightly-below",
    ]
    assert validate_visual_audit_specs(specs) == {
        "weapon": 8,
        "sword": 6,
        "armor": 8,
        "body": 5,
        "hair_fur_feather": 5,
        "unusual": 4,
    }


def test_visual_audit_corpus_rejects_partial_or_duplicate_selection() -> None:
    specs = default_visual_audit_specs()

    with pytest.raises(ValueError, match="at least 30 unique PAC paths"):
        validate_visual_audit_specs(specs[:29])
    with pytest.raises(ValueError, match="unique PAC paths"):
        validate_visual_audit_specs((*specs[:-1], specs[0]))


def test_visual_audit_corpus_rejects_unsafe_manifest_asset_id() -> None:
    specs = list(default_visual_audit_specs())
    specs[0] = VisualAuditAssetSpec(
        index=specs[0].index,
        asset_id="../outside",
        virtual_path=specs[0].virtual_path,
        model_category=specs[0].model_category,
        coverage_tags=specs[0].coverage_tags,
        selection_reason=specs[0].selection_reason,
    )

    with pytest.raises(ValueError, match="safe filename component"):
        validate_visual_audit_specs(specs)


def test_visual_audit_comparison_removes_non_material_overlays_from_clone() -> None:
    class Preview:
        physics_overlay = object()
        cloth_preview = object()

    preview = Preview()

    result = _remove_visual_audit_overlays(preview)

    assert result == {
        "skeleton_overlay_disabled": True,
        "cloth_overlay_disabled": True,
    }
    assert preview.physics_overlay is None
    assert preview.cloth_preview is None


def test_visual_audit_renderer_contract_is_resident_direct_and_vortice_only() -> None:
    batch = (DOTNET_ROOT / "VisualAuditBatch.cs").read_text(encoding="utf-8")
    entry = (DOTNET_ROOT / "ProgramEntry.cs").read_text(encoding="utf-8")
    d3d11 = (DOTNET_ROOT / "D3D11MaterialViewport.cs").read_text(encoding="utf-8")
    capture = (ROOT / "tools" / "mesh_harness" / "visual_audit_capture.py").read_text(
        encoding="utf-8"
    )
    native_host = (ROOT / "cdmw" / "ui" / "native_d3d11_preview_host.py").read_text(
        encoding="utf-8"
    )

    assert "VisualAuditBatch.IsRequested(args)" in entry
    assert '["process_start_count"] = 1' in batch
    assert '["process_restart_count"] = 0' in batch
    assert '"d3d11_vortice_shader"' in batch
    assert "TryCaptureReplacementPng(" in batch
    assert batch.count("new D3D11MaterialViewport(") == 1
    assert "new MeshViewport(" not in batch
    assert "ReplaceResidentScene(" in batch
    assert "public void ReplaceResidentScene(" in d3d11
    assert "ResidentSceneLoadCount++" in d3d11
    assert '["device_initialization_count"] = _deviceInitializationCount' in batch
    assert '"process_start_count": 1' in capture
    assert "host.load_package(" in capture
    assert "host.request_frame_capture(capture_path)" in capture
    assert "capture_path.unlink(missing_ok=True)" in capture
    assert "report_path.unlink(missing_ok=True)" in capture
    assert "completed.returncode == 0" in capture
    assert 'str(report.get("run_id", "")) == run_id' in capture
    assert '"command": "capture_frame"' in native_host


def test_visual_audit_composites_preserve_source_pixels_without_resampling(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    dotnet_dir = tmp_path / "dotnet"
    archive_dir.mkdir()
    dotnet_dir.mkdir()
    views = [str(view["name"]) for view in VISUAL_AUDIT_VIEWS]
    archive_captures = []
    dotnet_captures = []
    for index, view in enumerate(views):
        archive_path = archive_dir / f"{view}.png"
        dotnet_path = dotnet_dir / f"{view}.png"
        Image.new("RGB", (8, 6), (20 + index, 40, 60)).save(archive_path)
        Image.new("RGB", (8, 6), (120 + index, 140, 160)).save(dotnet_path)
        archive_captures.append({"name": view, "path": str(archive_path), "ok": True})
        dotnet_captures.append({"name": view, "path": str(dotnet_path), "ok": True})

    rows = build_visual_audit_composites(
        {
            "assets": [
                {
                    "asset_id": "001-test",
                    "virtual_path": "character/model/test.pac",
                }
            ]
        },
        {"assets": [{"id": "001-test", "ok": True, "captures": archive_captures}]},
        {"assets": [{"id": "001-test", "ok": True, "captures": dotnet_captures}]},
        tmp_path / "review",
        tmp_path / "final",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["selected_camera_angle"] == "three-quarter-front"
    assert row["archive_browser_capture_ok"] is True
    assert row["mesh_editor_capture_ok"] is True
    with Image.open(Path(str(row["primary_final_png"]))) as composite:
        assert composite.size == (16, 66)
        assert composite.getpixel((2, 34)) == (21, 40, 60)
        assert composite.getpixel((10, 34)) == (121, 140, 160)
    with Image.open(Path(str(row["contact_sheet"]))) as contact_sheet:
        assert contact_sheet.size == (32, 198)
