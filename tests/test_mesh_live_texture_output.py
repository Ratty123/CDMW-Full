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
    assert plan.plan_lines == (GAME_PATH + ": R8G8B8A8_UNORM, 4 x 2, 1 mips (shared by Upper body, Belt)",)
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
