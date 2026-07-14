from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.archives.format import material_sidecar_candidate_basenames_for_model
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("package/0.pamt"),
        paz_file=Path("package/0.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)


class _Action:
    def __init__(self, text: str) -> None:
        self.text = text
        self.enabled = True
        self.tooltip = ""
        self.triggered = _Signal()

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip


class _Menu:
    def __init__(self) -> None:
        self.sections: list[str] = []
        self.actions: list[_Action] = []

    def addSection(self, _icon: object, label: str) -> None:
        self.sections.append(label)

    def addAction(self, _icon: object, text: str) -> _Action:
        action = _Action(text)
        self.actions.append(action)
        return action


@pytest.mark.parametrize(
    ("model_path", "expected"),
    (
        ("character/model/armor.pac", ("armor.pac_xml", "armor.pac.xml")),
        ("character/model/armor.pam", ("armor.pami", "armor.pam_xml", "armor.pam.xml")),
        (
            "character/model/armor.pamlod",
            ("armor.pami", "armor.pamlod_xml", "armor.pamlod.xml"),
        ),
        ("character/model/armor.dds", ()),
    ),
)
def test_model_sidecar_candidates_cover_supported_archive_filename_variants(
    model_path: str,
    expected: tuple[str, ...],
) -> None:
    assert material_sidecar_candidate_basenames_for_model(model_path) == expected


@pytest.mark.parametrize("sidecar_basename", ("armor.pac_xml", "armor.pac.xml"))
def test_pac_material_action_resolves_supported_xml_companion(sidecar_basename: str) -> None:
    mesh = _entry("character/model/armor.pac")
    sidecar = _entry(f"character/model/{sidecar_basename}")
    entries_by_path = {sidecar.path: sidecar}
    owner = SimpleNamespace(
        archive_entries_by_basename={sidecar.basename.lower(): [sidecar]},
        _find_archive_entry_by_virtual_path=entries_by_path.get,
    )

    resolved = ArchiveMaterialSidecarActionsMixin._related_material_sidecar_entry_for_archive_entry(owner, mesh)

    assert resolved is sidecar


def test_mesh_without_material_sidecar_has_no_edit_target() -> None:
    mesh = _entry("character/model/armor.pac")
    owner = SimpleNamespace(
        archive_entries_by_basename={},
        _find_archive_entry_by_virtual_path=lambda _path: None,
    )

    resolved = ArchiveMaterialSidecarActionsMixin._related_material_sidecar_entry_for_archive_entry(owner, mesh)

    assert resolved is None


def test_pac_material_context_action_is_disabled_without_sidecar() -> None:
    menu = _Menu()
    owner = SimpleNamespace(_related_material_sidecar_entry_for_archive_entry=lambda _entry: None)

    ArchiveBrowserActionMixin._add_archive_material_context_action(
        owner,
        menu,
        {"texture": object()},
        _entry("character/model/armor.pac"),
    )

    assert menu.sections == ["Material"]
    assert [action.text for action in menu.actions] == ["Edit Material Values..."]
    assert menu.actions[0].enabled is False
    assert menu.actions[0].tooltip.startswith("Unavailable: no recognized companion")
    assert menu.actions[0].triggered.callbacks == []


def test_pac_material_context_action_opens_resolved_sidecar() -> None:
    menu = _Menu()
    sidecar = _entry("character/model/armor.pac.xml")
    opened: list[ArchiveEntry] = []
    owner = SimpleNamespace(
        _related_material_sidecar_entry_for_archive_entry=lambda _entry: sidecar,
        _open_material_sidecar_editor=opened.append,
    )

    ArchiveBrowserActionMixin._add_archive_material_context_action(
        owner,
        menu,
        {"texture": object()},
        _entry("character/model/armor.pac"),
    )
    action = menu.actions[0]
    callback = action.triggered.callbacks[0]
    assert callable(callback)
    callback()

    assert action.enabled is True
    assert opened == [sidecar]
