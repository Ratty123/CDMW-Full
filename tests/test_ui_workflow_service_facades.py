from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_focused_ui_workflow_service_facades_are_lazy_and_identity_preserving() -> None:
    script = """
import sys
from cdmw.services import (
    hkx_edit_service,
    material_sidecar_service,
    replace_assistant_service,
    startup_splash_service,
    text_search_service,
)
for owner in (
    'cdmw.core.archive_hkx',
    'cdmw.core.material_sidecar_editor',
    'cdmw.core.replace_assistant',
    'cdmw.core.startup_splash_protocol',
    'cdmw.core.text_search',
):
    assert owner not in sys.modules, owner

from cdmw.core import archive_hkx
assert hkx_edit_service.apply_hkx_editable_geometry_xml is archive_hkx.apply_hkx_editable_geometry_xml
assert 'cdmw.core.material_sidecar_editor' not in sys.modules
from cdmw.core import material_sidecar_editor
assert material_sidecar_service.is_material_sidecar_entry is material_sidecar_editor.is_material_sidecar_entry
from cdmw.core import replace_assistant
assert replace_assistant_service.build_replace_assistant_items is replace_assistant.build_replace_assistant_items
from cdmw.core import startup_splash_protocol
assert startup_splash_service.cleanup_startup_splash_artifacts is startup_splash_protocol.cleanup_startup_splash_artifacts
from cdmw.core import text_search
assert text_search_service.TextSearchResult is text_search.TextSearchResult
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
