"""Step 8 item 6: a colour CDMW generated from several files says why it cannot be edited
and offers the files it is made from."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.textures_panel import (
    COLUMN_STATE,
    NOT_ONE_FILE_REASON,
    NOT_ONE_FILE_STATE,
    MeshEditorTexturesPanel,
    contributing_rows,
    made_from_several_files,
    texture_rows_from_manifest,
)

_APP = QApplication.instance() or QApplication([])
GENERATED_SHA, MASK_SHA, DETAIL_SHA, NORMAL_SHA = "D" * 64, "E" * 64, "F" * 64, "B" * 64


def _manifest(*, with_files: bool = True) -> dict:
    layers = [{"layer_role": "base",
               "mask": {"path": "texture-0002.dds", "sha256": MASK_SHA},
               "mask_archive_path": "character/texture/cd_armor_02_mask.dds"},
              {"layer_role": "detail",
               "diffuse": {"path": "texture-0003.dds", "sha256": DETAIL_SHA},
               "diffuse_archive_path": "character/texture/cd_texturelayer_004_0004.dds"}] if with_files else []
    return {
        "textures": [
            {"label": "lod-0000-material-0000-base_color.dds", "role": "base_color",
             "file": {"path": "texture-0000.dds", "sha256": GENERATED_SHA}, "material_indices_by_lod": [[0]]},
            # A real game file whose game path is not known: not "made from several files".
            {"label": "cd_armor_02_n.dds", "role": "normal",
             "file": {"path": "texture-0001.dds", "sha256": NORMAL_SHA}, "material_indices_by_lod": [[0]]},
        ],
        "preview_core_material_graph": {"materials": [{"lod_index": 0, "material_index": 0, "layers": layers}]},
        "state": {"skeleton": {"parts": [{"index": 0, "name": "Chest"}]}},
    }


def test_a_generated_colour_is_told_apart_from_a_file_whose_path_is_unknown():
    (group,) = texture_rows_from_manifest(_manifest())
    generated = next(row for row in group.rows if row.source_sha256 == GENERATED_SHA.lower())
    normal = next(row for row in group.rows if row.source_sha256 == NORMAL_SHA.lower())
    assert made_from_several_files(generated) and not made_from_several_files(normal)
    # The layer mask first, then the detail map: the files the shader made the colour from.
    assert [row.file_name for row in contributing_rows(group, generated)][:2] == [
        "cd_armor_02_mask.dds", "cd_texturelayer_004_0004.dds"]
    assert contributing_rows(group, normal) == ()


def test_the_row_says_why_and_double_click_opens_what_it_is_made_from():
    panel = MeshEditorTexturesPanel()
    panel.set_manifest(_manifest())
    activated, refused = [], []
    panel.texture_activated.connect(activated.append)
    panel.texture_refused.connect(refused.append)
    (group,) = panel.groups
    generated = next(row for row in group.rows if made_from_several_files(row))
    item = panel.texture_item(generated.texture_id)
    assert item.text(COLUMN_STATE) == NOT_ONE_FILE_STATE
    assert "cd_armor_02_mask.dds" in item.toolTip(COLUMN_STATE)
    chosen = contributing_rows(group, generated)[1]
    panel._choose_contributor = lambda rows: chosen  # the menu's answer
    panel._on_item_double_clicked(item, 0)
    assert activated == [chosen.texture_id] and refused == []
    panel._choose_contributor = lambda rows: None  # the menu closed without a choice
    panel._on_item_double_clicked(item, 0)
    assert refused == [NOT_ONE_FILE_REASON]
    panel.deleteLater()


def test_a_generated_colour_with_nothing_to_offer_says_so_instead_of_opening():
    panel = MeshEditorTexturesPanel()
    panel.set_manifest(_manifest(with_files=False))
    refused, activated = [], []
    panel.texture_refused.connect(refused.append)
    panel.texture_activated.connect(activated.append)
    (group,) = panel.groups
    generated = next(row for row in group.rows if made_from_several_files(row))
    panel._on_item_double_clicked(panel.texture_item(generated.texture_id), 0)
    assert refused == [NOT_ONE_FILE_REASON] and activated == []
    panel.deleteLater()
