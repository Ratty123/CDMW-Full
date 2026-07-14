from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from tools.mesh_harness.visual_audit_corpus import (
    VISUAL_AUDIT_VIEWS,
    VisualAuditAssetSpec,
    _archive_package_key,
    _remove_visual_audit_overlays,
    default_visual_audit_specs,
    validate_visual_audit_specs,
)
from tools.mesh_harness.visual_audit_cli import _visual_audit_temporary_root, _write_preparation_checkpoint
from tools.mesh_harness.visual_audit_report import build_visual_audit_composites
from tools.mesh_harness.visual_audit_review import finalize_visual_audit_review


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


def test_visual_audit_runtime_paths_do_not_embed_long_evidence_or_asset_names(tmp_path: Path) -> None:
    evidence = tmp_path / ("descriptive-evidence-name-" * 8)
    run_id = "a" * 32
    temporary_root = _visual_audit_temporary_root(evidence, run_id)
    spider = next(spec for spec in default_visual_audit_specs() if spec.asset_id.startswith("029-"))
    package_key = _archive_package_key(spider)

    assert evidence.name not in temporary_root.name
    assert temporary_root.name.endswith(run_id)
    assert len(temporary_root.name) == 45
    assert spider.asset_id not in package_key
    assert package_key.startswith("029-")
    assert len(package_key) == 12
    worst_case_resource = (
        temporary_root
        / "packages"
        / "archive-browser"
        / package_key
        / "textures"
        / "combined"
        / "batch_002_03_standard_v2_material_roughness.png"
    )
    assert len(str(worst_case_resource)) < 260


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


def test_visual_audit_preparation_checkpoint_is_incremental_and_run_correlated(tmp_path: Path) -> None:
    _write_preparation_checkpoint(
        tmp_path,
        run_id="a" * 32,
        temporary_root=tmp_path / "packages",
        payload={
            "schema": "cdmw_mesh_visual_audit_preparation_checkpoint_v1",
            "requested_asset_count": 30,
            "prepared_asset_count": 7,
            "complete": False,
        },
    )

    payload = (tmp_path / "preparation-checkpoint.json").read_text(encoding="utf-8")
    assert '"prepared_asset_count": 7' in payload
    assert '"run_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"' in payload
    assert '"complete": false' in payload


def test_visual_audit_renderer_contract_is_resident_direct_and_vortice_only() -> None:
    batch = (DOTNET_ROOT / "VisualAuditBatch.cs").read_text(encoding="utf-8")
    entry = (DOTNET_ROOT / "ProgramEntry.cs").read_text(encoding="utf-8")
    d3d11 = (DOTNET_ROOT / "D3D11MaterialViewport.ResidentScene.cs").read_text(encoding="utf-8")
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
    assert "var rendererYaw = -yaw;" in batch
    assert '"archive_to_dotnet_inverted_yaw"' in batch
    assert "500.0f / size" in batch
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
        tmp_path,
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
    assert Path(str(row["contact_sheet"])).parent == tmp_path / "contact-sheets"
    assert all(
        Path(str(path)).is_relative_to(tmp_path / "comparisons")
        for path in dict(row["candidate_comparisons"]).values()
    )


def test_visual_audit_review_finalizer_requires_complete_structured_verdicts(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    runtime = evidence / "runtime"
    comparison = tmp_path / "comparison.png"
    contact = tmp_path / "contact.png"
    runtime.mkdir(parents=True)
    Image.new("RGB", (6, 4), (31, 47, 63)).save(comparison)
    Image.new("RGB", (6, 4), (7, 11, 13)).save(contact)
    run_id = "b" * 32
    asset_id = "001-test"

    def write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    write_json(
        evidence / "corpus.json",
        {
            "run_id": run_id,
            "assets": [
                {
                    "index": 1,
                    "asset_id": asset_id,
                    "virtual_path": "character/model/test.pac",
                    "archive_provenance": {"pamt_path": "0.pamt", "paz_path": "0.paz"},
                    "model_category": "weapon_sword",
                    "expected_material_families": ["standard_v2"],
                    "shader_profile_classification": ["standard_v2"],
                    "expected_texture_channels": ["base", "normal", "material"],
                    "alpha_modes": ["opaque"],
                }
            ],
        },
    )
    write_json(
        runtime / "composites.json",
        {
            "assets": [
                {
                    "id": asset_id,
                    "candidate_comparisons": {"side": str(comparison)},
                    "contact_sheet": str(contact),
                }
            ]
        },
    )
    write_json(runtime / "archive-browser-capture.json", {"ok": True, "assets": [{"id": asset_id, "ok": True}]})
    write_json(
        runtime / "dotnet-capture.json",
        {"ok": True, "renderer_session": {"viewport_create_count": 1}, "assets": [{"id": asset_id, "ok": True}]},
    )
    write_json(runtime / "integrity.json", {"ok": True})
    write_json(runtime / "archive-fingerprints-before.json", {"archive": {"sha256": "same"}})
    write_json(runtime / "archive-fingerprints-after.json", {"archive": {"sha256": "same"}})
    verdicts = tmp_path / "verdicts.json"
    write_json(
        verdicts,
        {
            "run_id": run_id,
            "assets": [
                {
                    "id": asset_id,
                    "selected_camera_angle": "side",
                    "archive_browser_verdict": "PASS",
                    "mesh_editor_verdict": "CONCERN",
                    "overall_verdict": "CONCERN",
                    "defect_categories": ["metallic_roughness"],
                    "visual_observations": "Stable base identity; highlight width needs source confirmation.",
                    "likely_cause": "Presentation or packed-channel interpretation remains ambiguous.",
                    "confidence": "medium",
                    "code_changes_made": "No production material change for this observation.",
                    "targeted_validation_performed": "Six-angle direct renderer comparison.",
                    "remaining_uncertainty": "No real-game parity claim.",
                }
            ],
        },
    )

    summary = finalize_visual_audit_review(evidence, verdicts)

    assert summary["status"] == "complete_visual_review"
    assert summary["concern_count"] == 1
    assert summary["archive_sources_unchanged"] is True
    final_path = evidence / "final" / f"{asset_id}.png"
    assert final_path.read_bytes() == comparison.read_bytes()
    review = (evidence / "review.md").read_text(encoding="utf-8")
    assert "Archive Browser verdict: PASS" in review
    assert "Mesh Editor verdict: CONCERN" in review
