from __future__ import annotations

from functools import lru_cache
from pathlib import Path


# Guard inputs are immutable within one pytest process; bound retained aggregates.
@lru_cache(maxsize=16)
def _sources(root: Path, patterns: tuple[str, ...]) -> str:
    owner_root = root / "cdmw" / "ui" / "archive_browser"
    paths = {
        path
        for pattern in patterns
        for path in owner_root.glob(pattern)
        if path.is_file()
    }
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(paths))


def static_replacement_callback_factory_source(root: Path) -> str:
    return _sources(
        root,
        (
            "static_replacement_dialog_callback_factories.py",
            "static_replacement_dialog_factory_owners.py",
            "static_replacement_dialog_factory_runtime.py",
            "static_replacement_dialog_callbacks_*_part_*.py",
        ),
    )


def static_replacement_callback_implementation_source(root: Path) -> str:
    return _sources(root, ("static_replacement_dialog_callbacks_*_part_*.py",))


def static_replacement_callback_concern_source(root: Path, concern: str) -> str:
    return _sources(
        root,
        (f"static_replacement_dialog_callbacks_{concern}_part_*.py",),
    )


def static_replacement_callback_family_source(root: Path, family: str) -> str:
    return _sources(
        root,
        (
            f"static_replacement_dialog_{family}_callbacks.py",
            f"static_replacement_dialog_callbacks_{family}_part_*.py",
            f"static_replacement_dialog_callbacks_{family}_*_part_*.py",
        ),
    )


def static_replacement_remaining_callback_source(root: Path) -> str:
    return static_replacement_callback_family_source(root, "remaining")


def static_replacement_texture_callback_source(root: Path) -> str:
    return static_replacement_callback_family_source(root, "texture")


def static_replacement_source_part_mutation_callback_source(root: Path) -> str:
    return static_replacement_callback_family_source(root, "source_part_mutation")


def static_replacement_routing_callback_source(root: Path) -> str:
    return static_replacement_callback_family_source(root, "routing")


def static_replacement_mesh_edit_implementation_source(root: Path) -> str:
    return _sources(
        root,
        (
            "static_replacement_dialog_mesh_edit_callbacks.py",
            "static_replacement_mesh_edit_*.py",
        ),
    )


def static_replacement_ui_section_source(root: Path) -> str:
    return _sources(
        root,
        (
            "static_replacement_dialog_ui_sections.py",
            "static_replacement_dialog_factory_owners.py",
            "static_replacement_dialog_factory_runtime.py",
            "static_replacement_dialog_sections_*_part_*.py",
        ),
    )


def static_replacement_ui_implementation_source(root: Path) -> str:
    return _sources(root, ("static_replacement_dialog_sections_*_part_*.py",))


def static_replacement_ui_concern_source(root: Path, concern: str) -> str:
    return _sources(
        root,
        (f"static_replacement_dialog_sections_{concern}_part_*.py",),
    )
