"""Edits of the layers the shader combines show on the model live (B item 6).

The Mesh Editor says which textures it samples, per part (``live_textures``): the
textures it loaded itself and the layer textures its shader combines. A layer it
dropped (grime) or a material it composed when the model opened is not there.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools
from cdmw.ui.mesh_editor.textures_panel import (
    MeshEditorTexturesPanel,
    shown_live_by_source,
    texture_rows_from_manifest,
    with_shown_live_textures,
)

DETAIL_SHA = "a1" * 32
MASK_SHA = "b2" * 32
NORMAL_SHA = "c3" * 32
GRIME_SHA = "d4" * 32


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _layer(role: str, colour_sha: str, colour_file: str) -> dict[str, object]:
    return {
        "layer_role": role,
        "diffuse": {"path": colour_file, "sha256": colour_sha.upper()},
        "diffuse_archive_path": "character/texture/" + colour_file.replace("texture-", "cd_texturelayer_"),
        "mask": {"path": "texture-0088-82bee05efdb3.dds", "sha256": MASK_SHA.upper()},
        "mask_archive_path": "character/texture/cd_phm_00_ub_00_0374_ma.dds",
    }


def _manifest() -> dict[str, object]:
    """Part 4 draws the detail layer; part 8 has the same file as grime (left out)."""
    return {
        "textures": [{
            "label": "7e1f229b05411c16_cd_phm_00_ub_00_0374_n.dds", "role": "normal",
            "file": {"path": "texture-0010-4092a553b170.dds", "sha256": NORMAL_SHA.upper()},
            "material_indices_by_lod": [[4, 8]],
        }],
        "preview_core_material_graph": {"materials": [
            {"lod_index": 0, "material_index": 4, "layers": [
                {"layer_role": "base"}, _layer("detail", DETAIL_SHA, "texture-0019-ca7b5b5a6c60.dds")]},
            {"lod_index": 0, "material_index": 8, "layers": [
                {"layer_role": "base"}, _layer("grime", DETAIL_SHA, "texture-0019-ca7b5b5a6c60.dds"),
                _layer("grime", GRIME_SHA, "texture-0043-d6a83b99f4c7.dds")]},
        ]},
    }


def _report() -> list[dict[str, object]]:
    # As the editor sends it: lower-case source hashes and the LOD 0 parts sampling each.
    return [{"source_sha256": DETAIL_SHA, "parts": [4]},
            {"source_sha256": MASK_SHA, "parts": [4]},
            {"source_sha256": NORMAL_SHA, "parts": [4, 8]}]


def _row(groups, part: int, sha: str):
    group = next(group for group in groups if group.part_index == part)
    return next(row for row in group.rows if row.source_sha256 == sha)


def test_the_editor_s_report_marks_each_layer_where_the_shader_draws_it() -> None:
    groups = texture_rows_from_manifest(_manifest())
    assert not _row(groups, 4, DETAIL_SHA).in_renderer, "before the report only loaded files count"
    assert _row(groups, 4, NORMAL_SHA).in_renderer

    shown = shown_live_by_source(_report() + [{"source_sha256": "", "parts": [1]}, "junk"])
    assert shown == {DETAIL_SHA: frozenset({4}), MASK_SHA: frozenset({4}), NORMAL_SHA: frozenset({4, 8})}
    groups = with_shown_live_textures(groups, shown)
    assert _row(groups, 4, DETAIL_SHA).in_renderer and _row(groups, 4, MASK_SHA).in_renderer
    # The same file as grime on part 8 is not drawn there, nor is part 8's own grime.
    assert not _row(groups, 8, DETAIL_SHA).in_renderer
    assert not _row(groups, 8, GRIME_SHA).in_renderer
    assert _row(groups, 8, NORMAL_SHA).in_renderer


def test_the_panel_takes_the_report_before_or_after_the_manifest(tmp_path: Path) -> None:
    _app()
    panel = MeshEditorTexturesPanel()
    shown = shown_live_by_source(_report())
    panel.set_shown_live_textures(shown)
    panel.set_manifest(_manifest(), session_root=tmp_path)
    assert panel.texture_shown_live(DETAIL_SHA.upper()), "drawn on part 4"
    assert not panel.texture_shown_live(GRIME_SHA)

    later = MeshEditorTexturesPanel()
    later.set_manifest(_manifest(), session_root=tmp_path)
    assert not later.texture_shown_live(DETAIL_SHA)
    later.set_shown_live_textures(shown)
    assert later.texture_shown_live(DETAIL_SHA)
    assert not _row(later.groups, 8, DETAIL_SHA).in_renderer
    # Another session's editor reports again.
    later.show_session(None)
    later.set_manifest(_manifest(), session_root=tmp_path)
    assert not later.texture_shown_live(DETAIL_SHA)
    for each in (panel, later):
        each.shutdown()
        each.deleteLater()


class _Editor(QWidget):
    def open_source_path(self, path, *, binding=None) -> None:
        pass


def test_the_open_texture_stops_saying_it_is_not_shown_once_the_editor_draws_it(tmp_path: Path) -> None:
    _app()
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    tools.open_target(LiveTextureTarget(
        session_id="doc", source_path=str(tmp_path / "layer.dds"), source_sha256=DETAIL_SHA,
        channel="detail", display_name="cd_texturelayer_003_0102.dds", in_renderer=False))
    assert "not shown" in tools.notice.text()
    tools.set_shown_live_sources([DETAIL_SHA.upper()])
    assert tools.target.in_renderer and tools.notice.text() == "" and tools.notice.isHidden()
    tools.set_shown_live_sources([MASK_SHA])
    assert "not shown" in tools.notice.text()
    tools.deleteLater()


def test_the_mesh_editor_passes_the_report_to_its_panels(tmp_path: Path) -> None:
    _app()
    panel = MeshEditorTexturesPanel()
    panel.set_manifest(_manifest(), session_root=tmp_path)
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    tools.open_target(LiveTextureTarget(
        session_id="doc", source_path=str(tmp_path / "layer.dds"), source_sha256=DETAIL_SHA,
        channel="detail", display_name="layer.dds", in_renderer=False))
    editor = SimpleNamespace(
        standalone_rust_protocol_events=[], standalone_rust_failure_reported=False,
        _validate_rust_event_identity=lambda payload: "live_textures",
        _textures_panel=lambda: panel, _texture_tools_panel=lambda: tools)
    editor._show_live_textures = lambda textures: MeshEditorRustProcessMixin._show_live_textures(editor, textures)
    MeshEditorRustProcessMixin._handle_rust_protocol_event(editor, {"event": "live_textures", "textures": _report()})
    assert panel.texture_shown_live(DETAIL_SHA) and tools.notice.isHidden()
    # Opening a row asks the panel whether any part draws the file.
    part_8_row = _row(panel.groups, 8, DETAIL_SHA)
    assert not part_8_row.in_renderer
    assert MeshEditorRustProcessMixin._texture_shown_live(panel, part_8_row)
    assert not MeshEditorRustProcessMixin._texture_shown_live(panel, _row(panel.groups, 8, GRIME_SHA))
    panel.shutdown()
    for each in (panel, tools):
        each.deleteLater()
