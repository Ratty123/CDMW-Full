from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run_identity_check(*, owners_first: bool) -> None:
    script = r"""
from importlib import import_module
import sys

service_names = (
    "cdmw.services.preview_rendering_service",
    "cdmw.services.preview_workflow_service",
)
owner_names = {
    "cdmw.core.archive_binary_preview",
    "cdmw.core.archive_mesh_import_preview",
    "cdmw.core.final_package_preview",
    "cdmw.core.model_preview_orientation",
    "cdmw.core.texture_pipeline.preview",
    "cdmw.rendering.material_combiner",
    "cdmw.rendering.model_preview_prepare",
    "cdmw.rendering.native_preview_core",
    "cdmw.rendering.native_preview_package_cache",
    "cdmw.rendering.native_preview_package_writer",
    "cdmw.rendering.static_model_thumbnail",
}
if sys.argv[1] == "owners-first":
    for owner_name in owner_names:
        import_module(owner_name)
services = tuple(import_module(name) for name in service_names)
if sys.argv[1] != "owners-first":
    assert owner_names.isdisjoint(sys.modules)
for service in services:
    for name, (module_name, attribute_name) in service._EXPORTS.items():
        assert getattr(service, name) is getattr(import_module(module_name), attribute_name), name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, "owners-first" if owners_first else "services-first"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_preview_services_are_lazy_and_keep_owner_identity() -> None:
    _run_identity_check(owners_first=False)
    _run_identity_check(owners_first=True)
