"""Validated output-path and edit-operation helpers for the .NET Mesh Editor package."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Mapping

from cdmw.core.atomic_file import atomic_copy_file
from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts


def resolve_package_output_path(package: object, value: Path | str, *, label: str) -> Path:
    raw_value = str(value or "").strip()
    if not raw_value or "\x00" in raw_value:
        raise ValueError(f"Mesh .NET {label} path is invalid.")
    normalized_value = raw_value.replace("\\", "/")
    if ".." in PurePosixPath(normalized_value).parts:
        raise ValueError(f"Mesh .NET {label} path contains traversal.")
    try:
        package_root = package.package_dir.resolve(strict=True)
        output_root = package.output_dir.resolve(strict=True)
        output_root.relative_to(package_root)
    except OSError as exc:
        raise ValueError("Mesh .NET package output directory is unavailable.") from exc
    except ValueError as exc:
        raise ValueError("Mesh .NET package output directory escapes its package root.") from exc
    if not output_root.is_dir():
        raise ValueError("Mesh .NET package output directory is unavailable.")
    raw_path = Path(normalized_value).expanduser()
    candidate = raw_path if raw_path.is_absolute() else output_root / raw_path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(output_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Mesh .NET {label} path escapes the package output directory.") from exc
    for input_path in (package.mesh_path, package.scene_mesh_path):
        if input_path is None:
            continue
        try:
            input_resolved = Path(input_path).resolve(strict=False)
        except OSError:
            input_resolved = Path(input_path)
        physical_alias = False
        try:
            physical_alias = (
                resolved.is_file()
                and input_resolved.is_file()
                and os.path.samefile(resolved, input_resolved)
            )
        except OSError:
            pass
        if resolved == input_resolved or physical_alias:
            raise ValueError(f"Mesh .NET {label} path aliases an input OBJ.")
    return resolved


def obj_candidates_in_dir(directory: Path) -> tuple[Path, ...]:
    return directory / "mesh.obj", directory / "edited_mesh.obj", directory / "edited.obj"


def ensure_output_sidecar(package: object, obj_path: Path) -> None:
    contained_obj_path = resolve_package_output_path(package, obj_path, label="edited OBJ")
    sidecar_path = resolve_package_output_path(
        package,
        Path(f"{contained_obj_path}.meta.json"),
        label="edited OBJ sidecar",
    )
    if sidecar_path.is_file():
        return
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_copy_file(package.obj_sidecar_path, sidecar_path)


def dotnet_edit_operations_path(
    package: object,
    status_payload: Mapping[str, object] | None,
) -> Path:
    raw_value = str((status_payload or {}).get("edit_operations", "") or "").strip()
    value = raw_value if raw_value else package.edit_operations_path
    return resolve_package_output_path(package, value, label="edit_operations")


def load_dotnet_edit_operations(path: Path) -> tuple[object, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("operations", ())
    if not isinstance(payload, list):
        raise ValueError("Mesh .NET edit operations must be a JSON list.")
    return mesh_edit_operations_from_dicts(payload)


__all__ = [
    "dotnet_edit_operations_path",
    "ensure_output_sidecar",
    "load_dotnet_edit_operations",
    "obj_candidates_in_dir",
    "resolve_package_output_path",
]
