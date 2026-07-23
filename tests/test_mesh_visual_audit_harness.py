from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from tools.mesh_editor_visual_audit_refresh_dotnet import (
    _link_or_copy_tree,
    _matching_source_assets,
    _reused_runtime_assets,
)
from tools.mesh_harness.archive_provenance import _apply_resolved_material_transport
from tools.mesh_harness.visual_audit_corpus import (
    VISUAL_AUDIT_VIEWS,
    VisualAuditAssetSpec,
    _remove_visual_audit_overlays,
    _resume_visual_audit_state,
    default_visual_audit_specs,
    validate_visual_audit_specs,
)
from tools.mesh_harness.visual_audit_package import stabilize_visual_audit_archive_package
from tools.mesh_harness.visual_audit_cli import (
    _atomic_write_json,
    _dotnet_assembly_path,
    _load_preparation_resume,
    _load_specs,
    _publish_or_verify_package_seal,
    _visual_audit_temporary_root,
    _write_commands,
    _write_preparation_checkpoint,
)
from tools.mesh_harness.visual_audit_capture import (
    _DOTNET_AUDIT_PRESENTATION_PROFILE,
    _dotnet_audit_presentation_is_safe,
)
from tools.mesh_harness.visual_audit_report import build_visual_audit_composites
from tools.mesh_harness.visual_audit_review import (
    _validate_verdict_row,
    finalize_visual_audit_review,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"
FOLLOWUP_MANIFEST = (
    ROOT / "tools" / "mesh_harness" / "visual_audit_followup_72.manifest.json"
)
THIRD_PASS_MANIFEST = (
    ROOT / "tools" / "mesh_harness" / "visual_audit_followup_90.manifest.json"
)
FOURTH_PASS_MANIFEST = (
    ROOT / "tools" / "mesh_harness" / "visual_audit_followup_120.manifest.json"
)
FIFTH_PASS_MANIFEST = (
    ROOT / "tools" / "mesh_harness" / "visual_audit_followup_fifth_120.manifest.json"
)
MATERIAL_REGRESSION_MANIFEST = (
    ROOT / "tools" / "mesh_harness" / "visual_audit_material_regression_15.manifest.json"
)


def test_visual_audit_rejects_dotnet_apphost_as_an_assembly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"cdmw-mesh-dotnet-editor\.dll"):
        _dotnet_assembly_path(
            Namespace(dotnet_assembly=tmp_path / "cdmw-mesh-dotnet-editor.exe")
        )


def test_visual_audit_hydration_preserves_pac_reference_and_rebases_only_transport(
    tmp_path: Path,
) -> None:
    declared = "tree/texture/branch_broad_cotton_01_color.dds"
    extracted = tmp_path / "branch_broad_cotton_01.dds"
    material_input = SimpleNamespace(
        source_texture_path=declared,
        source_dds_path="character/texture/branch_broad_cotton_01.dds",
    )

    _apply_resolved_material_transport(
        material_input,
        virtual_source=material_input.source_dds_path,
        archive_path="character/texture/branch_broad_cotton_01.dds",
        source_path=extracted,
    )

    assert material_input.source_texture_path == declared
    assert material_input.source_dds_path == str(extracted.resolve())


def test_visual_audit_resume_preserves_a_bounded_manifest_selection() -> None:
    source = (ROOT / "tools" / "mesh_harness" / "visual_audit_cli.py").read_text(
        encoding="utf-8"
    )

    assert "specs = specs[: max(1, args.limit)]" in source
    assert "allow_partial=bool(args.limit > 0)" in source
    assert "--resume-prepare cannot be combined with --limit" not in source


