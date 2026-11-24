"""CDMW and the Mesh Editor helper bound the session folder with the same numbers.

Each side checks the folder on its own; when the numbers drift, the editor refuses a
session CDMW thought was fine and closes as it starts (2026-11-24: slider profiles over
8 MiB). The helper's constants are read from its source.
"""

from __future__ import annotations

import re
from pathlib import Path

from cdmw.services import mesh_rust_authoring as authoring

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "rust_mesh_lab" / "apps" / "cdmw_mesh_lab" / "src" / \
    "cdmw_session.rs"


def _rust_constant(name: str) -> int:
    match = re.search(rf"const {name}: \w+ = ([0-9_ *]+);", SOURCE.read_text(encoding="utf-8"))
    assert match, name
    value = 1
    for factor in match.group(1).replace("_", "").split("*"):
        value *= int(factor.strip())
    return value


def test_the_slider_profile_bounds_are_the_same_on_both_sides() -> None:
    assert authoring.PROFILE_MAX_FILE_BYTES == _rust_constant("MAX_PROFILE_FILE_BYTES")
    assert authoring.PROFILE_MAX_TOTAL_BYTES == _rust_constant("MAX_PROFILE_TOTAL_BYTES")
    assert authoring.PROFILE_MAX_ENTRIES == _rust_constant("MAX_PROFILE_ENTRIES")
    assert authoring._PROFILE_MAX_DEPTH == _rust_constant("MAX_PROFILE_DEPTH")


def test_the_large_library_cdmw_supports_fits_the_editor() -> None:
    # tests/test_mesh_morph_large_profiles.py: nine 9 MiB profiles, 81 MiB in all.
    assert 9 * 1024 * 1024 < authoring.PROFILE_MAX_FILE_BYTES
    assert 81 * 1024 * 1024 < authoring.PROFILE_MAX_TOTAL_BYTES


def test_a_library_the_editor_would_refuse_is_named_before_the_editor_starts(tmp_path, monkeypatch) -> None:
    import pytest

    profiles = tmp_path / "settings" / "mesh_slider_profiles"
    profiles.mkdir(parents=True)
    (profiles / "big.json").write_text('{"padding": "' + "x" * 64 + '"}', encoding="utf-8")
    monkeypatch.setattr(authoring, "PROFILE_MAX_FILE_BYTES", 16)
    session = tmp_path / "session"
    session.mkdir()
    settings = authoring._ShadowSettings(tmp_path / "settings" / "settings.ini")
    with pytest.raises(authoring.RustMeshValidationError, match="slider profile library"):
        authoring._copy_shadow_morph_profiles(settings, session)
    assert not (session / "mesh_slider_profiles").exists()


def test_a_material_state_is_bounded_as_the_editor_bounds_it() -> None:
    assert authoring._RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES == _rust_constant("MAX_MANIFEST_BYTES")


def test_a_set_material_state_over_the_limit_is_refused_before_it_is_written(tmp_path, monkeypatch) -> None:
    import pytest
    from types import SimpleNamespace

    from cdmw.domain.mesh.emission import EmissionChoice
    from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE
    from cdmw.services.mesh_material_colours import stage_item_set_colour_preview

    part = SimpleNamespace(name="Coat", material="coat", vertices=[], faces=[])
    setattr(part, ASSET_ATTRIBUTE, "upper")
    mesh = SimpleNamespace(submeshes=[part], lod_levels=[[part]])
    base_key = "a" * 32
    host = SimpleNamespace(root=tmp_path, root_identity=authoring._session_root_identity(tmp_path),
                           archive_refit_material_cache={base_key: {"key": base_key, "textures": [],
                                                                    "material_presentations": [],
                                                                    "preview_core_material_graph": None}},
                           archive_refit_material_references={})
    context = SimpleNamespace(material_colours=(), emissions=(("upper", "coat", EmissionChoice((1.0, 0.5, 0.25), 6.0)),))
    monkeypatch.setattr(authoring, "_RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES", 8)
    with pytest.raises(ValueError, match="16 MiB"):
        stage_item_set_colour_preview(host, mesh, context, base_key)
    assert not list(tmp_path.glob("material-state-*.json"))


def test_an_fbx_import_converts_beside_the_session_and_the_next_state_still_writes(tmp_path) -> None:
    """An ``fbx-import`` folder inside the session failed CDMW's next state write, which
    closed the editor after every FBX Import Replacement (2026-11-24)."""
    from cdmw.services.mesh_rust_replacement import fbx_work_dir
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests

    authoritative, session = RustMeshAuthoringTests()._create(tmp_path / "session-0123")
    try:
        work = fbx_work_dir(session.root)
        assert work.parent == session.root.parent and work.name.startswith(session.root.name)
        work.mkdir()
        (work / "model.glb").write_bytes(b"glTF")
        assert session.state_payload()  # raised "Unexpected Mesh session entry: fbx-import" before
    finally:
        session.cancel()
        authoritative.close_edit_session(session.authoritative_session_id, force_without_saving=True)
