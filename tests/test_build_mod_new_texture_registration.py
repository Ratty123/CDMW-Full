"""Build Mod's new replacement textures reach the game's texture registry (P6 question 11).

Build Mod writes a replacement's imported textures as new files (`<stem>_cdmw_<hash>.dds`)
and ships no `meta/0.pathc`: DMM registers a mod's new textures itself, and CDMW's
virtual loader registers the DDS files of a selected mod folder when it composes a
profile (`virtual_loader_composition.compose_packages`). These tests build a mod through
the real Build Mod worker on owned fixtures and check both halves.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from cdmw.services.mesh_replacement_import import (
    commit_replacement,
    compose_import,
    initial_replacement_state,
    prepare_import,
)
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
from tests.test_mesh_editor_replacement import editor  # noqa: F401  (fixture)
from tests.test_mesh_editor_replacement_materials import _qt_application, material_fixture  # noqa: F401


def _build_loose_mod(service, session_id, tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    mesh, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
    commit_replacement(service, snapshot, mesh, state, label="Import")
    new_textures = tuple(file.path for file in files if file.path.endswith(".dds")
                         and file.path.casefold() not in context.entries_by_normalized_path)
    assert new_textures, "the imported material should bring at least one new texture"

    output = tmp_path / "built-mod"
    worker = MeshDirectOutputWorker(1, service, session_id, target, kind="loose_mod", output_path=output)
    errors, completed = [], []
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.completed.connect(lambda _id, result: completed.append(result))
    worker.run()
    assert not errors and completed, errors
    return output, new_textures


def test_build_mod_writes_new_textures_and_no_registry_of_its_own(editor, tmp_path):  # noqa: F811
    from cdmw.core.pathc_format import validate_dds_payload

    service, session_id = editor
    mod, new_textures = _build_loose_mod(service, session_id, tmp_path)
    for path in new_textures:
        assert "_cdmw_" in Path(path).name, path
        written = mod / path
        assert written.is_file(), path
        validate_dds_payload(written.read_bytes())  # a complete DDS the registry can describe
    # The registry is the mod manager's: DMM reports a mod's own meta/0.pathc as not applied.
    assert not (mod / "meta" / "0.pathc").exists()


def test_the_virtual_loader_registers_build_mods_new_textures(editor, tmp_path):  # noqa: F811
    from cdmw.core.pathc_format import parse_pathc
    from cdmw.services.virtual_loader_composition import compose_packages
    from tests.test_independent_items import setup_game

    service, session_id = editor
    (tmp_path / "build").mkdir()
    mod, new_textures = _build_loose_mod(service, session_id, tmp_path / "build")
    setup_game(tmp_path / "loader")
    root = tmp_path / "loader" / "game"
    before = parse_pathc((root / "meta" / "0.pathc").read_bytes())
    assert all(before.find(path) is None for path in new_textures)

    _resolved, files, _flags, pathc = compose_packages((), (mod,), root)
    assert pathc is not None
    registry = parse_pathc(pathc)
    missing = [path for path in new_textures if registry.find(path) is None]
    assert not missing, f"new textures the game could not find: {missing}"
    assert all(path in files for path in new_textures)

    # The step the Mods page runs accepts the folder as Build Mod wrote it.
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services.virtual_loader_composition import prepare_profile

    prepare_profile(VirtualProfile((), (mod,)), root)
