from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.core.research import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    SidecarDiscoveryRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureSetMember,
    TextureUsageHeatRow,
)
from cdmw.ui.research.tree_population import (
    populate_research_classification_tree,
    populate_research_heatmap_tree,
    populate_research_mip_tree,
    populate_research_normal_tree,
    populate_research_reference_tree,
    populate_research_sidecar_tree,
    populate_research_texture_group_tree,
    populate_research_ui_constraint_tree,
)


_APP = QApplication.instance() or QApplication([])


def test_populate_research_texture_group_and_classification_trees_ignore_invalid_rows() -> None:
    group_tree = QTreeWidget()
    group = TextureSetGroup(
        "texture/armor",
        "Armor",
        1,
        ["pak_a"],
        ["color"],
        [TextureSetMember("texture/armor.dds", "pak_a", "color", ".dds")],
    )

    first = populate_research_texture_group_tree(group_tree, [object(), group])

    assert first is group_tree.topLevelItem(0)
    assert group_tree.currentItem() is first
    assert group_tree.topLevelItemCount() == 1
    assert first.text(0) == "Armor"

    classifier_tree = QTreeWidget()
    populate_research_classification_tree(
        classifier_tree,
        [object(), TextureClassificationRow("texture/armor.dds", "pak_a", "color", 90, "name", "texture/armor")],
    )

    assert classifier_tree.topLevelItemCount() == 1
    assert classifier_tree.topLevelItem(0).text(1) == "color"


def test_populate_research_analysis_trees_select_expected_first_rows() -> None:
    heatmap_tree = QTreeWidget()
    populate_research_heatmap_tree(
        heatmap_tree,
        [
            object(),
            TextureUsageHeatRow("world", "terrain", 2, 1, 0, 0, 1, 0, 25, ["a.dds"]),
            TextureUsageHeatRow("world", "props", 1, 0, 1, 0, 0, 0, 15, ["b.dds"]),
        ],
    )
    assert heatmap_tree.topLevelItemCount() == 1
    assert heatmap_tree.topLevelItem(0).childCount() == 2

    mip_tree = QTreeWidget()
    assert populate_research_mip_tree(
        mip_tree,
        [object(), MipAnalysisRow("texture/armor.dds", "BC7", "BC7", "512x512", "1024x1024", 8, 9, 1)],
    )
    assert mip_tree.currentItem() is mip_tree.topLevelItem(0)

    normal_tree = QTreeWidget()
    assert populate_research_normal_tree(
        normal_tree,
        [NormalValidationRow("texture/armor_n.dds", "Output", "BC5", "512x512", 0)],
        select_first=True,
    )
    assert normal_tree.currentItem() is normal_tree.topLevelItem(0)


def test_populate_research_reference_constraint_and_sidecar_trees() -> None:
    row = MaterialTextureReferenceRow(
        "ui/layout.xml",
        "pak_a",
        "texture/ui.dds",
        "pak_b",
        "ui_rect",
        12,
        "snippet",
        get_rect_raw="0,0,64,32",
        constraint_kind="Explicit UI rect",
    )

    reference_tree = QTreeWidget()
    assert populate_research_reference_tree(reference_tree, [object(), row])
    assert reference_tree.currentItem() is reference_tree.topLevelItem(0)

    constraint_tree = QTreeWidget()
    populate_research_ui_constraint_tree(constraint_tree, [row, object()])
    assert constraint_tree.topLevelItemCount() == 1
    assert constraint_tree.topLevelItem(0).text(0) == "texture/ui.dds"

    sidecar_tree = QTreeWidget()
    assert populate_research_sidecar_tree(
        sidecar_tree,
        [SidecarDiscoveryRow("model.pac", "texture/ui.dds", "pak_a", "sidecar", 91, "nearby")],
    )
    assert sidecar_tree.currentItem() is sidecar_tree.topLevelItem(0)
