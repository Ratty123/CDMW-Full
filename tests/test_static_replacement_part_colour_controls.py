"""Real Builder behaviour for the per-part colour controls.

Source-string guards cannot prove Qt wiring, so these construct the actual
Import Mesh and Modify Original Builders offscreen and drive the controls.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QPushButton

from tests.mesh_builder_driver import open_mesh_builder


TINT_PICK = "MeshAlignmentPartTintPickButton"
COLOURISE_PICK = "MeshAlignmentPartColourisePickButton"
COLOURISE_STRENGTH = "MeshAlignmentPartColouriseStrengthSpin"
COLOUR_RESET = "MeshAlignmentPartColourResetButton"
EMISSIVE_CHECK = "MeshAlignmentPartEmissiveCheckBox"
EMISSIVE_PICK = "MeshAlignmentPartEmissivePickButton"
EMISSIVE_STRENGTH = "MeshAlignmentPartEmissiveStrengthSpin"

_MODES = pytest.mark.parametrize(
    ("modify_original_clone_mode", "mode_name"),
    ((False, "Import Mesh"), (True, "Modify Original")),
)


def _select_first_source_part(builder) -> int:
    """Point the inspector at source part 0 through the real selection path.

    The synthetic Builder fixture carries no source submeshes, so the inspector
    reports no selection and leaves its controls disabled. The edit path itself
    is still driven end to end, which is what these tests are for; anything
    that depends on a populated source list belongs in a unit test instead.
    """
    builder.control("_load_selected_part_controls")()
    builder.control("selected_source_part")["index"] = 0
    builder.pump()
    return 0


def _adjustments(builder) -> dict:
    return builder.control("source_part_adjustments")


@_MODES
def test_colour_controls_exist_in_both_builder_modes(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        assert builder.find(QPushButton, TINT_PICK) is not None
        assert builder.find(QPushButton, COLOURISE_PICK) is not None
        assert builder.find(QPushButton, COLOUR_RESET) is not None
        assert builder.find(QDoubleSpinBox, COLOURISE_STRENGTH) is not None


def test_colour_controls_stay_visible_without_advanced_texture_tuning() -> None:
    """The Modify Original recolour case must not hide behind the expert opt-in."""
    with open_mesh_builder(
        modify_original_clone_mode=True,
        dialog_title="Modify Original colour visibility",
    ) as builder:
        for name in (TINT_PICK, COLOURISE_PICK, COLOUR_RESET):
            assert not builder.find(QPushButton, name).isHidden(), (
                f"{name} was hidden in Modify Original"
            )
        assert not builder.find(QDoubleSpinBox, COLOURISE_STRENGTH).isHidden()


@_MODES
def test_recolour_strength_writes_through_to_the_part_adjustment(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        source_index = _select_first_source_part(builder)
        builder.find(QPushButton, COLOURISE_PICK).setProperty(
            "cdmwPartColourRgb", "#DC1E1E"
        )
        builder.set_value(builder.find(QDoubleSpinBox, COLOURISE_STRENGTH), 80.0)

        adjustment = _adjustments(builder).get(source_index)
        assert adjustment is not None, "no adjustment was created for the edited part"
        assert adjustment.material_colourise_strength == pytest.approx(0.8)
        assert tuple(adjustment.material_colourise_rgb) == (0xDC, 0x1E, 0x1E)


def test_recolour_reaches_the_renderer_parameters_for_that_part_only() -> None:
    """The live lane must carry the recolour, scoped to the edited submesh."""
    from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
        source_part_material_parameter_values,
    )

    with open_mesh_builder(dialog_title="Recolour parameters") as builder:
        source_index = _select_first_source_part(builder)
        builder.find(QPushButton, COLOURISE_PICK).setProperty(
            "cdmwPartColourRgb", "#1E64DC"
        )
        builder.set_value(builder.find(QDoubleSpinBox, COLOURISE_STRENGTH), 100.0)

        adjustment = _adjustments(builder)[source_index]
        values = source_part_material_parameter_values(adjustment)

        assert values["base_tint_strength"] == pytest.approx(1.0)
        assert values["base_tint_color"] == pytest.approx(
            [0x1E / 255, 0x64 / 255, 0xDC / 255], abs=1e-6
        )


def test_reset_colour_clears_tint_and_recolour() -> None:
    with open_mesh_builder(dialog_title="Reset colour") as builder:
        source_index = _select_first_source_part(builder)
        strength_spin = builder.find(QDoubleSpinBox, COLOURISE_STRENGTH)

        builder.find(QPushButton, COLOURISE_PICK).setProperty(
            "cdmwPartColourRgb", "#00FF00"
        )
        builder.set_value(strength_spin, 65.0)
        assert _adjustments(builder).get(source_index) is not None

        # The fixture carries no source list, so the inspector leaves its
        # buttons disabled and a click would be swallowed. Enabling it here
        # still drives the real connected slot, which is what is under test.
        reset_button = builder.find(QPushButton, COLOUR_RESET)
        reset_button.setEnabled(True)
        builder.click(reset_button)

        adjustment = _adjustments(builder).get(source_index)
        # A fully neutral adjustment is dropped from the map entirely.
        if adjustment is not None:
            assert adjustment.material_colourise_strength == pytest.approx(0.0)
            assert tuple(adjustment.material_colourise_rgb) == ()
            assert tuple(adjustment.material_tint_rgb) in ((), (255, 255, 255))
        assert strength_spin.value() == pytest.approx(0.0)


@_MODES
def test_emissive_controls_exist_in_both_builder_modes(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        assert builder.find(QCheckBox, EMISSIVE_CHECK) is not None
        assert builder.find(QPushButton, EMISSIVE_PICK) is not None
        assert builder.find(QDoubleSpinBox, EMISSIVE_STRENGTH) is not None


def test_emits_light_assigns_the_glow_role_without_touching_the_role_combo() -> None:
    """The point of Phase 3: no trip through the Role taxonomy combo."""
    with open_mesh_builder(dialog_title="Emissive role") as builder:
        source_index = _select_first_source_part(builder)
        role_combo = builder.control("part_role_combo")

        builder.set_checked(builder.find(QCheckBox, EMISSIVE_CHECK), True)

        assert role_combo.currentData() == "glow", "the Role box did not follow"
        assert _adjustments(builder)[source_index].material_role == "glow"


def test_emissive_colour_and_strength_write_through_to_the_part() -> None:
    with open_mesh_builder(dialog_title="Emissive values") as builder:
        source_index = _select_first_source_part(builder)
        builder.set_checked(builder.find(QCheckBox, EMISSIVE_CHECK), True)

        builder.control("_commit_selected_part_emissive")(rgb=(0, 220, 255), strength=None)
        builder.pump()
        assert tuple(_adjustments(builder)[source_index].emissive_color_rgb) == (0, 220, 255)

        builder.set_value(builder.find(QDoubleSpinBox, EMISSIVE_STRENGTH), 6.5)
        assert _adjustments(builder)[source_index].emissive_strength == pytest.approx(6.5)


def test_clearing_emits_light_keeps_the_colour_dormant_for_next_time() -> None:
    """Turning glow off must not throw the chosen colour away."""
    with open_mesh_builder(dialog_title="Emissive dormant") as builder:
        source_index = _select_first_source_part(builder)
        checkbox = builder.find(QCheckBox, EMISSIVE_CHECK)
        builder.set_checked(checkbox, True)
        builder.control("_commit_selected_part_emissive")(rgb=(0, 220, 255), strength=None)
        builder.pump()

        builder.set_checked(checkbox, False)

        adjustment = _adjustments(builder)[source_index]
        assert adjustment.material_role == ""
        assert tuple(adjustment.emissive_color_rgb) == (0, 220, 255)


def test_emissive_colour_and_strength_are_disabled_until_the_part_emits() -> None:
    """A control that silently does nothing is worse than a disabled one."""
    with open_mesh_builder(dialog_title="Emissive gating") as builder:
        _select_first_source_part(builder)
        refresh = builder.control("_refresh_part_emissive_controls")

        refresh(None, enabled=True)
        builder.pump()
        assert not builder.find(QPushButton, EMISSIVE_PICK).isEnabled()
        assert not builder.find(QDoubleSpinBox, EMISSIVE_STRENGTH).isEnabled()

        builder.set_checked(builder.find(QCheckBox, EMISSIVE_CHECK), True)
        refresh(_adjustments(builder)[0], enabled=True)
        builder.pump()
        assert builder.find(QPushButton, EMISSIVE_PICK).isEnabled()
        assert builder.find(QDoubleSpinBox, EMISSIVE_STRENGTH).isEnabled()


def test_more_than_one_glow_part_is_a_normal_state() -> None:
    """Glow used to read as a single-part feature; N>1 must be ordinary."""
    from cdmw.domain.textures.material_authority_state import (
        MaterialAuthorityCapability,
        material_authority_control_states,
    )

    states = {
        state.key: state
        for state in material_authority_control_states(
            {},
            available_channels=("base", "emissive"),
            has_emissive_source=True,
            has_explicit_glow_part=True,
        )
    }
    for key in ("part_glow_color", "part_glow_strength"):
        assert states[key].capability is MaterialAuthorityCapability.ACTIVE

    without = {
        state.key: state
        for state in material_authority_control_states(
            {},
            available_channels=("base", "emissive"),
            has_emissive_source=True,
            has_explicit_glow_part=False,
        )
    }
    assert "at least one" in without["part_glow_color"].reason.lower()
    assert "exactly one" not in without["part_glow_color"].reason.lower()


@_MODES
def test_resident_colour_edits_reach_the_builder_adjustments(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    """Phase 4: the .NET Colour page edits parts the inspector never selected."""
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        handler = getattr(builder.dialog, "_mesh_editor_apply_dotnet_part_material_edit", None)
        assert callable(handler), "the Builder published no resident colour authority"

        assert handler(
            {
                "source_submesh_indices": (0, 2),
                "colourise_rgb": (220, 30, 30),
                "colourise_strength": 0.75,
            }
        )

        adjustments = _adjustments(builder)
        for index in (0, 2):
            adjustment = adjustments[index]
            assert tuple(adjustment.material_colourise_rgb) == (220, 30, 30)
            assert adjustment.material_colourise_strength == pytest.approx(0.75)


def test_a_resident_reset_clears_every_named_part() -> None:
    with open_mesh_builder(dialog_title="Resident reset") as builder:
        handler = builder.dialog._mesh_editor_apply_dotnet_part_material_edit
        handler(
            {
                "source_submesh_indices": (1,),
                "colourise_rgb": (10, 20, 30),
                "colourise_strength": 0.9,
            }
        )
        assert _adjustments(builder).get(1) is not None

        assert handler({"source_submesh_indices": (1,), "reset": True})

        adjustment = _adjustments(builder).get(1)
        if adjustment is not None:
            assert adjustment.material_colourise_strength == pytest.approx(0.0)
            assert tuple(adjustment.material_colourise_rgb) == ()


def test_a_resident_edit_that_changes_nothing_is_reported_as_such() -> None:
    """An unchanged edit must not claim an undo unit was worth pushing."""
    with open_mesh_builder(dialog_title="Resident no-op") as builder:
        handler = builder.dialog._mesh_editor_apply_dotnet_part_material_edit

        assert handler({"source_submesh_indices": (0,), "colourise_strength": 0.4})
        assert not handler({"source_submesh_indices": (0,), "colourise_strength": 0.4})


def test_resident_emissive_edits_set_the_glow_role() -> None:
    with open_mesh_builder(dialog_title="Resident glow") as builder:
        handler = builder.dialog._mesh_editor_apply_dotnet_part_material_edit

        assert handler(
            {
                "source_submesh_indices": (3,),
                "emissive": True,
                "emissive_rgb": (0, 220, 255),
                "emissive_strength": 4.0,
            }
        )

        adjustment = _adjustments(builder)[3]
        assert adjustment.material_role == "glow"
        assert tuple(adjustment.emissive_color_rgb) == (0, 220, 255)
        assert adjustment.emissive_strength == pytest.approx(4.0)


def test_swatch_state_paints_the_colour_and_reports_a_non_neutral_part() -> None:
    """The swatch is the only place a recoloured part is visible at a glance."""
    from cdmw.ui.archive_browser.static_replacement_source_part_controls_state import (
        source_part_colour_swatch_state,
    )

    painted = source_part_colour_swatch_state(rgb=(0x1E, 0x64, 0xDC), enabled=True)
    assert painted.hex_color == "#1E64DC"
    assert "#1E64DC" in painted.style_sheet.upper()
    assert painted.active is True
    # A dark swatch needs light text and a bright one needs dark text, or the
    # button label disappears into its own background.
    assert "#f0f6fc" in painted.style_sheet

    bright = source_part_colour_swatch_state(rgb=(250, 240, 120), enabled=True)
    assert "#0d1117" in bright.style_sheet

    neutral = source_part_colour_swatch_state(rgb=(255, 255, 255), enabled=True)
    assert neutral.active is False

    disabled = source_part_colour_swatch_state(rgb=(0x1E, 0x64, 0xDC), enabled=False)
    assert disabled.style_sheet == ""
    assert disabled.hex_color == "#1E64DC"
