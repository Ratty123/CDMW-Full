"""Stable capture names, sizes, and plan construction."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Mapping, Sequence


HARNESS_DESCRIPTION = """Capture deterministic Compact Workspace geometry and screenshots.

The harness constructs one production ``MainWindow`` with temporary settings,
then visits the same registered tool instances at the reference and responsive
window sizes.  Fixture rows are added directly to views with signals blocked;
the harness never opens or mutates game archives.
"""

REFERENCE_FILENAMES: Mapping[str, str] = {
    "archive_browser": "01-browse-archives.png",
    "model_library": "02-model-library.png",
    "item_icons": "03-item-icons.png",
    "new_item_studio": "04-create-new-item.png",
    "mesh_editor": "05-mesh-editor.png",
    "placement_studio": "06-placement-animation.png",
    "texture_workflow": "07-upscale-process-textures.png",
    "replace_assistant": "08-replace-textures.png",
    "recolor_variants": "09-recolor-variants.png",
    "texture_editor": "10-texture-editor.png",
    "mod_package_retrofit": "11-repackage-mods.png",
    "format_explorer": "12-inspect-file-formats.png",
    "translation_studio": "13-edit-translations.png",
    "research": "14-asset-research.png",
    "text_search": "15-search-file-text.png",
}

REFERENCE_SIZE = (1672, 941)
RESPONSIVE_SIZES = ((1360, 840), (1120, 720))
_SIZE_PATTERN = re.compile(r"^(?P<width>[1-9][0-9]*)x(?P<height>[1-9][0-9]*)$")
SYNTHETIC_MESH_SESSION_ID = "compact-visual-fixture"
SYNTHETIC_MESH_SOURCE_PATH = "tools/harness_quad.pac"
EXPECTED_MESH_RENDERER_BACKEND = "d3d11_vortice_shader"
EXPECTED_MESH_EDIT_BACKEND = "cdmw_mesh_core_0.1"
MESH_RENDERER_READY_TIMEOUT_SECONDS = 20.0
_BUNDLED_HELPER_RESOLUTION_SOURCES = frozenset(
    {
        "source_release",
        "source_debug",
        "native_release",
        "native_debug",
        "frozen_root_flat",
        "frozen_root_release",
        "frozen_root_debug",
        "exe_root_flat",
        "exe_root_internal_flat",
        "exe_root_release",
        "exe_root_internal_release",
        "exe_root_debug",
        "exe_root_internal_debug",
    }
)


def parse_size(value: str) -> tuple[int, int]:
    """Parse a CLI size without accepting ambiguous separators or zeroes."""

    match = _SIZE_PATTERN.fullmatch(str(value).strip().lower())
    if match is None:
        raise argparse.ArgumentTypeError("size must use WIDTHxHEIGHT, for example 1672x941")
    return int(match.group("width")), int(match.group("height"))


def capture_sizes(primary: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    """Return the requested size first and the two required responsive sizes."""

    ordered = (primary, *RESPONSIVE_SIZES)
    return tuple(dict.fromkeys(ordered))


def relative_capture_path(
    key: str,
    size: tuple[int, int],
    primary: tuple[int, int],
) -> Path:
    """Map primary captures one-to-one to reference filenames."""

    filename = REFERENCE_FILENAMES[key]
    if size == primary:
        return Path(filename)
    return Path("responsive") / f"{size[0]}x{size[1]}" / filename


def build_capture_plan(
    keys: Sequence[str],
    primary: tuple[int, int],
) -> tuple[tuple[str, tuple[int, int], Path], ...]:
    return tuple(
        (key, size, relative_capture_path(key, size, primary))
        for size in capture_sizes(primary)
        for key in keys
    )
