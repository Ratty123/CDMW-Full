from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.material_profiles import get_complete_swap_material_profile
from cdmw.ui.archive_browser.static_replacement_dialog_remaining_callbacks import (
    create_alignment_complete_swap_profile_select_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_material_authority_controls import (
    material_authority_requested_profile_name,
)


ROOT = Path(__file__).resolve().parents[1]


class _ProfileComboProbe:
    items = ("material_authority_detail_mask", "material_authority_manual")

    def __init__(self) -> None:
        self.index = 1

    def findData(self, value: object) -> int:
        try:
            return self.items.index(str(value))
        except ValueError:
            return -1

    def currentIndex(self) -> int:
        return self.index

    def setCurrentIndex(self, index: int) -> None:
        self.index = int(index)


def test_obsolete_profile_setting_migrates_to_automatic() -> None:
    assert get_complete_swap_material_profile("placeholder_safe").name == "material_authority_detail_mask"
    assert get_complete_swap_material_profile("automatic").label == "Automatic"
    writes: list[tuple[object, str]] = []
    settings = SimpleNamespace(values={})
    settings.setValue = lambda key, value: settings.values.__setitem__(key, value)
    combo = _ProfileComboProbe()
    callback = create_alignment_complete_swap_profile_select_callbacks(
        {
            "_material_authority_requested_profile_name_helper": material_authority_requested_profile_name,
            "complete_swap_material_profile_combo": combo,
            "complete_swap_profile_store_path": "profile.json",
            "get_complete_swap_material_profile": get_complete_swap_material_profile,
            "self": SimpleNamespace(settings=settings),
            "write_complete_swap_calibrated_material_profile": lambda path, name: writes.append((path, name)),
        }
    )._select_complete_swap_material_profile

    callback("material_authority_placeholder_safe_test")

    assert combo.index == 0
    assert settings.values["settings/complete_swap_material_profile"] == "material_authority_detail_mask"
    assert writes == [("profile.json", "material_authority_detail_mask")]


def test_material_authority_expert_controls_are_one_collapsed_group() -> None:
    source = (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_sections_setup_options_transform_part_01.py").read_text(encoding="utf-8")
    assert "material_authority_unsafe_section = _state.CollapsibleSection('Unsafe Expert Controls', expanded=False)" in source
    assert "_state.unsafe_material_widgets = (" in source
    assert "for _state.unsafe_widget in _state.unsafe_material_widgets:" in source
