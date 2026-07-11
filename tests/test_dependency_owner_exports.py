from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _assert_identity_in_clean_process(import_order: tuple[str, ...]) -> None:
    script = """
import importlib
import sys

for module_name in sys.argv[1:]:
    importlib.import_module(module_name)

from cdmw.core import upscale_profiles
from cdmw.core import atomic_file, common
from cdmw.domain import cancellation
from cdmw.domain.textures import semantics
from cdmw.domain import workspace
from cdmw import models
from cdmw.services import atomic_file_service, cancellable_file_service, process_control_service
from cdmw.services import workspace_layout

assert models.RunCancelled is cancellation.RunCancelled
assert common.RunCancelled is cancellation.RunCancelled
assert common.raise_if_cancelled is cancellation.raise_if_cancelled
assert atomic_file_service.atomic_write_text is atomic_file.atomic_write_text
assert atomic_file_service.atomic_publish_files is atomic_file.atomic_publish_files
assert cancellable_file_service.read_file_bytes_cancellable is common.read_file_bytes_cancellable
assert cancellable_file_service.read_text_file_cancellable is common.read_text_file_cancellable
assert process_control_service.force_stop_windows_process_tree is common.force_stop_windows_process_tree
assert upscale_profiles.TextureUpscaleDecision is semantics.TextureUpscaleDecision
assert upscale_profiles.should_upscale_texture is semantics.should_upscale_texture
assert upscale_profiles.is_technical_texture_type is semantics.is_technical_texture_type
assert upscale_profiles.is_png_intermediate_high_risk is semantics.is_png_intermediate_high_risk
assert workspace_layout.workspace_root is workspace.workspace_root
assert workspace_layout.workspace_path is workspace.workspace_path
assert workspace_layout.workspace_paths is workspace.workspace_paths
assert workspace_layout.default_mod_package_export_root is workspace.default_mod_package_export_root
assert workspace_layout.app_root_from_workspace_member is workspace.app_root_from_workspace_member
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, *import_order],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_dependency_owner_exports_keep_identity_in_both_import_orders() -> None:
    _assert_identity_in_clean_process(
        (
            "cdmw.domain.cancellation",
            "cdmw.domain.textures.semantics",
            "cdmw.core.atomic_file",
            "cdmw.core.common",
            "cdmw.core.upscale_profiles",
            "cdmw.domain.workspace",
            "cdmw.services.atomic_file_service",
            "cdmw.services.cancellable_file_service",
            "cdmw.services.process_control_service",
            "cdmw.services.workspace_layout",
        )
    )


def test_archive_mutation_dtos_are_domain_owned_and_service_import_is_lazy() -> None:
    script = """
import sys
from cdmw.services import archive_mutation_service
assert "cdmw.core.archive_patching" not in sys.modules
from cdmw.domain.archives import mutation
from cdmw.core import archive_patching
assert archive_mutation_service.ArchivePatchRequest is mutation.ArchivePatchRequest
assert archive_mutation_service.ArchivePatchResult is mutation.ArchivePatchResult
assert archive_patching.ArchivePatchRequest is mutation.ArchivePatchRequest
assert archive_patching.ArchivePatchResult is mutation.ArchivePatchResult
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    _assert_identity_in_clean_process(
        (
            "cdmw.services.process_control_service",
            "cdmw.services.cancellable_file_service",
            "cdmw.services.atomic_file_service",
            "cdmw.services.workspace_layout",
            "cdmw.domain.workspace",
            "cdmw.core.upscale_profiles",
            "cdmw.core.common",
            "cdmw.core.atomic_file",
            "cdmw.domain.textures.semantics",
            "cdmw.domain.cancellation",
        )
    )
