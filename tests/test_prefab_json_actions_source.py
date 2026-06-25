from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_prefab_context_menu_exposes_edit_json_actions() -> None:
    source = _read("cdmw/ui/archive_browser/actions.py")

    assert "Export Decode JSON..." in source
    assert "Export Prefab Edit JSON..." in source
    assert "Import Prefab Edit JSON..." in source
    assert "self._export_current_archive_prefab_edit_json()" in source
    assert "self._import_current_archive_prefab_edit_json()" in source


def test_prefab_json_actions_write_loose_package_not_archive_patch() -> None:
    source = _read("cdmw/ui/archive_browser/prefab_json_actions.py")

    assert "apply_prefab_edit_json" in source
    assert "allow_experimental_length_change" not in source
    assert "Only same-length resource and placement edits are importable in V1." in source
    assert "export_archive_payloads_to_mod_ready_loose" in source
    assert "ArchivePatchRequest(entry, patched)" in source
    assert "Original game archives will not be modified." in source
    forbidden_archive_mutators = (
        "apply_archive_patch_requests",
        "patch_archive_entries",
        "ArchivePatchResult",
        "_apply_archive_patch_result",
        "_write_paz_payload",
        "_write_bytes_preserve_timestamps",
        ".write_bytes(",
        ".paz",
        ".pamt",
    )
    for forbidden in forbidden_archive_mutators:
        assert forbidden not in source


def test_prefab_json_mixin_is_composed_into_main_window() -> None:
    source = _read("cdmw/ui/shell/app_window.py")

    assert "ArchivePrefabJsonActionsMixin" in source
    assert "from cdmw.ui.archive_browser.prefab_json_actions import ArchivePrefabJsonActionsMixin" in source
