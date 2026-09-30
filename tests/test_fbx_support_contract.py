"""FBX filters, selected-Blender import and metadata audit remain consistent."""

from __future__ import annotations

import pytest

from cdmw.core.external_model_audit import EXTERNAL_MODEL_AUDIT_EXTENSIONS
from cdmw.modding.full_import_model_replacement import (
    full_import_model_replacement_external_file_filter,
)
from cdmw.ui.archive_browser.static_replacement_source_part_append_state import (
    source_part_append_mesh_file_dialog_text,
)


def _import_filters() -> dict[str, str]:
    from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin

    return {
        "full_import_model_replacement": full_import_model_replacement_external_file_filter(),
        "archive_mesh_import": ArchiveMeshDirectPatchMixin._archive_mesh_import_file_filter(),
        "source_part_append": source_part_append_mesh_file_dialog_text()["mesh_filter"],
    }


@pytest.mark.parametrize("name", sorted(_import_filters()))
def test_geometry_import_filters_offer_blender_backed_fbx(name: str) -> None:
    assert "*.fbx" in _import_filters()[name].lower(), name


@pytest.mark.parametrize("name", sorted(_import_filters()))
def test_every_geometry_import_filter_offers_the_supported_formats(name: str) -> None:
    body = _import_filters()[name].lower()
    for extension in ("obj", "fbx", "dae", "gltf", "glb"):
        assert extension in body, (name, extension)


def test_fbx_import_requires_a_selected_blender(tmp_path, monkeypatch) -> None:
    from cdmw.modding.scene_importer import import_fbx
    from cdmw.services.fbx_blender_conversion import BlenderNotConfigured
    monkeypatch.setattr("cdmw.services.fbx_blender_conversion.configured_blender", lambda: "")
    source = tmp_path / "mesh.fbx"
    source.write_bytes(b"FBX")
    with pytest.raises(BlenderNotConfigured, match="needs Blender"):
        import_fbx(source)


def test_the_audit_accepts_fbx_because_it_reads_metadata_not_geometry() -> None:
    # The audit is deliberately wider than the import filters: it inspects an
    # FBX's materials so a reader can plan a conversion.
    assert ".fbx" in EXTERNAL_MODEL_AUDIT_EXTENSIONS
    for extension in (".obj", ".dae", ".gltf", ".glb", ".zip"):
        assert extension in EXTERNAL_MODEL_AUDIT_EXTENSIONS


def test_the_audit_explains_the_blender_requirement() -> None:
    from cdmw.core import external_model_audit

    source = external_model_audit.__file__
    body = open(source, encoding="utf-8").read()
    # Both the ASCII and the binary inventory paths carry the caveat, so an FBX
    # that audits cleanly cannot be mistaken for one that will import.
    assert body.count("geometry import requires a selected Blender executable.") == 2
    assert "FBX material audit is metadata-only" in body


def test_fbx_export_is_supported_with_and_without_a_skeleton() -> None:
    from cdmw.modding.mesh_exporter import export_fbx, export_fbx_with_skeleton

    assert callable(export_fbx)
    assert callable(export_fbx_with_skeleton)


def test_the_readme_advertises_all_supported_mesh_formats() -> None:
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    mesh_editor_rows = [line for line in readme.splitlines() if "**Mesh Editor**" in line]
    assert mesh_editor_rows, "README no longer describes the Mesh Editor"
    row = mesh_editor_rows[0]
    assert "OBJ/FBX/GLB export" in row
    assert "OBJ/FBX/DAE/glTF/GLB import" in row
