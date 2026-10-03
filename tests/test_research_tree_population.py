from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QTreeWidget,
)
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
from cdmw.ui.research.tree_column_specs import research_tree_column_specs
from cdmw.ui.research.tree_helpers import (
    auto_fit_persisted_research_tree_columns,
    auto_fit_research_tree_columns,
    research_tree_storage_key,
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


def test_research_tree_column_specs_cover_expected_tree_storage_names() -> None:
    specs = research_tree_column_specs()
    by_storage = {spec.storage_name: spec for spec in specs}

    assert set(by_storage) == {
        "archive_picker",
        "texture_group",
        "classifier",
        "unknown_group",
        "unknown_member",
        "reference",
        "sidecar",
        "ui_constraint",
        "heatmap",
        "mip",
        "normal",
        "budget_file",
        "budget_class",
        "budget_group",
        "budget_profile",
        "notes",
    }
    assert by_storage["archive_picker"].tree_attr == "archive_picker_tree"
    assert by_storage["archive_picker"].min_widths[0] == 260
    assert by_storage["unknown_member"].min_widths[5] == 220
    assert by_storage["budget_profile"].min_widths[4] == 90


def test_research_tree_column_specs_are_immutable() -> None:
    spec = research_tree_column_specs()[0]

    try:
        spec.min_widths[0] = 1  # type: ignore[index]
    except TypeError:
        pass
    else:  # pragma: no cover - defensive branch
        raise AssertionError("research tree column specs should not be mutable")


def test_research_tree_storage_key_prefixes_research_namespace() -> None:
    assert research_tree_storage_key("archive_picker") == "research/archive_picker"


def test_auto_fit_research_tree_columns_expands_stretch_column() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(3)
    tree.resize(520, 200)
    tree.header().resizeSection(0, 80)
    tree.header().resizeSection(1, 90)
    tree.header().resizeSection(2, 100)

    auto_fit_research_tree_columns(tree, stretch_column=0, min_widths={0: 180, 1: 110, 2: 120})

    assert tree.header().sectionSize(1) >= 110
    assert tree.header().sectionSize(2) >= 120
    assert tree.header().sectionSize(0) >= 180


def test_auto_fit_research_tree_columns_respects_saved_widths() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.resize(220, 160)
    tree.header().resizeSection(0, 1000)
    tree.header().resizeSection(1, 1000)

    auto_fit_research_tree_columns(tree, stretch_column=0, min_widths={0: 300, 1: 300}, has_saved_columns=True)

    assert tree.header().sectionSize(0) == 1000
    assert tree.header().sectionSize(1) == 1000


def test_auto_fit_persisted_research_tree_columns_checks_storage_namespace() -> None:
    class Settings:
        def value(self, key: str, default: object = None) -> object:
            if key == "research/archive_picker/column_widths":
                return [1000, 1000]
            return default

    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.resize(220, 160)
    tree.header().resizeSection(0, 1000)
    tree.header().resizeSection(1, 1000)

    auto_fit_persisted_research_tree_columns(
        tree,
        Settings(),
        "archive_picker",
        stretch_column=0,
        min_widths={0: 300, 1: 300},
    )

    assert tree.header().sectionSize(0) == 1000
    assert tree.header().sectionSize(1) == 1000
