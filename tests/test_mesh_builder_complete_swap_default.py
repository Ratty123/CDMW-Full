"""An external Import Mesh opens as a complete source-owned swap, armed.

The switch that turns an import into a real swap used to sit under two collapsed
sections and default off, so a first import got the legacy overwrite route with
the target's shader layers still applied. It is armed for external models, and
it is the one material switch: the five routing checkboxes it used to sit among
are forced by it and no longer shown. Owner's direction, 2026-08-17: it lives in
Material Authority beside the runtime profile it applies to. Modify Original
never shows it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox

from tests.mesh_builder_driver import open_mesh_builder


def test_external_import_opens_with_the_complete_swap_armed_and_visible() -> None:
    with open_mesh_builder(dialog_title="Complete swap default") as builder:
        checkbox = builder.checkbox("MeshAlignmentCompleteExternalSwapCheckbox")
        assert checkbox.isChecked()
        # It is one row of the Material Authority form, beside the runtime
        # profile combo -- the same widget the combo lives in.
        profile_combo = builder.combo("MeshAlignmentCompleteSwapMaterialProfileCombo")
        assert checkbox.parentWidget() is profile_combo.parentWidget()
        assert builder.context["_complete_external_swap_enabled"]()
        # The switch forces the routing options it replaced in the form. They
        # stay constructed for the accept path and are hidden from the reader.
        for name in (
            "rebuild_sidecar_checkbox",
            "prune_unmapped_original_dds_checkbox",
            "inject_base_color_checkbox",
            "source_color_faithful_checkbox",
            "external_material_reset_checkbox",
        ):
            dependent = builder.control(name)
            assert isinstance(dependent, QCheckBox) and dependent.isChecked(), name
            assert dependent.isHidden(), name
        # The one acknowledgement with meaning of its own stays visible.
        unsafe = builder.checkbox("MeshAlignmentUnsafeMaterialPreflightExportCheckbox")
        assert not unsafe.isHidden()


def test_expert_manual_controls_follow_the_complete_swap_switch() -> None:
    """Expert routing rides the complete swap, not the unsafe-export acknowledgement."""
    with open_mesh_builder(dialog_title="Expert controls follow complete swap") as builder:
        builder.select_data(
            builder.combo("MeshAlignmentCompleteSwapMaterialProfileCombo"),
            "material_authority_manual",
        )
        expert = builder.control("manual_profile_controls")["scratch_roughness"]
        unsafe = builder.checkbox("MeshAlignmentUnsafeMaterialPreflightExportCheckbox")
        assert not unsafe.isChecked()
        assert expert.isEnabled()

        checkbox = builder.checkbox("MeshAlignmentCompleteExternalSwapCheckbox")
        builder.set_checked(checkbox, False)
        assert not expert.isEnabled()
        builder.set_checked(checkbox, True)
        assert expert.isEnabled()


def test_modify_original_hides_the_complete_swap_switch() -> None:
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original complete swap"
    ) as builder:
        checkbox = builder.checkbox("MeshAlignmentCompleteExternalSwapCheckbox")
        assert not checkbox.isChecked()
        assert not checkbox.isVisibleTo(builder.dialog)
