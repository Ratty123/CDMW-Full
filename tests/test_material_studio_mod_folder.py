"""Reopening a loose mod folder: its material sidecar and textures replace the game's."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.models import ArchiveEntry
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.mesh_archive_results import ADDED_RESULT_NOTE, EDITED_RESULT_NOTE
from cdmw.services.mesh_saved_work_service import (
    MAX_FOLDER_MODELS,
    folder_model_choices,
    KIND_BUILT_MOD,
    add_built_mod_folder,
    draft_baseline_entries,
    ensure_session_draft_workspace,
    folder_model_paths,
    list_saved_work,
    material_sidecar_path_for_mesh,
    mesh_path_for_material_sidecar,
    plan_session_draft,
    prepare_saved_work_launch,
)
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.mesh_editor.saved_work_launch import overlay_dependency_context

_MESH = "character/model/1_pc/2_phw/armor/20_mask/cd_phw_01_mask_0271.pac"
_SIDECAR = "character/modelproperty/1_pc/2_phw/armor/20_mask/cd_phw_01_mask_0271.pac_xml"
_BASE = "character/texture/cd_phm_00_mask_0248.dds"
_HEIGHT = "character/texture/cd_phm_00_mask_0248_disp.dds"
_PRIVATE = "character/texture/my_veil_base.dds"


def _sidecar(base: str, height: str, pitch: str) -> bytes:
    return (
        '<ModelProperty Index="0"><SkinnedMeshMaterialWrapper _subMeshName="cd_phm_00_mask_0248">'
        '<Material Name="_resourceMaterial" _materialName="SkinnedMeshTransparency"><Vector Name="_parameters">'
        f'<MaterialParameterTexture StringItemID="_baseColorTexture" ItemID="7" _name="_baseColorTexture" Index="0">'
        f'<ResourceReferencePath_ITexture Name="_value" _path="{base}"/></MaterialParameterTexture>'
        f'<MaterialParameterTexture StringItemID="_heightTexture" ItemID="4" _name="_heightTexture" Index="1">'
        f'<ResourceReferencePath_ITexture Name="_value" _path="{height}"/></MaterialParameterTexture>'
        f'<MaterialParameterFloat StringItemID="_netPitch" ItemID="2027176113209342" _name="_netPitch" '
        f'_value="{pitch}" Index="2"/>'
        '</Vector></Material></SkinnedMeshMaterialWrapper></ModelProperty>'
    ).encode("utf-8")


def _game_entry(root: Path, path: str, data: bytes, offset: int) -> ArchiveEntry:
    """A game file as Archive Browser prepares it: a location plus a verified local copy."""

    copies = root.parent / "prepared"
    copies.mkdir(exist_ok=True)
    copy = copies / (hashlib.sha256(path.encode()).hexdigest()[:10] + Path(path).name)
    copy.write_bytes(data)
    return ArchiveEntry(path, root / "0.pamt", root / "0.paz", offset, len(data), len(data), 0, 0,
                        prepared_path=copy, prepared_sha256=hashlib.sha256(data).hexdigest(),
                        prepared_size=len(data))


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "game" / "0009"
    root.mkdir(parents=True)
    files = {
        _MESH: b"game mesh bytes",
        _SIDECAR: _sidecar(_BASE, _HEIGHT, "0.300000"),
        _BASE: b"DDS game base colour",
        _HEIGHT: b"DDS game height",
    }
    entries = {path: _game_entry(root, path, data, 100 * index) for index, (path, data) in enumerate(files.items(), 1)}
    paths = {path.casefold(): [entry] for path, entry in entries.items()}
    names = {entry.basename.casefold(): [entry] for entry in entries.values()}
    context = ArchiveWorkflowDependencyContext(entries[_MESH], tuple(entries.values()), paths, names, remote=True)
    return type("Game", (), {"files": files, "entries": entries, "context": context,
                             "drafts": tmp_path / "workspace" / "drafts"})


def _write(root: Path, relative: str, data: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _launch(game, row):
    return prepare_saved_work_launch(
        game.drafts, row, game.entries[_MESH], edited_note=EDITED_RESULT_NOTE, added_note=ADDED_RESULT_NOTE,
        game_entry_for_path=game.context.entry_for_path,
    )


def _only_row(game):
    rows = [row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD]
    assert len(rows) == 1
    return rows[0]


def test_material_sidecar_and_mesh_paths_mirror_each_other():
    assert material_sidecar_path_for_mesh(_MESH) == _SIDECAR
    assert mesh_path_for_material_sidecar(_SIDECAR) == _MESH
    assert mesh_path_for_material_sidecar("character/texture/a.dds") == ""
    assert mesh_path_for_material_sidecar("character/model/a.pac_xml") == ""


@pytest.mark.parametrize("prefix", ["", "0009/", "files/0009/", "Lace Veil Blue/"])
def test_material_only_folder_lists_the_model_its_sidecar_belongs_to(tmp_path, prefix):
    mod = tmp_path / "mod"
    _write(mod, prefix + _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.5"))
    _write(mod, "manifest.json", b"{}")
    assert folder_model_paths(mod) == [_MESH]


def test_folder_with_several_models_is_listed_once_per_model(game, tmp_path):
    mod = tmp_path / "Angel"
    other = _SIDECAR.replace("mask_0271", "mask_0300")
    _write(mod, "files/0009/" + _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.5"))
    _write(mod, "files/0009/" + other, _sidecar(_BASE, _HEIGHT, "0.5"))
    add_built_mod_folder(game.drafts, mod)
    rows = [row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD]
    assert sorted(row.source_archive_path for row in rows) == sorted([_MESH, _MESH.replace("mask_0271", "mask_0300")])
    assert {row.display_name for row in rows} == {"Angel - cd_phw_01_mask_0271", "Angel - cd_phw_01_mask_0300"}
    with pytest.raises(ValueError, match="already in the list"):
        add_built_mod_folder(game.drafts, mod)


def test_parent_of_several_variants_is_refused(game, tmp_path):
    mod = tmp_path / "Lace Veil"
    _write(mod, "Blue/" + _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.5"))
    _write(mod, "Red/" + _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.6"))
    with pytest.raises(ValueError, match="more than one copy"):
        add_built_mod_folder(game.drafts, mod)
    assert not list_saved_work(game.drafts)


def test_wrapped_mesh_path_is_read_as_its_game_path(tmp_path):
    mod = tmp_path / "mod"
    _write(mod, "My Mod/files/0009/" + _MESH, b"mesh")
    assert folder_model_paths(mod) == [_MESH]


def test_folder_without_models_is_refused(game, tmp_path):
    mod = tmp_path / "textures-only"
    _write(mod, "character/texture/a.dds", b"DDS")
    with pytest.raises(ValueError, match="no mesh files"):
        add_built_mod_folder(game.drafts, mod)


def test_material_only_mod_continues_over_the_game_mesh_with_its_own_files(game, tmp_path):
    mod = tmp_path / "Lace Veil"
    sidecar = _sidecar(_PRIVATE, _HEIGHT, "0.627000")
    _write(mod, "files/0009/" + _SIDECAR, sidecar)
    _write(mod, "files/0009/" + _PRIVATE, b"DDS my own base colour")
    _write(mod, "files/0009/" + _HEIGHT, b"DDS repainted height")
    # Present but identical to the game: left to the game.
    _write(mod, "files/0009/" + _BASE, game.files[_BASE])
    record = add_built_mod_folder(game.drafts, mod)
    assert record["source_archive_path"] == _MESH

    launch = _launch(game, _only_row(game))

    assert launch.selected_entry is game.entries[_MESH]
    by_path = {entry.path: entry for entry in launch.replacements}
    assert set(by_path) == {_SIDECAR, _PRIVATE, _HEIGHT}
    assert read_archive_entry_data(by_path[_SIDECAR])[0] == sidecar
    assert read_archive_entry_data(by_path[_HEIGHT])[0] == b"DDS repainted height"
    assert read_archive_entry_data(by_path[_PRIVATE])[0] == b"DDS my own base colour"
    # Replacements keep the game file's location; a new file is added beside the mesh.
    assert by_path[_SIDECAR].identity == game.entries[_SIDECAR].identity
    assert by_path[_HEIGHT].identity == game.entries[_HEIGHT].identity
    assert (by_path[_SIDECAR].prepared_note, by_path[_HEIGHT].prepared_note) == (EDITED_RESULT_NOTE,) * 2
    assert by_path[_PRIVATE].prepared_note == ADDED_RESULT_NOTE
    assert by_path[_PRIVATE].pamt_path == game.entries[_MESH].pamt_path and by_path[_PRIVATE].offset == 0
    # The copies are the session's own, so later edits to the mod folder cannot break it.
    assert all(mod not in Path(entry.prepared_path).parents for entry in launch.replacements)
    assert launch.draft_request.edit_pass == 2
    assert launch.draft_request.baseline_entries == launch.replacements

    overlaid = overlay_dependency_context(game.context, launch.selected_entry, launch.replacements)
    assert read_archive_entry_data(overlaid.entry_for_path(_SIDECAR))[0] == sidecar
    assert read_archive_entry_data(overlaid.entry_for_path(_PRIVATE))[0] == b"DDS my own base colour"
    assert overlaid.entry_for_path(_BASE) is game.entries[_BASE]
    assert overlaid.entry_for_path(_MESH) is game.entries[_MESH]


def test_draft_of_a_material_only_mod_resumes_with_the_game_mesh_unmarked(game, tmp_path):
    mod = tmp_path / "Lace Veil"
    _write(mod, _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.627000"))
    add_built_mod_folder(game.drafts, mod)
    launch = _launch(game, _only_row(game))
    mesh = game.files[_MESH]
    plan = plan_session_draft(game.drafts, launch.selected_entry,
                              source_sha256=hashlib.sha256(mesh).hexdigest(), request=launch.draft_request)
    manifest = ensure_session_draft_workspace(plan, mesh)

    selected, companions = draft_baseline_entries(manifest, game.entries[_MESH], edited_note=EDITED_RESULT_NOTE)

    # Build Mod must not ship the game's own mesh as if it were edited.
    assert selected.prepared_note == ""
    assert [(entry.path, entry.prepared_note) for entry in companions] == [(_SIDECAR, EDITED_RESULT_NOTE)]


def test_mod_with_a_mesh_carries_its_material_files_too(game, tmp_path):
    mod = tmp_path / "Reshaped"
    _write(mod, "0009/" + _MESH, b"edited mesh bytes")
    _write(mod, "0009/" + _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.450000"))
    add_built_mod_folder(game.drafts, mod)

    launch = _launch(game, _only_row(game))

    assert read_archive_entry_data(launch.selected_entry)[0] == b"edited mesh bytes"
    assert launch.selected_entry.prepared_note == EDITED_RESULT_NOTE
    assert [entry.path for entry in launch.replacements] == [_MESH, _SIDECAR]
    assert [entry.path for entry in launch.draft_request.baseline_entries] == [_SIDECAR]


def test_extracted_folder_matching_the_game_opens_the_game_model(game, tmp_path):
    mod = tmp_path / "Extracted"
    _write(mod, _SIDECAR, game.files[_SIDECAR])
    _write(mod, _BASE, game.files[_BASE])
    add_built_mod_folder(game.drafts, mod)

    launch = _launch(game, _only_row(game))

    assert launch.selected_entry is game.entries[_MESH]
    assert launch.replacements == () and launch.draft_request.edit_pass == 1


def test_mod_folder_that_lost_its_files_cannot_be_continued(game, tmp_path):
    mod = tmp_path / "Emptied"
    _write(mod, _SIDECAR, _sidecar(_BASE, _HEIGHT, "0.5"))
    add_built_mod_folder(game.drafts, mod)
    (mod / _SIDECAR).unlink()
    with pytest.raises(ValueError, match="no longer contains the edited mesh"):
        _launch(game, _only_row(game))


def _many_models(mod: Path, count: int) -> list[str]:
    paths = []
    for index in range(count):
        mesh = f"character/model/1_pc/2_phw/armor/9_upperbody/cd_phw_00_ub_00_{index:04d}.pac"
        _write(mod, "0009/" + material_sidecar_path_for_mesh(mesh), _sidecar(_BASE, _HEIGHT, "0.5"))
        paths.append(mesh)
    return paths


def test_a_mod_sized_folder_is_listed_whole_without_asking(tmp_path):
    mod = tmp_path / "mod"
    _many_models(mod, MAX_FOLDER_MODELS)
    assert folder_model_choices(mod) == []


def test_an_extracted_folder_offers_every_model_and_lists_only_the_chosen(game, tmp_path):
    mod = tmp_path / "extracted"
    paths = _many_models(mod, MAX_FOLDER_MODELS + 40)
    assert folder_model_choices(mod) == paths

    record = add_built_mod_folder(game.drafts, mod, model_paths=[paths[90].upper(), paths[3]])

    rows = [row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD]
    assert {row.source_archive_path for row in rows} == {paths[3], paths[90]}
    assert record["source_archive_path"] in {paths[3], paths[90]}
    # Each row is named after its model, and adding the same one again is refused.
    assert {row.display_name for row in rows} == {f"extracted - {Path(path).stem}" for path in (paths[3], paths[90])}
    with pytest.raises(ValueError, match="already in the list"):
        add_built_mod_folder(game.drafts, mod, model_paths=[paths[3]])
    add_built_mod_folder(game.drafts, mod, model_paths=[paths[3], paths[4]])
    assert len([row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD]) == 3


@pytest.mark.parametrize("chosen", [[], ["character/model/not/here.pac"], None])
def test_choosing_models_outside_the_folder_or_too_many_is_refused(game, tmp_path, chosen):
    mod = tmp_path / "extracted"
    paths = _many_models(mod, MAX_FOLDER_MODELS + 2)
    with pytest.raises(ValueError, match="between 1 and 64"):
        add_built_mod_folder(game.drafts, mod, model_paths=paths if chosen is None else chosen)


def test_one_folder_walk_serves_every_lookup_of_a_launch(game, tmp_path, monkeypatch):
    import cdmw.services.mesh_saved_work_service as service

    mod = tmp_path / "Lace Veil"
    _write(mod, "files/0009/" + _SIDECAR, _sidecar(_PRIVATE, _HEIGHT, "0.627000"))
    _write(mod, "files/0009/" + _PRIVATE, b"DDS my own base colour")
    _write(mod, "files/0009/" + _HEIGHT, b"DDS repainted height")
    add_built_mod_folder(game.drafts, mod)
    row = _only_row(game)
    walks = []
    original = service._loose_files
    monkeypatch.setattr(service, "_loose_files",
                        lambda folder, suffixes=(), limit=65536: walks.append(suffixes) or original(folder, suffixes, limit))

    launch = _launch(game, row)

    assert {entry.path for entry in launch.replacements} == {_SIDECAR, _PRIVATE, _HEIGHT}
    # One walk per file type: the sidecar, the textures, and the absent mesh.
    assert sorted(walks) == [(".dds",), (".pac",), (".pac_xml",)]


def test_picker_filters_keeps_hidden_choices_and_caps_the_selection(tmp_path):
    from PySide6.QtWidgets import QApplication

    from cdmw.ui.mesh_editor.folder_model_picker import VISIBLE_MODEL_ROWS, FolderModelPicker

    app = QApplication.instance() or QApplication([])
    paths = [f"character/model/1_pc/2_phw/armor/{'20_mask' if index % 2 else '9_upperbody'}/cd_phw_{index:04d}.pac"
             for index in range(VISIBLE_MODEL_ROWS + 100)]
    picker = FolderModelPicker(paths)
    try:
        assert picker.list.count() == VISIBLE_MODEL_ROWS
        assert not picker.add_button.isEnabled()

        picker.filter_edit.setText("MASK 0401")
        assert [picker.list.item(row).toolTip() for row in range(picker.list.count())] == [paths[401]]
        picker.list.item(0).setSelected(True)
        assert picker.add_button.isEnabled()

        # A choice made under one filter survives the next.
        picker.filter_edit.setText("upperbody 0002")
        assert picker.list.count() == 1 and not picker.list.item(0).isSelected()
        picker.list.item(0).setSelected(True)
        assert picker.selected_paths() == [paths[2], paths[401]]
        picker.filter_edit.setText("0401")
        assert picker.list.item(0).isSelected()
        picker.list.item(0).setSelected(False)
        assert picker.selected_paths() == [paths[2]]

        picker.filter_edit.setText("")
        picker.list.selectAll()
        assert len(picker.selected_paths()) == VISIBLE_MODEL_ROWS
        assert not picker.add_button.isEnabled()
    finally:
        picker.deleteLater()
        app.processEvents()
