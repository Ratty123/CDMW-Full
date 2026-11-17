"""Mesh Editor live texture edits written into Build Mod (step 8, stage 4)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_live_texture_output import (
    ENCODE_DIRNAME,
    LiveTextureEdit,
    encode_live_texture_outputs,
    live_texture_metadata,
    plan_live_texture_outputs,
)
from cdmw.ui.mesh_editor.live_texture_updates import rgba8_dds_bytes

GAME_PATH = "character/texture/cd_phm_00_ub_00_0374_d.dds"


def _entry(path: str = GAME_PATH) -> ArchiveEntry:
    return ArchiveEntry(path=path, pamt_path=Path("0009/0.pamt"), paz_file=Path("0009/0.paz"), offset=0,
                        comp_size=1, orig_size=1, flags=0, paz_index=0)


def _original(tmp_path: Path, width: int = 4, height: int = 2) -> Path:
    path = tmp_path / "session" / "texture-0-ab.dds"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(rgba8_dds_bytes(width, height, bytes(width * height * 4)))
    return path


def _edit(tmp_path: Path, **extra) -> LiveTextureEdit:
    values = dict(source_sha256="ab" * 32, game_path=GAME_PATH, original_path=str(_original(tmp_path)),
                  rgba=np.full((2, 4, 4), 200, dtype=np.uint8), users=("Upper body", "Belt"))
    values.update(extra)
    return LiveTextureEdit(**values)


def test_the_plan_names_the_game_file_and_the_original_format(tmp_path: Path) -> None:
    plan = plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)})
    assert plan.refusals == ()
    (output,) = plan.outputs
    assert output.entry.path == GAME_PATH
    assert (output.original.dds_format, output.original.width, output.original.height) == ("R8G8B8A8_UNORM", 4, 2)
    assert plan.plan_lines == (GAME_PATH + ": writes, R8G8B8A8_UNORM, 4 x 2, 1 mips (shared by Upper body, Belt)",)
    assert live_texture_metadata(plan.outputs)[0]["parts"] == ["Upper body", "Belt"]


def test_textures_that_cannot_be_written_say_why(tmp_path: Path) -> None:
    plan = plan_live_texture_outputs(
        [
            _edit(tmp_path, game_path="texture-label-only"),
            _edit(tmp_path, game_path="character/texture/missing.dds"),
            _edit(tmp_path, rgba=np.zeros((8, 8, 4), dtype=np.uint8)),
        ],
        {GAME_PATH: (_entry(),)},
    )
    assert plan.outputs == ()
    assert "which game file" in plan.refusals[0]
    assert "not found in the archives" in plan.refusals[1]
    assert "original's size" in plan.refusals[2]


def test_encoding_writes_beside_the_session_and_leaves_nothing_behind(tmp_path: Path) -> None:
    plan = plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)})
    calls = []

    def encoder(rgba, original, target, *, temp_root):
        calls.append((Path(target).parent, Path(temp_root)))
        Path(target).write_bytes(b"DDS encoded")

    requests = encode_live_texture_outputs(plan.outputs, tmp_path / "session", encoder=encoder)
    assert [(request.entry.path, request.payload_data) for request in requests] == [(GAME_PATH, b"DDS encoded")]
    assert calls == [(tmp_path / "session" / ENCODE_DIRNAME,) * 2]
    assert not (tmp_path / "session" / ENCODE_DIRNAME).exists()


def test_only_build_mod_writes_edited_textures() -> None:
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    entry = SimpleNamespace(path="character/model/a.pac")
    with pytest.raises(ValueError, match="only by Build Mod"):
        MeshDirectOutputWorker(1, None, "s", entry, kind="archive_result", texture_outputs=(object(),),
                               texture_work_root=Path("x"))
    with pytest.raises(ValueError, match="only by Build Mod"):
        MeshDirectOutputWorker(1, None, "s", entry, kind="loose_mod", texture_outputs=(object(),))


def test_an_edit_undone_to_the_original_is_not_written(tmp_path: Path) -> None:
    from PySide6.QtCore import QThreadPool
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from cdmw.ui.mesh_editor.live_texture_updates import LiveTextureUpdates

    QApplication.instance() or QApplication([])
    live = LiveTextureUpdates(lambda: None, lambda _fields: False, pool=QThreadPool())
    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    live.push("AB" * 32, image)
    assert list(live.edited_textures()) == ["ab" * 32]
    live.push("ab" * 32, image, changed=False)
    assert live.edited_textures() == {}


def test_the_real_encoder_writes_the_original_format_size_and_mips(tmp_path: Path) -> None:
    from cdmw.core import texture_native
    from cdmw.core.texture_pipeline.inspection import parse_dds

    if texture_native.find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built here")
    plan = plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)})
    (request,) = encode_live_texture_outputs(plan.outputs, tmp_path / "session")
    written = tmp_path / "written.dds"
    written.write_bytes(request.payload_data)
    info = parse_dds(written)
    assert (info.dds_format, info.width, info.height, info.mip_count) == ("R8G8B8A8_UNORM", 4, 2, 1)
    assert not any((tmp_path / "session").glob(ENCODE_DIRNAME + "/*"))


def test_a_stored_source_plans_without_the_session_folder(tmp_path: Path) -> None:
    from cdmw.domain.textures.original_output import check_texture_editable

    original = check_texture_editable(_original(tmp_path))
    (tmp_path / "session" / "texture-0-ab.dds").unlink()  # Finish deleted the session folder
    edit = LiveTextureEdit(source_sha256="ab" * 32, game_path=GAME_PATH, rgba=np.zeros((2, 4, 4), dtype=np.uint8),
                           original=original)
    plan = plan_live_texture_outputs([edit], {GAME_PATH: (_entry(),)})
    assert plan.refusals == () and plan.outputs[0].original == original


def test_a_texture_only_build_writes_just_the_textures(tmp_path: Path, monkeypatch) -> None:
    """No mesh change: nothing to validate, and the mesh is not written (step 8)."""

    import json

    import cdmw.services.mesh_live_texture_output as output
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    plan = plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)})
    real = output.encode_live_texture_outputs
    monkeypatch.setattr(output, "encode_live_texture_outputs", lambda outputs, root, *, stop_event=None: real(
        outputs, root, stop_event=stop_event,
        encoder=lambda rgba, original, target, *, temp_root: Path(target).write_bytes(b"DDS edited")))
    with pytest.raises(ValueError, match="needs edited textures"):
        MeshDirectOutputWorker(1, None, "s", _entry("character/model/a.pac"), kind="loose_mod", textures_only=True)
    worker = MeshDirectOutputWorker(1, None, "s", _entry("character/model/a.pac"), kind="loose_mod",
                                    output_path=tmp_path / "mods" / "Edited", texture_outputs=plan.outputs,
                                    texture_work_root=tmp_path / "work", textures_only=True)
    done = []
    worker.completed.connect(lambda _id, result: done.append(result))
    worker.error.connect(lambda _id, message: done.append(message))
    worker.run()
    (result,) = done
    assert not isinstance(result, str), result
    files = sorted(p.relative_to(result.output_path).as_posix() for p in result.output_path.rglob("*") if p.is_file())
    assert any(name.endswith("cd_phm_00_ub_00_0374_d.dds") for name in files), files
    assert not any(name.endswith(".pac") for name in files), files
    dds = next(p for p in result.output_path.rglob("*.dds"))
    assert dds.read_bytes() == b"DDS edited"
    session = next(result.output_path.rglob("mesh-editor-session.json"), None)
    if session is not None:
        assert json.loads(session.read_text(encoding="utf-8"))["contents"] == ["edited_textures"]


def test_a_texture_no_part_in_the_build_uses_is_left_out_and_says_so(tmp_path: Path) -> None:
    # Item 5: its parts were deleted, so writing it would change the game file for nothing.
    plan = plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)},
                                     parts_in_build=("Lower body",))
    assert plan.outputs == () and plan.refusals == ()
    assert plan.plan_lines == (GAME_PATH + ": left out, no part in this mod uses it (Upper body, Belt)",)


def test_one_remaining_part_keeps_the_texture_written(tmp_path: Path) -> None:
    plan = plan_live_texture_outputs([_edit(tmp_path, users=("Upper body (cd_phm_00_ub_00_0374.pac)",))],
                                     {GAME_PATH: (_entry(),)},
                                     parts_in_build=("upper body", "Belt"))
    assert len(plan.outputs) == 1 and plan.left_out == ()
    # Not knowing the build's parts writes every edited texture, as before.
    assert len(plan_live_texture_outputs([_edit(tmp_path)], {GAME_PATH: (_entry(),)}).outputs) == 1


def test_the_build_s_parts_are_its_working_mesh_s_parts() -> None:
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="CD_PHM_00_UB_00_0374"), SimpleNamespace(name="Belt")])
    service = SimpleNamespace(working_mesh=lambda session_id: mesh if session_id == "s1" else None)
    host = SimpleNamespace(standalone_controller=SimpleNamespace(mesh_service=service, active_session_id="s1"))
    assert MeshEditorRustProcessMixin._parts_in_build(host) == ("CD_PHM_00_UB_00_0374", "Belt")
    # Unknown or unnamed parts: nothing is left out.
    assert MeshEditorRustProcessMixin._parts_in_build(SimpleNamespace(standalone_controller=None)) is None
    mesh.submeshes.append(SimpleNamespace(name=""))
    assert MeshEditorRustProcessMixin._parts_in_build(host) is None


def _set_host(excluded: frozenset[str] = frozenset()):
    """A Mesh Editor tab with a set of two files open: a.pac (Upper body, Belt), b.pac (Belt)."""

    import threading

    from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE, PART_ATTRIBUTE, MeshAssetContext

    def part(name: str, asset: str, index: int):
        return SimpleNamespace(name=name, **{ASSET_ATTRIBUTE: asset, PART_ATTRIBUTE: f"{asset}:{index}"})

    assets = tuple(SimpleNamespace(asset_id=key, entry=_entry(f"character/model/{key}.pac"), part_indices=indices)
                   for key, indices in (("a", (0, 1)), ("b", (2,))))
    context = MeshAssetContext(assets=assets, workflow="item_set", excluded_part_ids=excluded)
    mesh = SimpleNamespace(submeshes=[part("Upper body", "a", 0), part("Belt", "a", 1), part("Belt", "b", 0)])
    session = SimpleNamespace(export_lock=threading.RLock(), archive_refit_context=context, replacement_state=None)
    service = SimpleNamespace(working_mesh=lambda session_id: mesh, _session=lambda session_id: session)
    return SimpleNamespace(standalone_controller=SimpleNamespace(mesh_service=service, active_session_id="s1"))


def test_a_set_part_whose_include_is_off_is_not_in_the_build() -> None:
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    assert MeshEditorRustProcessMixin._parts_in_build(_set_host()) == (
        "Upper body (a.pac)", "Belt (a.pac)", "Belt (b.pac)")
    # Include off for b.pac's Belt (or the whole of b.pac): its part stays in the
    # working mesh but the mod does not hold it.
    assert MeshEditorRustProcessMixin._parts_in_build(_set_host(frozenset({"b:0"}))) == (
        "Upper body (a.pac)", "Belt (a.pac)")


def test_a_texture_only_an_excluded_set_part_uses_is_left_out_not_kept_by_a_namesake(tmp_path: Path) -> None:
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    kept = MeshEditorRustProcessMixin._parts_in_build(_set_host(frozenset({"b:0"})))
    # b.pac's Belt is left out; a.pac also has a part called Belt, which must not keep it.
    plan = plan_live_texture_outputs([_edit(tmp_path, users=("Belt (b.pac)",))], {GAME_PATH: (_entry(),)},
                                     parts_in_build=kept)
    assert plan.outputs == () and plan.refusals == ()
    assert plan.plan_lines == (GAME_PATH + ": left out, no part in this mod uses it (Belt (b.pac))",)
    shared = plan_live_texture_outputs([_edit(tmp_path, users=("Belt (a.pac)", "Belt (b.pac)"))],
                                       {GAME_PATH: (_entry(),)}, parts_in_build=kept)
    assert len(shared.outputs) == 1 and shared.left_out == ()


def test_a_single_file_part_whose_include_is_off_is_not_in_the_build() -> None:
    import threading

    from cdmw.domain.mesh.replacement import PART_ID_ATTRIBUTE, MeshReplacementState, ReplacementPart
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="Upper body", **{PART_ID_ATTRIBUTE: "p0"}),
                                      SimpleNamespace(name="Belt", **{PART_ID_ATTRIBUTE: "p1"})])
    state = MeshReplacementState(target_path="character/model/a.pac", target_sha256="0" * 64,
                                 parts=(ReplacementPart("p0", 0), ReplacementPart("p1", 1, included=False)))
    session = SimpleNamespace(export_lock=threading.RLock(), archive_refit_context=None, replacement_state=state)
    service = SimpleNamespace(working_mesh=lambda session_id: mesh, _session=lambda session_id: session)
    host = SimpleNamespace(standalone_controller=SimpleNamespace(mesh_service=service, active_session_id="s1"))
    assert MeshEditorRustProcessMixin._parts_in_build(host) == ("Upper body",)
    # Part identities that no longer match the replacement: not known, nothing left out.
    mesh.submeshes.pop()
    assert MeshEditorRustProcessMixin._parts_in_build(host) is None


def test_build_mod_writes_no_texture_only_an_excluded_part_uses(tmp_path: Path, monkeypatch) -> None:
    import cdmw.services.mesh_live_texture_output as output
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    other = "character/texture/cd_phm_00_belt_0001_d.dds"
    plan = plan_live_texture_outputs(
        [_edit(tmp_path, users=("Upper body (a.pac)",)), _edit(tmp_path, game_path=other, users=("Belt (b.pac)",))],
        {GAME_PATH: (_entry(),), other: (_entry(other),)},
        parts_in_build=MeshEditorRustProcessMixin._parts_in_build(_set_host(frozenset({"b:0"}))))
    real = output.encode_live_texture_outputs
    monkeypatch.setattr(output, "encode_live_texture_outputs", lambda outputs, root, *, stop_event=None: real(
        outputs, root, stop_event=stop_event,
        encoder=lambda rgba, original, target, *, temp_root: Path(target).write_bytes(b"DDS edited")))
    worker = MeshDirectOutputWorker(1, None, "s", _entry("character/model/a.pac"), kind="loose_mod",
                                    output_path=tmp_path / "mods" / "Edited", texture_outputs=plan.outputs,
                                    texture_work_root=tmp_path / "work", textures_only=True)
    done = []
    worker.completed.connect(lambda _id, result: done.append(result))
    worker.error.connect(lambda _id, message: done.append(message))
    worker.run()
    (result,) = done
    assert not isinstance(result, str), result
    written = sorted(p.name for p in result.output_path.rglob("*.dds"))
    assert written == ["cd_phm_00_ub_00_0374_d.dds"], written


BELT_PATH = "character/texture/cd_phm_00_belt_0001_d.dds"
MISSING_PATH = "character/texture/missing.dds"


def mixed_plan(tmp_path: Path):
    """One edited texture of each status: written, left out (only Belt uses it), blocked."""

    return plan_live_texture_outputs(
        [_edit(tmp_path, users=("Upper body",)), _edit(tmp_path, game_path=BELT_PATH, users=("Belt",)),
         _edit(tmp_path, game_path=MISSING_PATH, users=("Upper body",))],
        {GAME_PATH: (_entry(),), BELT_PATH: (_entry(BELT_PATH),)}, parts_in_build=("Upper body",))


def test_each_edited_texture_says_whether_it_writes_is_left_out_or_is_blocked(tmp_path: Path) -> None:
    plan = mixed_plan(tmp_path)
    written = GAME_PATH + ": writes, R8G8B8A8_UNORM, 4 x 2, 1 mips"
    left_out = BELT_PATH + ": left out, no part in this mod uses it (Belt)"
    blocked = MISSING_PATH + ": blocked. The game file was not found in the archives."
    assert plan.plan_lines == (written, left_out, blocked)
    assert [row.status for row in plan.statuses] == ["writes", "left out", "blocked"]
    assert [output.game_path for output in plan.outputs] == [GAME_PATH]
    assert plan.refusals == (blocked,) and plan.left_out == (left_out,)


def test_the_status_lines_are_in_the_app_s_language(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.services.active_ui_translation import ACTIVE_UI_LOCALIZER_PROPERTY
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog

    app = QApplication.instance() or QApplication([])
    previous = app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="de")
    app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, localizer)
    parent = QWidget()
    try:
        lines = mixed_plan(tmp_path).plan_lines
        assert lines == (
            GAME_PATH + ": wird geschrieben, R8G8B8A8_UNORM, 4 x 2, 1 Mips",
            BELT_PATH + ": weggelassen, kein Teil dieser Mod verwendet sie (Belt)",
            MISSING_PATH + ": blockiert. Die Spieldatei wurde in den Archiven nicht gefunden.",
        )
        dialog = MeshModExportDialog(parent, title="Mod", description="", output_parent="", output_choice="",
                                     manager_profile="dmm", texture_plan=lines)
        localizer.apply(dialog)
        assert dialog.texture_plan.text() == "Bearbeitete Texturen in dieser Mod:\n" + "\n".join(lines)
        dialog.deleteLater()
    finally:
        app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY, previous)
        localizer.shutdown()
        parent.deleteLater()
        app.processEvents()


def test_the_body_a_fit_follows_is_not_in_the_build_unless_it_is_included() -> None:
    import threading

    from cdmw.services.mesh_asset_context import MeshAssetContext
    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    assets = (SimpleNamespace(asset_id="c", entry=_entry("character/model/coat.pac"), part_indices=(0,), role="target"),
              SimpleNamespace(asset_id="b", entry=_entry("character/model/body.pac"), part_indices=(1,), role="body"))
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="Coat"), SimpleNamespace(name="Body")])
    session = SimpleNamespace(export_lock=threading.RLock(), archive_refit_context=MeshAssetContext(assets=assets),
                              replacement_state=None)
    service = SimpleNamespace(working_mesh=lambda session_id: mesh, _session=lambda session_id: session,
                              cached_morph_state=lambda session_id: None)
    host = SimpleNamespace(standalone_controller=SimpleNamespace(mesh_service=service, active_session_id="s1"))
    assert MeshEditorRustProcessMixin._parts_in_build(host) == ("Coat (coat.pac)", "Body (body.pac)")
    assert MeshEditorRustProcessMixin._parts_in_build(host, include_body=False) == ("Coat (coat.pac)",)


def test_the_build_mod_list_follows_include_the_body() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog

    QApplication.instance() or QApplication([])
    parent = QWidget()
    without = ("body_d.dds: left out, no part in this mod uses it (Body (body.pac))",)
    with_body = ("body_d.dds: writes, BC7_UNORM_SRGB, 4 x 4, 3 mips",)
    dialog = MeshModExportDialog(parent, title="Mod", description="", output_parent="", output_choice="",
                                 manager_profile="dmm", body_files=("body.pac",), texture_plan=without,
                                 texture_plan_with_body=with_body)
    try:
        assert dialog.texture_plan.text() == "Edited textures in this mod:\n" + without[0]
        dialog.include_body.setChecked(True)
        assert dialog.texture_plan.text() == "Edited textures in this mod:\n" + with_body[0]
        dialog.include_body.setChecked(False)
        assert dialog.texture_plan.text() == "Edited textures in this mod:\n" + without[0]
    finally:
        dialog.deleteLater()
        parent.deleteLater()
        QApplication.processEvents()


def test_a_part_named_without_its_file_is_kept_by_that_part_in_any_file(tmp_path: Path) -> None:
    # The texture was opened while one file was open, then a body was loaded: the build
    # names its parts with their files, the edit's users do not.
    kept = ("Coat (coat.pac)", "Body (body.pac)")
    plan = plan_live_texture_outputs([_edit(tmp_path, users=("Coat",))], {GAME_PATH: (_entry(),)},
                                     parts_in_build=kept)
    assert len(plan.outputs) == 1 and plan.left_out == ()
    gone = plan_live_texture_outputs([_edit(tmp_path, users=("Belt",))], {GAME_PATH: (_entry(),)},
                                     parts_in_build=kept)
    assert gone.outputs == () and len(gone.left_out) == 1


def test_a_part_the_panel_could_not_name_never_leaves_its_texture_out(tmp_path: Path) -> None:
    # Without the editor's part names the Textures panel says "Part 1": that says nothing
    # about which build part it is, so the texture is written as before.
    plan = plan_live_texture_outputs([_edit(tmp_path, users=("Part 1 (coat.pac)",))], {GAME_PATH: (_entry(),)},
                                     parts_in_build=("Coat (coat.pac)",))
    assert len(plan.outputs) == 1 and plan.left_out == ()
