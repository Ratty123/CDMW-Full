from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_preview_textures import (
    texture_set_for_mapping,
)


def _texture_set(name: str, source_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        material_name=name,
        slots={"base": SimpleNamespace(source_path=source_path)},
    )


def test_face_dominance_cannot_override_a_second_resolved_material() -> None:
    included_base = Path("textures/lambert1_baseColor.png")
    body = _texture_set("lambert1", included_base)
    gem = _texture_set("Gem_inside", Path("generated/gem_inside.png"))
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(faces=[None] * 200),
            SimpleNamespace(faces=[None] * 2),
        ]
    )

    selected = texture_set_for_mapping(
        SimpleNamespace(source_submesh_indices=(0, 1)),
        texture_sets={"lambert1": body, "gem_inside": gem},
        replacement_mesh=mesh,
        texture_set_for_source_index=lambda index, _sets: body if index == 0 else gem,
    )

    assert selected is None


def test_balanced_mixed_mapping_remains_unresolved() -> None:
    body = _texture_set("Body", Path("textures/body.png"))
    trim = _texture_set("Trim", Path("textures/trim.png"))
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(faces=[None] * 10),
            SimpleNamespace(faces=[None] * 10),
        ]
    )

    assert texture_set_for_mapping(
        SimpleNamespace(source_submesh_indices=(0, 1)),
        texture_sets={"body": body, "trim": trim},
        replacement_mesh=mesh,
        texture_set_for_source_index=lambda index, _sets: body if index == 0 else trim,
    ) is None


def test_bare_majority_does_not_override_second_material() -> None:
    body = _texture_set("Body", Path("textures/body.png"))
    trim = _texture_set("Trim", Path("textures/trim.png"))
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(faces=[None] * 51),
            SimpleNamespace(faces=[None] * 49),
        ]
    )

    assert texture_set_for_mapping(
        SimpleNamespace(source_submesh_indices=(0, 1)),
        texture_sets={"body": body, "trim": trim},
        replacement_mesh=mesh,
        texture_set_for_source_index=lambda index, _sets: body if index == 0 else trim,
    ) is None
