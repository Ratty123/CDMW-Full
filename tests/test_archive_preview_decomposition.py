from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import subprocess
import sys
import threading
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core import archive_mesh_import_preview, archive_model_textures
from cdmw.core import archive_model_texture_config
from cdmw.core.archive_mesh_import_build import build_mesh_import_preview
from cdmw.core.archive_mesh_import_scene_preview import attach_scene_preview_textures
from cdmw.core.archive_mesh_import_validation import _build_sidecar_binding_validation
from cdmw.core.archive_mesh_types import MeshImportSupplementalFileSpec
from cdmw.core.archive_model_references import _ArchiveModelSidecarTextureBinding
from cdmw.core.archive_model_texture_reporting import build_archive_model_texture_references
from cdmw.core.archive_model_texture_support_attach import _attach_model_support_texture_preview_paths
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh, RunCancelled
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
OWNER_GLOBS = ("archive_mesh_import*.py", "archive_model_texture*.py")


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0000/0.pamt"),
        paz_file=Path("0000/1.paz"),
        offset=1,
        comp_size=2,
        orig_size=3,
        flags=0,
        paz_index=1,
    )


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_preview_facades_reexport_owner_objects() -> None:
    assert archive_mesh_import_preview.build_mesh_import_preview is build_mesh_import_preview
    assert archive_mesh_import_preview.attach_scene_preview_textures is attach_scene_preview_textures
    assert archive_mesh_import_preview._build_sidecar_binding_validation is _build_sidecar_binding_validation
    assert archive_model_textures.build_archive_model_texture_references is build_archive_model_texture_references
    assert (
        archive_model_textures._attach_model_support_texture_preview_paths
        is _attach_model_support_texture_preview_paths
    )


def test_model_texture_preview_limits_stay_visible_through_facade() -> None:
    original = archive_model_textures._MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
    original_low = archive_model_textures._MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
    try:
        archive_model_textures.set_model_texture_display_preview_max_dimension(2048, low_quality_value=192)
        assert (
            archive_model_textures._MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
            == archive_model_texture_config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
        )
        assert (
            archive_model_textures._MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
            == archive_model_texture_config.MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
        )
    finally:
        archive_model_textures.set_model_texture_display_preview_max_dimension(
            original,
            low_quality_value=original_low,
        )


def test_preview_owner_import_order_preserves_identity() -> None:
    scripts = (
        "from cdmw.core.archive_mesh_import_build import build_mesh_import_preview as o; "
        "from cdmw.core import archive_mesh_import_preview as f; assert f.build_mesh_import_preview is o",
        "from cdmw.core import archive_mesh_import_preview as f; "
        "from cdmw.core.archive_mesh_import_build import build_mesh_import_preview as o; "
        "assert f.build_mesh_import_preview is o",
        "from cdmw.core.archive_model_texture_reporting import build_archive_model_texture_references as o; "
        "from cdmw.core import archive_model_textures as f; assert f.build_archive_model_texture_references is o",
        "from cdmw.core import archive_model_textures as f; "
        "from cdmw.core.archive_model_texture_reporting import build_archive_model_texture_references as o; "
        "assert f.build_archive_model_texture_references is o",
    )
    for script in scripts:
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=30)


def test_preview_owners_are_bounded_and_have_no_wildcard_imports() -> None:
    paths = {
        path
        for pattern in OWNER_GLOBS
        for path in (ROOT / "cdmw" / "core").glob(pattern)
    }
    assert paths
    for path in paths:
        source = path.read_text(encoding="utf-8-sig")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, f"{path}:{node.name}"
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names), path


def test_model_texture_reference_provenance_golden() -> None:
    source = _entry("character/model/body.pac")
    base = _entry("character/texture/body_d.dds")
    normal = _entry("character/texture/body_n.dds")
    by_path = defaultdict(list)
    by_name = defaultdict(list)
    for entry in (base, normal):
        by_path[entry.path.lower()].append(entry)
        by_name[Path(entry.path).name.lower()].append(entry)
    model = ModelPreviewData(
        path=source.path,
        meshes=[
            ModelPreviewMesh(
                material_name="Body",
                texture_name=base.path,
                preview_texture_path="preview://body",
            )
        ],
    )
    bindings = (
        _ArchiveModelSidecarTextureBinding(
            base.path,
            "_baseColorTexture",
            "Body",
            sidecar_kind="pac_xml",
            sidecar_path="character/modelproperty/body.pac_xml",
            linked_mesh_path=source.path,
        ),
        _ArchiveModelSidecarTextureBinding(
            normal.path,
            "_normalTexture",
            "Body",
            sidecar_kind="pac_xml",
            sidecar_path="character/modelproperty/body.pac_xml",
            linked_mesh_path=source.path,
        ),
    )
    references = build_archive_model_texture_references(
        source,
        model,
        sidecar_texture_references=bindings,
        texture_entries_by_normalized_path=by_path,
        texture_entries_by_basename=by_name,
    )
    fields = (
        "reference_name",
        "material_name",
        "semantic_label",
        "semantic_hint",
        "sidecar_kind",
        "linked_mesh_path",
        "resolution_status",
        "resolved_archive_path",
        "preview_texture_path",
        "usage_count",
        "reference_kind",
        "relation_group",
        "relation_confidence",
    )
    payload = [{field: getattr(reference, field) for field in fields} for reference in references]
    assert _digest(payload) == "05c3c97acbad5b89d19263fa3d6be31d3689e9e842296d3dd57b8b2d85093b66"


def test_sidecar_binding_validation_golden() -> None:
    original = SimpleNamespace(
        texture_path="character/texture/body_d.dds",
        parameter_name="_baseColorTexture",
        submesh_name="Body",
        sidecar_path="character/modelproperty/body.pac_xml",
    )
    selected = SimpleNamespace(
        texture_path="character/texture/body_alt_d.dds",
        parameter_name="_baseColorTexture",
        submesh_name="Body",
        sidecar_path="body.pac_xml",
    )
    result = _build_sidecar_binding_validation(
        original_sidecar_bindings=(original,),
        selected_sidecar_bindings=(selected,),
        supplemental_file_specs=(
            MeshImportSupplementalFileSpec(
                Path("body.pac_xml"),
                "character/modelproperty/body.pac_xml",
                "sidecar",
            ),
        ),
    )
    payload = {
        "diffs": [dataclasses.asdict(diff) for diff in result[0]],
        "issues": [
            {
                "code": issue.code,
                "status": issue.status,
                "detail": issue.detail,
                "diffs": [diff.field_name for diff in issue.diffs],
            }
            for issue in result[1]
        ],
        "summary": result[2],
        "warning": result[3],
        "manual": result[4],
    }
    assert _digest(payload) == "5f0746dc902770f0f7bc98d9806397321b5d405434b727c3256f7f553a727666"


def test_model_support_attachment_honors_pre_cancel() -> None:
    stop_event = threading.Event()
    stop_event.set()
    model = ModelPreviewData(
        path="character/model/body.pac",
        meshes=[ModelPreviewMesh(material_name="Body", texture_name="Body")],
    )
    binding = _ArchiveModelSidecarTextureBinding(
        "character/texture/body_n.dds",
        "_normalTexture",
        "Body",
    )
    with pytest.raises(RunCancelled):
        _attach_model_support_texture_preview_paths(
            _entry(model.path),
            model,
            sidecar_texture_bindings=(binding,),
            texture_entries_by_normalized_path={},
            texture_entries_by_basename={},
            stop_event=stop_event,
        )
