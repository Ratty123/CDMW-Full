from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from cdmw.ui.archive_browser.static_replacement_combo_options import (
    ALIGNMENT_MODE_OPTIONS,
    DONOR_MODE_OPTIONS,
    EDGE_RELIEF_SOURCE_OPTIONS,
    MESH_EDIT_DELETE_MODE_OPTIONS,
    MESH_EDIT_FALLOFF_OPTIONS,
    MESH_EDIT_SCOPE_OPTIONS,
    MESH_EDIT_SELECTION_DEPTH_OPTIONS,
    MESH_EDIT_SELECTION_MODE_OPTIONS,
    MESH_EDIT_TOOL_BUTTON_OPTIONS,
    MESH_EDIT_TOOL_OPTIONS,
    PARTS_OUTLINER_ROLE_OPTIONS,
    PREVIEW_MODE_OPTIONS,
    PREVIEW_RENDERER_OPTIONS,
    SOURCE_ROLE_OPTIONS,
    SOURCE_TREE_ROLE_OPTIONS,
    TEXTURE_OUTPUT_SIZE_OPTIONS,
    TEXTURE_UV_ROTATION_OPTIONS,
    d3d11_view_mode_options,
    populate_combo_options,
)

_APP = QApplication.instance() or QApplication([])


def _combo_entries(combo: QComboBox) -> list[tuple[str, object]]:
    return [(combo.itemText(index), combo.itemData(index)) for index in range(combo.count())]


def test_static_combo_options_keep_expected_order_and_values() -> None:
    assert PREVIEW_RENDERER_OPTIONS == (("Native D3D11 accurate", "d3d11"),)
    assert PREVIEW_MODE_OPTIONS == (
        ("Side by side", "side_by_side"),
        ("Overlay", "overlay"),
        ("Replacement only", "replacement_only"),
        ("Original only", "original_only"),
    )
    assert TEXTURE_UV_ROTATION_OPTIONS == (
        ("0 deg", 0),
        ("90 deg", 90),
        ("180 deg", 180),
        ("270 deg", 270),
    )
    assert DONOR_MODE_OPTIONS[0] == ("Authoritative donor recipe", "authoritative_recipe")
    assert ALIGNMENT_MODE_OPTIONS == (("Auto: Force grid flat", "grid_flat"), ("Manual only", "manual"))
    assert EDGE_RELIEF_SOURCE_OPTIONS[-1] == ("Generate from source", "generate_source")
    assert TEXTURE_OUTPUT_SIZE_OPTIONS == (("Source image size", "source"), ("Original DDS size", "original"))
    assert PARTS_OUTLINER_ROLE_OPTIONS[0] == ("auto", "")
    assert PARTS_OUTLINER_ROLE_OPTIONS[-1] == ("unknown", "unknown")
    assert SOURCE_ROLE_OPTIONS[0] == ("Auto / inferred", "")
    assert SOURCE_ROLE_OPTIONS[-1] == ("Unknown", "unknown")
    assert ("Head / face", "head/face") in SOURCE_ROLE_OPTIONS
    assert SOURCE_TREE_ROLE_OPTIONS == (
        ("Auto / inferred", ""),
        ("Blade", "blade"),
        ("Handle / grip", "handle"),
        ("Guard / crossguard", "guard"),
        ("Accessory / detail", "accessory/detail"),
        ("Glow / emissive", "glow"),
        ("Cloth / fabric", "cloth"),
        ("Unknown", "unknown"),
    )
    assert MESH_EDIT_SCOPE_OPTIONS == (("All editable parts", "all"), ("Selected part only", "selected"))
    assert MESH_EDIT_TOOL_OPTIONS[-1] == ("Select Vertices", "vertex")
    assert MESH_EDIT_TOOL_BUTTON_OPTIONS[4] == (
        "Remove Faces",
        "remove",
        "Cut away faces touched by the brush. Boundaries stay open.",
    )
    assert MESH_EDIT_DELETE_MODE_OPTIONS == (("On release", "release"), ("During drag", "live"))
    assert MESH_EDIT_FALLOFF_OPTIONS == (
        ("Smooth", "smooth"),
        ("Linear", "linear"),
        ("Sharp", "sharp"),
        ("Constant", "constant"),
    )
    assert MESH_EDIT_SELECTION_MODE_OPTIONS[-1] == ("Rectangle Select", "rectangle")
    assert MESH_EDIT_SELECTION_DEPTH_OPTIONS == (("Visible Only", "visible"), ("X-Ray", "xray"))


def test_d3d11_view_mode_options_uses_label_mapping_with_fallback() -> None:
    assert d3d11_view_mode_options(("lit", "debug"), {"lit": "Lit"}) == (
        ("Lit", "lit"),
        ("debug", "debug"),
    )


def test_populate_combo_options_adds_labels_and_payloads() -> None:
    combo = QComboBox()

    populate_combo_options(combo, (("First", 1), ("Second", "two")))

    assert _combo_entries(combo) == [("First", 1), ("Second", "two")]