def test_visual_audit_rerun_commands_preserve_custom_manifest(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    manifest = tmp_path / "custom corpus.json"
    game_root = tmp_path / "game"
    temporary_root = tmp_path / "temporary"
    evidence.mkdir()
    manifest.write_text('{"assets": []}', encoding="utf-8")

    _write_commands(
        evidence,
        Namespace(game_root=game_root, manifest=manifest),
        temporary_root,
    )

    commands = (evidence / "commands.md").read_text(encoding="utf-8")
    assert f'--manifest "{manifest.resolve()}"' in commands
    assert commands.count(f'--manifest "{manifest.resolve()}"') == 4
    assert "--phase seal" in commands
    assert "--phase capture" in commands


def test_visual_audit_seal_is_idempotent_but_refuses_rebaseline(
    tmp_path: Path,
) -> None:
    seal_path = tmp_path / "prepared-package-fingerprints.json"
    baseline = {"schema": "seal", "aggregate_sha256": "a" * 64}

    assert _publish_or_verify_package_seal(
        seal_path,
        baseline,
        allow_replace=False,
    ) == "Sealed prepared package trees"
    baseline_bytes = seal_path.read_bytes()
    assert _publish_or_verify_package_seal(
        seal_path,
        baseline,
        allow_replace=False,
    ) == "Verified prepared package seal"
    assert seal_path.read_bytes() == baseline_bytes

    with pytest.raises(ValueError, match="refuse resealing"):
        _publish_or_verify_package_seal(
            seal_path,
            {"schema": "seal", "aggregate_sha256": "b" * 64},
            allow_replace=False,
        )
    seal_path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        _publish_or_verify_package_seal(
            seal_path,
            baseline,
            allow_replace=False,
        )


def test_dotnet_refresh_reuses_only_exactly_matching_source_assets() -> None:
    corpus = {
        "assets": [
            {
                "asset_id": "001-test",
                "virtual_path": "character/model/test.pac",
            }
        ]
    }
    state = {
        "runtime_assets": [
            {
                "id": "001-test",
                "virtual_path": "CHARACTER\\MODEL\\TEST.PAC",
                "archive_package_dir": "archive-package",
                "dotnet_package_dir": "dotnet-package",
                "views": [],
            }
        ]
    }

    rows = _matching_source_assets(corpus, state)

    assert len(rows) == 1
    assert rows[0]["id"] == "001-test"
    mismatched = json.loads(json.dumps(state))
    mismatched["runtime_assets"][0]["virtual_path"] = "character/model/other.pac"
    with pytest.raises(ValueError, match="virtual path mismatch"):
        _matching_source_assets(corpus, mismatched)


def test_dotnet_refresh_links_or_copies_immutable_archive_package(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "textures"
    nested.mkdir(parents=True)
    (source / "manifest.json").write_text('{"ok":true}', encoding="utf-8")
    (nested / "base.png").write_bytes(b"image-bytes")
    target = tmp_path / "target"

    _link_or_copy_tree(source, target)

    assert (target / "manifest.json").read_text(encoding="utf-8") == '{"ok":true}'
    assert (target / "textures" / "base.png").read_bytes() == b"image-bytes"
    assert (source / "textures" / "base.png").read_bytes() == b"image-bytes"


def test_dotnet_refresh_can_reuse_complete_packages_for_renderer_only_capture(
    tmp_path: Path,
) -> None:
    archive_package = tmp_path / "archive"
    dotnet_package = tmp_path / "dotnet"
    archive_package.mkdir()
    dotnet_package.mkdir()
    (archive_package / "manifest.json").write_text("{}", encoding="utf-8")
    for name in ("dotnet_scene.json", "net_materials.json", "scene.obj"):
        (dotnet_package / name).write_text("ready", encoding="utf-8")

    rows = _reused_runtime_assets(
        (
            {
                "id": "001-test",
                "virtual_path": "character/model/test.pac",
                "archive_package_dir": str(archive_package),
                "dotnet_package_dir": str(dotnet_package),
                "views": [{"name": "front", "yaw": 0.0, "pitch": 0.0}],
                "run_id": "source-run",
            },
        ),
        run_id="recapture-run",
        temporary_root=tmp_path / "recapture",
    )

    archive_target = tmp_path / "recapture" / "packages" / "archive-browser" / "archive"
    dotnet_target = tmp_path / "recapture" / "packages" / "mesh-editor" / "dotnet"
    assert rows == (
        {
            "id": "001-test",
            "virtual_path": "character/model/test.pac",
            "archive_package_dir": str(archive_target),
            "dotnet_package_dir": str(dotnet_target),
            "views": [{"name": "front", "yaw": 0.0, "pitch": 0.0}],
            "run_id": "recapture-run",
            "archive_package_stability": {},
            "package_reuse": "renderer_only_recapture",
        },
    )
    assert (archive_target / "manifest.json").read_text(encoding="utf-8") == "{}"
    assert (dotnet_target / "dotnet_scene.json").read_text(encoding="utf-8") == "ready"


def test_dotnet_refresh_rebases_stabilized_archive_texture_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    transient = tmp_path / "transient"
    source.mkdir()
    transient.mkdir()
    source_dds = transient / "base.dds"
    source_dds.write_bytes(b"durable-dds")
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "dds_textures": {
                            "base": {
                                "source_path": str(source_dds),
                                "available": True,
                                "direct_upload_candidate": True,
                            }
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stabilize_visual_audit_archive_package(source)
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    source_stable_dds = Path(
        source_manifest["batches"][0]["dds_textures"]["base"]["source_path"]
    )
    target = tmp_path / "target"

    _link_or_copy_tree(source, target)
    stabilize_visual_audit_archive_package(target)
    target_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    target_stable_dds = Path(
        target_manifest["batches"][0]["dds_textures"]["base"]["source_path"]
    )

    source_dds.unlink()
    source_stable_dds.unlink()
    assert target_stable_dds.is_relative_to(target.resolve())
    assert target_stable_dds.read_bytes() == b"durable-dds"


def test_dotnet_refresh_tool_preserves_provenance_and_uses_production_paths() -> None:
    source = (ROOT / "tools" / "mesh_editor_visual_audit_refresh_dotnet.py").read_text(
        encoding="utf-8"
    )

    assert "_validate_prepared_state(" in source
    assert "_validated_fingerprint_paths(" in source
    assert "_hydrate_real_archive_mesh_materials(" in source
    assert "build_mesh_dotnet_experiment_package(" in source
    assert "_link_or_copy_tree(archive_source, archive_target)" in source
    assert "stabilize_visual_audit_archive_package(archive_target)" in source
    assert "--reuse-dotnet-packages" in source
    assert '"dotnet_packages_reused": args.reuse_dotnet_packages' in source
    assert "read_isolated_d3d11_preview_manifest(archive_target)" in source
    assert "apply_dotnet_native_material_batch_bindings(" in source
    stabilized = source.index("stabilize_visual_audit_archive_package(archive_target)")
    manifest = source.index("read_isolated_d3d11_preview_manifest(archive_target)")
    applied = source.index("apply_dotnet_native_material_batch_bindings(", manifest)
    built = source.index("package = build_mesh_dotnet_experiment_package(")
    assert stabilized < manifest < applied < built
    assert '"archive_packages_reused": True' in source
    assert '"archive_packages_rebased": not args.reuse_dotnet_packages' in source
    assert '"dotnet_packages_rebuilt": not args.reuse_dotnet_packages' in source
    assert "--phase capture" in source


def test_visual_audit_packages_the_exact_prepared_archive_material_bindings() -> None:
    source = (ROOT / "tools" / "mesh_harness" / "visual_audit_corpus.py").read_text(
        encoding="utf-8"
    )
    provenance = (
        ROOT / "tools" / "mesh_harness" / "archive_provenance.py"
    ).read_text(encoding="utf-8")

    assert "preview_model=preview_result.preview_model" in source
    assert "build_archive_preview_result(\n        entry,\n        ()," in source
    assert "build_archive_preview_result(\n            model_entry,\n            ()," in provenance
    assert "build_archive_preview_result(\n        None,\n        entry," not in source
    assert "build_archive_preview_result(\n            None,\n            model_entry," not in provenance
    prepared = source.index("prepared_model, _prepared_preview = prepare_model_preview(")
    stripped = source.index("comparison_overlays = _remove_visual_audit_overlays(prepared_model)")
    copied = source.index("copy_dotnet_preview_material_bindings(mesh, prepared_model)")
    state = source.index("material_state = mesh_dotnet_material_state_payload(")
    dotnet_package = source.index("dotnet_package = build_mesh_dotnet_experiment_package(")
    shared_package = source.index('"same_package_for_archive_and_mesh_editor": True')
    assert prepared < stripped < copied < state < dotnet_package < shared_package
    assert "write_isolated_d3d11_preview_package(" not in source


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


def test_followup_visual_audit_corpus_is_large_unique_and_excludes_original_corpus() -> None:
    specs = _load_specs(FOLLOWUP_MANIFEST)
    original_paths = {spec.virtual_path.casefold() for spec in default_visual_audit_specs()}

    assert len(specs) == 72
    assert len({spec.asset_id for spec in specs}) == 72
    assert len({spec.virtual_path.casefold() for spec in specs}) == 72
    assert not original_paths & {spec.virtual_path.casefold() for spec in specs}
    assert validate_visual_audit_specs(specs) == {
        "weapon": 15,
        "sword": 5,
        "armor": 14,
        "body": 13,
        "hair_fur_feather": 17,
        "unusual": 20,
    }
    payload = json.loads(FOLLOWUP_MANIFEST.read_text(encoding="utf-8"))
    for tag, minimum in payload["required_coverage"].items():
        assert sum(tag in spec.coverage_tags for spec in specs) >= minimum


def test_third_visual_audit_corpus_is_diverse_unique_and_excludes_both_prior_corpora() -> None:
    specs = _load_specs(THIRD_PASS_MANIFEST)
    original_paths = {spec.virtual_path.casefold() for spec in default_visual_audit_specs()}
    followup_paths = {spec.virtual_path.casefold() for spec in _load_specs(FOLLOWUP_MANIFEST)}
    selected_paths = {spec.virtual_path.casefold() for spec in specs}

    assert len(specs) == 90
    assert len({spec.asset_id for spec in specs}) == 90
    assert len(selected_paths) == 90
    assert not (original_paths | followup_paths) & selected_paths
    assert validate_visual_audit_specs(specs) == {
        "weapon": 22,
        "sword": 5,
        "armor": 28,
        "body": 5,
        "hair_fur_feather": 5,
        "unusual": 26,
    }
    payload = json.loads(THIRD_PASS_MANIFEST.read_text(encoding="utf-8"))
    excluded_paths = {str(value).casefold() for value in payload["excluded_virtual_paths"]}
    assert excluded_paths == original_paths | followup_paths
    for tag, minimum in payload["required_coverage"].items():
        assert sum(tag in spec.coverage_tags for spec in specs) >= minimum


def test_fourth_visual_audit_corpus_adds_120_balanced_nonoverlapping_pacs() -> None:
    specs = _load_specs(FOURTH_PASS_MANIFEST)
    selected_paths = {spec.virtual_path.casefold() for spec in specs}
    prior_paths = {
        spec.virtual_path.casefold()
        for manifest_specs in (
            default_visual_audit_specs(),
            _load_specs(FOLLOWUP_MANIFEST),
            _load_specs(THIRD_PASS_MANIFEST),
        )
        for spec in manifest_specs
    }

    assert len(specs) == 120
    assert len({spec.asset_id for spec in specs}) == 120
    assert len(selected_paths) == 120
    assert not prior_paths & selected_paths
    assert validate_visual_audit_specs(specs) == {
        "weapon": 40,
        "sword": 16,
        "armor": 52,
        "body": 8,
        "hair_fur_feather": 10,
        "unusual": 12,
    }
    payload = json.loads(FOURTH_PASS_MANIFEST.read_text(encoding="utf-8"))
    excluded_paths = {str(value).casefold() for value in payload["excluded_virtual_paths"]}
    assert len(excluded_paths) == 197
    assert prior_paths <= excluded_paths
    assert not selected_paths & excluded_paths
    for tag, minimum in payload["required_coverage"].items():
        assert sum(tag in spec.coverage_tags for spec in specs) >= minimum


def test_fifth_visual_audit_corpus_adds_120_material_first_nonoverlapping_pacs() -> None:
    specs = _load_specs(FIFTH_PASS_MANIFEST)
    selected_paths = {spec.virtual_path.casefold() for spec in specs}
    prior_paths = {
        spec.virtual_path.casefold()
        for manifest_specs in (
            default_visual_audit_specs(),
            _load_specs(FOLLOWUP_MANIFEST),
            _load_specs(THIRD_PASS_MANIFEST),
            _load_specs(FOURTH_PASS_MANIFEST),
        )
        for spec in manifest_specs
    }

    assert len(specs) == 120
    assert len({spec.asset_id for spec in specs}) == 120
    assert len(selected_paths) == 120
    assert len(prior_paths) == 312
    assert not prior_paths & selected_paths
    assert validate_visual_audit_specs(specs) == {
        "weapon": 40,
        "sword": 16,
        "armor": 52,
        "body": 8,
        "hair_fur_feather": 10,
        "unusual": 12,
    }
    payload = json.loads(FIFTH_PASS_MANIFEST.read_text(encoding="utf-8"))
    excluded_paths = {str(value).casefold() for value in payload["excluded_virtual_paths"]}
    assert len(excluded_paths) == 317
    assert prior_paths <= excluded_paths
    assert not selected_paths & excluded_paths
    assert all("fifth-pass" in spec.selection_reason.casefold() for spec in specs)
    for tag, minimum in payload["required_coverage"].items():
        assert sum(tag in spec.coverage_tags for spec in specs) >= minimum


def test_material_regression_manifest_covers_soft_metal_and_alpha_controls() -> None:
    specs = _load_specs(MATERIAL_REGRESSION_MANIFEST)
    payload = json.loads(MATERIAL_REGRESSION_MANIFEST.read_text(encoding="utf-8"))

    assert len(specs) == 15
    assert len({spec.asset_id for spec in specs}) == 15
    assert len({spec.virtual_path.casefold() for spec in specs}) == 15
    assert all("regression" in spec.coverage_tags for spec in specs)
    for tag, minimum in payload["required_coverage"].items():
        assert sum(tag in spec.coverage_tags for spec in specs) >= minimum


def test_visual_audit_manifest_constraints_reject_partial_overlap_and_missing_tags(
    tmp_path: Path,
) -> None:
    original = default_visual_audit_specs()[0]
    path = tmp_path / "manifest.json"
    payload = {
        "minimum_asset_count": 2,
        "assets": [
            {
                "asset_id": "001-probe",
                "virtual_path": original.virtual_path,
                "model_category": "probe",
                "coverage_tags": ["probe"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="requires at least 2 assets"):
        _load_specs(path)

    payload["minimum_asset_count"] = 1
    payload["excluded_virtual_paths"] = [original.virtual_path.upper().replace("/", "\\")]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="reuses excluded PAC paths"):
        _load_specs(path)

    payload.pop("excluded_virtual_paths")
    payload["required_coverage"] = {"shield_layer": 1}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="coverage is incomplete"):
        _load_specs(path)


def test_visual_audit_runtime_paths_do_not_embed_long_evidence_or_asset_names(tmp_path: Path) -> None:
    evidence = tmp_path / ("descriptive-evidence-name-" * 8)
    run_id = "a" * 32
    temporary_root = _visual_audit_temporary_root(evidence, run_id)
    assert evidence.name not in temporary_root.name
    assert temporary_root.name.endswith(run_id)
    assert len(temporary_root.name) == 45
    worst_case_resource = (
        temporary_root
        / "packages"
        / "mesh-editor"
        / "canonical-package"
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


def test_visual_audit_atomic_json_retries_transient_windows_replace_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.mesh_harness import visual_audit_cli

    path = tmp_path / "checkpoint.json"
    path.write_text('{"prepared_asset_count": 1}\n', encoding="utf-8")
    real_replace = visual_audit_cli.os.replace
    replace_calls = 0

    def flaky_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls < 3:
            raise PermissionError(5, "Access is denied", str(destination))
        real_replace(source, destination)

    monkeypatch.setattr(visual_audit_cli.os, "replace", flaky_replace)
    monkeypatch.setattr(visual_audit_cli.time, "sleep", lambda _delay: None)

    _atomic_write_json(path, {"prepared_asset_count": 2})

    assert replace_calls == 3
    assert json.loads(path.read_text(encoding="utf-8")) == {"prepared_asset_count": 2}


def test_visual_audit_preparation_resume_reuses_only_an_exact_manifest_prefix(tmp_path: Path) -> None:
    spec = VisualAuditAssetSpec(
        index=1,
        asset_id="001-test",
        virtual_path="character/model/test.pac",
        model_category="test",
        coverage_tags=("unusual",),
        selection_reason="test",
    )
    game_root = tmp_path / "game"
    pamt_path = game_root / "0009" / "0.pamt"
    checkpoint = {
        "schema": "cdmw_mesh_visual_audit_preparation_checkpoint_v1",
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "requested_asset_count": 1,
        "prepared_asset_count": 1,
        "coverage": {"unusual": 1},
        "assets": [{"asset_id": spec.asset_id, "virtual_path": spec.virtual_path}],
        "runtime_assets": [{"id": spec.asset_id, "virtual_path": spec.virtual_path}],
        "archive_fingerprint_paths": [str(pamt_path)],
        "complete": True,
    }

    rows, runtime_assets, fingerprints = _resume_visual_audit_state(
        checkpoint,
        specs=(spec,),
        game_root=game_root.resolve(),
        pamt_path=pamt_path.resolve(),
        coverage={"unusual": 1},
    )

    assert rows[0]["asset_id"] == spec.asset_id
    assert runtime_assets[0]["id"] == spec.asset_id
    assert fingerprints == {pamt_path.resolve()}
    changed = VisualAuditAssetSpec(
        index=1,
        asset_id=spec.asset_id,
        virtual_path="character/model/changed.pac",
        model_category=spec.model_category,
        coverage_tags=spec.coverage_tags,
        selection_reason=spec.selection_reason,
    )
    with pytest.raises(ValueError, match="manifest prefix"):
        _resume_visual_audit_state(
            checkpoint,
            specs=(changed,),
            game_root=game_root.resolve(),
            pamt_path=pamt_path.resolve(),
            coverage={"unusual": 1},
        )


def test_visual_audit_preparation_resume_rejects_packages_outside_owned_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    game_root = tmp_path / "game"
    game_root.mkdir()
    temporary_root = tmp_path / "cdmw-mesh-editor-visual-audit" / "run"
    archive_package = temporary_root / "archive"
    dotnet_package = temporary_root / "dotnet"
    archive_package.mkdir(parents=True)
    dotnet_package.mkdir()
    monkeypatch.setattr("tools.mesh_harness.visual_audit_cli.tempfile.gettempdir", lambda: str(tmp_path))
    _write_preparation_checkpoint(
        runtime_root,
        run_id="b" * 32,
        temporary_root=temporary_root,
        payload={
            "runtime_assets": [
                {
                    "archive_package_dir": str(archive_package),
                    "dotnet_package_dir": str(dotnet_package),
                }
            ]
        },
    )

    run_id, resumed_root, _checkpoint = _load_preparation_resume(
        runtime_root,
        game_root=game_root.resolve(),
    )

    assert run_id == "b" * 32
    assert resumed_root == temporary_root.resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = json.loads((runtime_root / "preparation-checkpoint.json").read_text(encoding="utf-8"))
    payload["runtime_assets"][0]["dotnet_package_dir"] = str(outside)
    (runtime_root / "preparation-checkpoint.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid dotnet_package_dir"):
        _load_preparation_resume(runtime_root, game_root=game_root.resolve())


def test_visual_audit_renderer_contract_is_resident_direct_and_vortice_only() -> None:
    batch = (DOTNET_ROOT / "VisualAuditBatch.cs").read_text(encoding="utf-8")
    camera = (DOTNET_ROOT / "NetViewportCamera.cs").read_text(encoding="utf-8")
    dotnet_capture = (DOTNET_ROOT / "D3D11MaterialViewport.Capture.cs").read_text(
        encoding="utf-8"
    )
    entry = (DOTNET_ROOT / "ProgramEntry.cs").read_text(encoding="utf-8")
    d3d11 = (DOTNET_ROOT / "D3D11MaterialViewport.ResidentScene.cs").read_text(encoding="utf-8")
    capture = (ROOT / "tools" / "mesh_harness" / "visual_audit_capture.py").read_text(
        encoding="utf-8"
    )
    corpus = (ROOT / "tools" / "mesh_harness" / "visual_audit_corpus.py").read_text(
        encoding="utf-8"
    )
    shared_host = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")

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
    assert "var rendererYaw = yaw;" in batch
    assert "var rendererPitch = pitch;" in batch
    assert "session.SetArchiveCamera(document, rendererYaw, rendererPitch);" in batch
    assert '["renderer_pitch"] = rendererPitch' in batch
    assert '"archive_object_rotation_basis_orthographic_v1"' in batch
    assert "NetViewportCamera.CreateArchiveAudit(" in batch
    assert "public static NetViewportCamera CreateArchiveAudit(" in camera
    assert "* Matrix4x4.CreateRotationX(pitch)" in camera
    assert "* Matrix4x4.CreateRotationY(yaw);" in camera
    assert "var worldViewProjection = world * orthographicProjection;" in camera
    assert '["rendered_camera"] = new Dictionary<string, object?>' in batch
    assert "D3D11RenderedCameraEvidence" in dotnet_capture
    assert "cameraForCapture.WorldViewProjectionRowMajorArray()" in dotnet_capture
    assert "WorldViewProjection = camera.World * captureProjection" in dotnet_capture
    assert "return NetViewportCamera.Create(" not in dotnet_capture
    assert "viewport.ApplyPresentationSettings(new D3D11PresentationSettings());" in batch
    assert '["presentation"] = viewport.PresentationEvidencePayload()' in batch
    assert "_form.CreateControl();" in batch
    assert "viewport.CreateControl();" in batch
    assert "_form.Show();" not in batch
    assert '["capture_mode"] = "hidden_hwnd_no_show"' in batch
    assert '["native_windows_remained_hidden"] = nativeWindowsRemainedHidden' in batch
    assert "500.0f / size" in batch
    assert '"process_start_count"] = 1' in batch
    assert "report = run_dotnet_capture_batch(" in capture
    assert '"backend": "d3d11_vortice_shader"' in capture
    assert '"surface": "archive_browser"' in capture
    assert '"shared_package_artifacts": True' in capture
    assert '"--visual-audit-batch"' in capture
    assert "report_path.unlink(missing_ok=True)" in capture
    assert "completed.returncode == 0" in capture
    assert 'str(report.get("run_id", "")) == run_id' in capture
    assert "def request_frame_capture(" in shared_host
    assert not (ROOT / "cdmw" / "ui" / "native_d3d11_preview_host.py").exists()
    assert not (ROOT / "native" / "cdmw_d3d11_preview" / "CMakeLists.txt").exists()
    assert "enable_material_combiner=False" in corpus
    assert "enable_material_combiner=True" not in corpus


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"cull_back_faces": True}, False),
        ({"disable_depth_test": True}, False),
        ({"tone_gamma": 1.2}, False),
        ({"sampling_filter": "trilinear"}, False),
        ({"profile": "custom"}, False),
        ({"color_pipeline": "unknown"}, False),
    ],
)
def test_visual_audit_rejects_noncanonical_or_unproven_dotnet_presentation(
    overrides: dict[str, object], expected: bool
) -> None:
    presentation = {**_DOTNET_AUDIT_PRESENTATION_PROFILE, **overrides}
    report = {
        "renderer_session": {
            "capture_mode": "hidden_hwnd_no_show",
            "native_windows_remained_hidden": True,
            "presentation": presentation,
        }
    }

    assert _dotnet_audit_presentation_is_safe(report) is expected


def test_visual_audit_rejects_missing_dotnet_presentation_evidence() -> None:
    assert _dotnet_audit_presentation_is_safe({"renderer_session": {}}) is False
    assert (
        _dotnet_audit_presentation_is_safe(
            {"renderer_session": {"presentation": {"profile": "mesh_editor_default_v1"}}}
        )
        is False
    )


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


def test_visual_audit_v2_composites_refuse_missing_capture_placeholders(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Archive Browser capture missing"):
        build_visual_audit_composites(
            {
                "schema": "cdmw_mesh_visual_audit_corpus_v2",
                "assets": [{"asset_id": "001-test", "virtual_path": "test.pac"}],
            },
            {"assets": [{"id": "001-test", "ok": False, "captures": []}]},
            {"assets": [{"id": "001-test", "ok": False, "captures": []}]},
            tmp_path,
            tmp_path / "final",
        )


def test_visual_audit_v2_composites_refuse_missing_source_board_placeholders(
    tmp_path: Path,
) -> None:
    capture_path = tmp_path / "capture.png"
    Image.new("RGB", (8, 6), (20, 40, 60)).save(capture_path)
    captures = [
        {"name": str(view["name"]), "path": str(capture_path), "ok": True}
        for view in VISUAL_AUDIT_VIEWS
    ]
    region_captures = [
        {"angle": angle, "debug_mode": mode, "path": str(capture_path), "ok": True}
        for angle, mode in (
            ("front", "final"),
            ("oblique", "final"),
            ("oblique", "base"),
            ("oblique", "normal"),
            ("oblique", "roughness"),
            ("oblique", "metallic"),
            ("oblique", "specular"),
            ("oblique", "layer_mask"),
        )
    ]
    with pytest.raises(ValueError, match="Missing: PAC / DDS source board"):
        build_visual_audit_composites(
            {
                "schema": "cdmw_mesh_visual_audit_corpus_v2",
                "assets": [
                    {
                        "asset_id": "001-test",
                        "virtual_path": "test.pac",
                        "source_boards": {
                            "boards": [
                                {
                                    "submesh_index": 0,
                                    "path": str(tmp_path / "missing-source.png"),
                                    "sha256": "0" * 64,
                                }
                            ]
                        },
                    }
                ],
            },
            {"assets": [{"id": "001-test", "ok": True, "captures": captures}]},
            {
                "assets": [
                    {
                        "id": "001-test",
                        "ok": True,
                        "captures": captures,
                        "material_regions": [
                            {
                                "source_submesh_index": 0,
                                "submesh_name": "blade",
                                "captures": region_captures,
                            }
                        ],
                    }
                ]
            },
            tmp_path,
            tmp_path / "final",
        )


def test_visual_audit_review_rejects_missing_or_unknown_material_classification() -> None:
    row = {
        "selected_camera_angle": "front",
        "archive_browser_verdict": "PASS",
        "mesh_editor_verdict": "PASS",
        "overall_verdict": "PASS",
        "defect_categories": [],
        "visual_observations": "Soft stitched regions remain matte.",
        "likely_cause": "No parity defect observed.",
        "confidence": "high",
        "code_changes_made": "None.",
        "targeted_validation_performed": "All paired views inspected.",
        "remaining_uncertainty": "None.",
    }

    with pytest.raises(ValueError, match="material classification is required"):
        _validate_verdict_row(row, require_material_classification=True)

    row["material_classification"] = ["inventory_slot_armor"]
    with pytest.raises(ValueError, match="Invalid visual-audit material classifications"):
        _validate_verdict_row(row, require_material_classification=True)


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
            "require_material_classification": True,
            "assets": [
                {
                    "id": asset_id,
                    "selected_camera_angle": "side",
                    "archive_browser_verdict": "PASS",
                    "mesh_editor_verdict": "CONCERN",
                    "overall_verdict": "CONCERN",
                    "defect_categories": ["metallic_roughness"],
                    "material_classification": ["metal", "leather"],
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
    assert summary["material_classification_required"] is True
    assert summary["assets"][0]["material_classification"] == ["metal", "leather"]
    assert summary["archive_sources_unchanged"] is True
    final_path = evidence / "final" / f"{asset_id}.png"
    assert final_path.read_bytes() == comparison.read_bytes()
    review = (evidence / "review.md").read_text(encoding="utf-8")
    assert "Archive Browser verdict: PASS" in review
    assert "Mesh Editor verdict: CONCERN" in review
    assert 'Visual material classification: `["metal", "leather"]`' in review
