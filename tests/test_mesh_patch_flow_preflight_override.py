"""A failed final preflight asks before a direct archive patch, as it does before a loose export.

The blocker dialog offered `Export Anyway (Unsafe)` for loose export and only
`OK` for a direct patch, and the override flag was dropped for the patch
destination before the commit even ran. Both destinations now get the choice.
"""

from __future__ import annotations

from pathlib import Path


PATCH_FLOW = Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "archive_browser" / "mesh_patch_flow.py"


def test_direct_patch_gets_the_unsafe_override_choice_and_honours_it() -> None:
    source = PATCH_FLOW.read_text(encoding="utf-8")

    assert '"Patch Anyway (Unsafe)" if destination == "patch" else "Export Anyway (Unsafe)"' in source
    assert "Continuing direct archive patch despite material preflight blocker(s)" in source
    assert "Continuing direct archive patch despite material authority report blocker(s)" in source
    assert "Continuing direct archive patch even though final package preflight could not be built." in source
    assert "Patching game archive files with unsafe material preflight override..." in source
    # The override is read for both destinations and the dialog offers it for both.
    assert 'destination == "loose" and unsafe_material_preflight_override' not in source
    assert (
        'unsafe_material_preflight_override = bool(getattr(static_replacement_options, "allow_unsafe_material_preflight_export", False))'
        in source
    )
    assert (
        'unsafe_export_available = not bool(getattr(static_replacement_options, "allow_unsafe_material_preflight_export", False))'
        in source
    )
