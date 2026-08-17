"""What FBX is and is not supported for, pinned in one place.

The audit that prompted this test read FBX-handling code in several modules
beside import filters that omit `.fbx`, and could not tell whether FBX was
intentionally unsupported or merely hidden. It is intentional, and the code
already agrees with itself:

* geometry **import** is not supported, and the Geometry append path says so;
* mesh **export** to FBX is supported, with or without an armature;
* the external-model **audit** reads FBX material metadata only, and says that
  geometry import still needs another format;
* the scene-import report can parse FBX through native ufbx, but reports rig and
  animation as report-only and degrades to `ufbx_unavailable` without it.

The risk is drift: a filter gaining `.fbx` without a parser, or a parser landing
without the filters and messages following. This pins all four surfaces
together so any half-move fails here.
"""

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
def test_no_geometry_import_filter_offers_fbx(name: str) -> None:
    """Offering it without a parser is the failure this pins against."""
    assert "fbx" not in _import_filters()[name].lower(), name


@pytest.mark.parametrize("name", sorted(_import_filters()))
def test_every_geometry_import_filter_offers_the_supported_formats(name: str) -> None:
    body = _import_filters()[name].lower()
    for extension in ("obj", "dae", "gltf", "glb"):
        assert extension in body, (name, extension)


def test_the_geometry_append_path_explains_the_refusal_rather_than_hiding_it() -> None:
    text = source_part_append_mesh_file_dialog_text()

    assert text["fbx_title"] == "FBX Import Deferred"
    message = text["fbx_message"]
    assert "not supported" in message
    # A refusal has to name the way forward, not only the refusal.
    for alternative in ("OBJ", "DAE", "glTF/GLB", "PAC", "PAM", "PAMLOD"):
        assert alternative in message, alternative


def test_the_audit_accepts_fbx_because_it_reads_metadata_not_geometry() -> None:
    # The audit is deliberately wider than the import filters: it inspects an
    # FBX's materials so a reader can plan a conversion.
    assert ".fbx" in EXTERNAL_MODEL_AUDIT_EXTENSIONS
    for extension in (".obj", ".dae", ".gltf", ".glb", ".zip"):
        assert extension in EXTERNAL_MODEL_AUDIT_EXTENSIONS


def test_the_audit_says_geometry_import_still_needs_another_format() -> None:
    from cdmw.core import external_model_audit

    source = external_model_audit.__file__
    body = open(source, encoding="utf-8").read()
    # Both the ASCII and the binary inventory paths carry the caveat, so an FBX
    # that audits cleanly cannot be mistaken for one that will import.
    assert body.count("geometry import still requires OBJ, DAE, GLB, or glTF.") == 2
    assert "FBX material audit is metadata-only" in body


def test_fbx_export_is_supported_with_and_without_a_skeleton() -> None:
    from cdmw.modding.mesh_exporter import export_fbx, export_fbx_with_skeleton

    assert callable(export_fbx)
    assert callable(export_fbx_with_skeleton)


def test_the_readme_advertises_fbx_for_export_and_not_for_import() -> None:
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    mesh_editor_rows = [line for line in readme.splitlines() if "**Mesh Editor**" in line]
    assert mesh_editor_rows, "README no longer describes the Mesh Editor"
    row = mesh_editor_rows[0]
    assert "OBJ/FBX export" in row
    # The import list is the one that must not gain FBX.
    assert "OBJ/DAE/glTF/GLB import" in row
    import_clause = row.split("import", 1)[0].rsplit("export,", 1)[-1]
    assert "FBX" not in import_clause
