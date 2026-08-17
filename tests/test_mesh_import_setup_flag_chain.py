"""Every preset flag survives the whole setup chain, by signature and by field.

A workflow preset is threaded through five places before it reaches the Builder:
the async entry point, the preflight dispatcher, the prompt, the
`MeshImportSetupSelection` it constructs, and the dialog. Adding
`materials_and_textures_only` to four of the five shipped a crash on *every*
Import Mesh, not only the new command, because the prompt passes the keyword
unconditionally and the selection had no field for it.

Nothing caught it. The Builder construction gate builds the dialog rather than
the prompt, and the prompt cannot run headless because it calls `exec()`. So
this checks the chain the way the chain actually breaks: a name present in one
signature and absent from the next.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.ui.archive_browser.mesh_import_export import ArchiveMeshImportExportMixin
from cdmw.ui.archive_browser.mesh_import_preflight_controller import (
    dispatch_mesh_import_setup_preflight,
)
from cdmw.ui.archive_browser.static_replacement_dialog import (
    ArchiveStaticReplacementDialogMixin,
)


#: The workflow presets the setup chain carries. A new one belongs here the
#: moment it is threaded anywhere, which is the point.
PRESET_FLAGS = ("full_import_model_replacement", "materials_and_textures_only")

_LINKS = {
    "_prepare_archive_mesh_import_setup_async": ArchiveMeshImportExportMixin._prepare_archive_mesh_import_setup_async,
    "dispatch_mesh_import_setup_preflight": dispatch_mesh_import_setup_preflight,
    "_prompt_archive_mesh_import_setup": ArchiveMeshImportExportMixin._prompt_archive_mesh_import_setup,
    "_prompt_archive_static_replacement_options": ArchiveStaticReplacementDialogMixin._prompt_archive_static_replacement_options,
}


@pytest.mark.parametrize("flag", PRESET_FLAGS)
@pytest.mark.parametrize("name,function", sorted(_LINKS.items()))
def test_every_link_in_the_setup_chain_accepts_the_flag(
    flag: str, name: str, function: object
) -> None:
    assert flag in inspect.signature(function).parameters, f"{name} drops {flag}"


@pytest.mark.parametrize("flag", PRESET_FLAGS)
def test_the_selection_has_a_field_for_the_flag(flag: str) -> None:
    # The failure this pins: the prompt passed the keyword and the dataclass
    # had no field, so constructing the selection raised TypeError on every
    # Import Mesh regardless of which preset the user picked.
    assert flag in MeshImportSetupSelection.__dataclass_fields__


def test_the_selection_accepts_every_flag_at_once() -> None:
    selection = MeshImportSetupSelection(
        scene_path=Path("model.glb"),
        import_mode="static_replacement",
        **{flag: True for flag in PRESET_FLAGS},
    )

    for flag in PRESET_FLAGS:
        assert getattr(selection, flag) is True


def test_the_flags_default_to_off() -> None:
    selection = MeshImportSetupSelection(scene_path=Path("model.glb"), import_mode="roundtrip")

    for flag in PRESET_FLAGS:
        assert getattr(selection, flag) is False
